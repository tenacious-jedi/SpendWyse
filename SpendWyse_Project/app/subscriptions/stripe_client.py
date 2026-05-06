import stripe
from flask import current_app


def _stripe():
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
    return stripe


def create_customer(email: str, name: str) -> str:
    """Creates a Stripe customer and returns the customer ID."""
    customer = _stripe().Customer.create(email=email, name=name)
    return customer.id


def create_checkout_session(
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Creates a Stripe Checkout Session and returns the session URL."""
    session = _stripe().checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        subscription_data={"trial_period_days": 0},
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return session.url


def create_portal_session(customer_id: str, return_url: str) -> str:
    """Creates a Stripe Customer Portal session and returns the URL."""
    session = _stripe().billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return session.url


def cancel_subscription_at_period_end(stripe_subscription_id: str) -> dict:
    """Schedules a subscription to cancel at the end of the current period."""
    sub = _stripe().Subscription.modify(
        stripe_subscription_id,
        cancel_at_period_end=True,
    )
    return sub


def construct_webhook_event(payload: bytes, sig_header: str) -> stripe.Event:
    return _stripe().Webhook.construct_event(
        payload,
        sig_header,
        current_app.config["STRIPE_WEBHOOK_SECRET"],
    )
