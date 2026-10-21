from flask import request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
import stripe

from app.events.idempotency import already_processed, mark_processed
from app.extensions import db
from app.models.user import User
from app.models.subscription import Subscription
from . import subscriptions_bp
from .stripe_client import (
    create_checkout_session,
    create_portal_session,
    cancel_subscription_at_period_end,
    construct_webhook_event,
)
from .webhook import (
    handle_checkout_completed,
    handle_subscription_updated,
    handle_subscription_deleted,
    handle_payment_failed,
)

PLAN_TO_PRICE_KEY = {
    "individual_monthly": "STRIPE_PRICE_INDIVIDUAL_MONTHLY",
    "individual_yearly": "STRIPE_PRICE_INDIVIDUAL_YEARLY",
    "team": "STRIPE_PRICE_TEAM",
}

# Namespace for Stripe events in the processed_events idempotency ledger.
STRIPE_CONSUMER_GROUP = "stripe-webhook"


def _error(message: str, status: int):
    return jsonify({"error": message}), status


@subscriptions_bp.get("/me")
@jwt_required()
def get_my_subscription():
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return _error("user not found", 404)

    sub = Subscription.query.filter_by(user_id=user.id).first()
    return jsonify({
        "tier": user.effective_tier.value,
        "trial_ends_at": user.trial_ends_at.isoformat() if user.trial_ends_at else None,
        "subscription": sub.to_dict() if sub else None,
    }), 200


@subscriptions_bp.post("/checkout")
@jwt_required()
def checkout():
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return _error("user not found", 404)

    if not user.stripe_customer_id:
        return _error("stripe customer not set up for this account", 400)

    data = request.get_json(silent=True) or {}
    plan = data.get("plan", "")
    if plan not in PLAN_TO_PRICE_KEY:
        return _error(f"plan must be one of: {', '.join(PLAN_TO_PRICE_KEY)}", 400)

    price_id = current_app.config.get(PLAN_TO_PRICE_KEY[plan], "")
    if not price_id:
        return _error("this plan is not configured yet", 503)

    checkout_url = create_checkout_session(
        customer_id=user.stripe_customer_id,
        price_id=price_id,
        success_url=current_app.config["STRIPE_SUCCESS_URL"],
        cancel_url=current_app.config["STRIPE_CANCEL_URL"],
    )
    return jsonify({"checkout_url": checkout_url}), 200


@subscriptions_bp.post("/portal")
@jwt_required()
def portal():
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return _error("user not found", 404)

    if not user.stripe_customer_id:
        return _error("no billing account found", 400)

    portal_url = create_portal_session(
        customer_id=user.stripe_customer_id,
        return_url=current_app.config["STRIPE_CANCEL_URL"],
    )
    return jsonify({"portal_url": portal_url}), 200


@subscriptions_bp.post("/cancel")
@jwt_required()
def cancel():
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return _error("user not found", 404)

    sub = Subscription.query.filter_by(user_id=user.id).first()
    if not sub or not sub.stripe_subscription_id:
        return _error("no active subscription found", 404)

    cancel_subscription_at_period_end(sub.stripe_subscription_id)
    sub.cancel_at_period_end = True
    db.session.commit()

    return jsonify({
        "message": "subscription will cancel at end of billing period",
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
    }), 200


@subscriptions_bp.post("/webhook")
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = construct_webhook_event(payload, sig_header)
    except stripe.error.SignatureVerificationError:
        return _error("invalid webhook signature", 400)
    except Exception:
        return _error("webhook error", 400)

    config = current_app.config
    event_type = event["type"]
    event_id = event.get("id")
    data = event["data"]["object"]

    # Stripe delivers at least once and retries on any non-2xx, so the same
    # event id can arrive more than once. Skip anything already applied; the
    # processed_events unique constraint is the backstop against a race.
    if event_id and already_processed(STRIPE_CONSUMER_GROUP, event_id):
        return jsonify({"received": True, "deduped": True}), 200

    if event_type == "checkout.session.completed":
        handle_checkout_completed(data, config)
    elif event_type == "customer.subscription.updated":
        handle_subscription_updated(data, config)
    elif event_type == "customer.subscription.deleted":
        handle_subscription_deleted(data)
    elif event_type == "invoice.payment_failed":
        handle_payment_failed(data)
    else:
        # An event type we don't act on; ack without recording so it is neither
        # retried nor fills the ledger.
        return jsonify({"received": True, "handled": False}), 200

    # Record only after a handled event is applied, so a crash mid-handling
    # leaves it reprocessable (the handlers are idempotent set-state updates).
    if event_id:
        mark_processed(STRIPE_CONSUMER_GROUP, event_id)

    return jsonify({"received": True}), 200
