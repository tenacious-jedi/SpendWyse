from decimal import Decimal

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.utils.decorators import require_tier
from . import recurring_bp
from .detector import LOOKBACK_DAYS, detect_recurring, monthly_equivalent


ALL_TIERS = (
    "free_trial",
    "free_readonly",
    "individual_monthly",
    "individual_yearly",
    "team",
)

MIN_LOOKBACK_DAYS = 30
MAX_LOOKBACK_DAYS = 730


def _error(message: str, status: int):
    return jsonify({"error": message}), status


def _uid() -> int:
    return int(get_jwt_identity())


@recurring_bp.get("/subscriptions")
@require_tier(*ALL_TIERS)
def list_subscriptions():
    try:
        lookback = int(request.args.get("lookback_days", LOOKBACK_DAYS))
    except ValueError:
        return _error("lookback_days must be an integer", 400)
    if not MIN_LOOKBACK_DAYS <= lookback <= MAX_LOOKBACK_DAYS:
        return _error(
            f"lookback_days must be between {MIN_LOOKBACK_DAYS} and {MAX_LOOKBACK_DAYS}",
            400,
        )

    subs = detect_recurring(_uid(), lookback_days=lookback)
    # Decimal start value so an empty list sums to Decimal("0"), keeping the
    # math exact rather than dropping back to float.
    monthly_total = sum(
        (monthly_equivalent(Decimal(s["avg_amount"]), s["cadence"]) for s in subs),
        Decimal("0"),
    )

    return jsonify({
        "subscriptions": subs,
        "monthly_burn": str(monthly_total.quantize(Decimal("0.01"))),
        "lookback_days": lookback,
    }), 200
