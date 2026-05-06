from datetime import datetime, timezone
from app.extensions import db
from app.models.user import User, SubscriptionTier
from app.models.subscription import Subscription, Plan, SubscriptionStatus


def _tier_from_plan(plan: Plan) -> SubscriptionTier:
    return SubscriptionTier[plan.value]


def _plan_from_stripe_price(price_id: str, config: dict) -> Plan:
    mapping = {
        config["STRIPE_PRICE_INDIVIDUAL_MONTHLY"]: Plan.individual_monthly,
        config["STRIPE_PRICE_INDIVIDUAL_YEARLY"]: Plan.individual_yearly,
        config["STRIPE_PRICE_TEAM"]: Plan.team,
    }
    return mapping.get(price_id)


def handle_checkout_completed(session, config: dict) -> None:
    stripe_customer_id = session["customer"]
    stripe_subscription_id = session["subscription"]

    user = User.query.filter_by(stripe_customer_id=stripe_customer_id).first()
    if not user:
        return

    import stripe as stripe_lib
    stripe_lib.api_key = config["STRIPE_SECRET_KEY"]
    stripe_sub = stripe_lib.Subscription.retrieve(stripe_subscription_id)

    price_id = stripe_sub["items"]["data"][0]["price"]["id"]
    plan = _plan_from_stripe_price(price_id, config)
    if not plan:
        return

    subscription = Subscription.query.filter_by(user_id=user.id).first()
    if not subscription:
        subscription = Subscription(user_id=user.id, stripe_customer_id=stripe_customer_id)
        db.session.add(subscription)

    subscription.stripe_subscription_id = stripe_subscription_id
    subscription.plan = plan
    subscription.status = SubscriptionStatus.active
    subscription.cancel_at_period_end = False
    subscription.current_period_start = datetime.fromtimestamp(
        stripe_sub["current_period_start"], tz=timezone.utc
    )
    subscription.current_period_end = datetime.fromtimestamp(
        stripe_sub["current_period_end"], tz=timezone.utc
    )

    user.subscription_tier = _tier_from_plan(plan)
    user.trial_ends_at = None
    db.session.commit()


def handle_subscription_updated(stripe_sub, config: dict) -> None:
    sub = Subscription.query.filter_by(
        stripe_subscription_id=stripe_sub["id"]
    ).first()
    if not sub:
        return

    price_id = stripe_sub["items"]["data"][0]["price"]["id"]
    plan = _plan_from_stripe_price(price_id, config)

    stripe_status = stripe_sub["status"]
    status_map = {
        "active": SubscriptionStatus.active,
        "past_due": SubscriptionStatus.past_due,
        "incomplete": SubscriptionStatus.incomplete,
        "canceled": SubscriptionStatus.cancelled,
    }
    new_status = status_map.get(stripe_status, SubscriptionStatus.active)

    if plan:
        sub.plan = plan
    sub.status = new_status
    sub.cancel_at_period_end = stripe_sub.get("cancel_at_period_end", False)
    sub.current_period_start = datetime.fromtimestamp(
        stripe_sub["current_period_start"], tz=timezone.utc
    )
    sub.current_period_end = datetime.fromtimestamp(
        stripe_sub["current_period_end"], tz=timezone.utc
    )

    if plan:
        sub.user.subscription_tier = _tier_from_plan(plan)

    db.session.commit()


def handle_subscription_deleted(stripe_sub) -> None:
    sub = Subscription.query.filter_by(
        stripe_subscription_id=stripe_sub["id"]
    ).first()
    if not sub:
        return

    sub.status = SubscriptionStatus.cancelled
    sub.user.subscription_tier = SubscriptionTier.free_readonly
    db.session.commit()


def handle_payment_failed(invoice) -> None:
    stripe_subscription_id = invoice.get("subscription")
    if not stripe_subscription_id:
        return

    sub = Subscription.query.filter_by(
        stripe_subscription_id=stripe_subscription_id
    ).first()
    if sub:
        sub.status = SubscriptionStatus.past_due
        db.session.commit()
