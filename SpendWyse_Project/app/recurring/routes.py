from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.utils.decorators import require_tier
from . import recurring_bp
from .detector import LOOKBACK_DAYS, detect_recurring


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
    monthly_total = sum(_monthly_burn(s) for s in subs)

    return jsonify({
        "subscriptions": subs,
        "monthly_burn": str(round(monthly_total, 2)),
        "lookback_days": lookback,
    }), 200


def _monthly_burn(sub: dict) -> float:
    amount = float(sub["avg_amount"])
    if sub["cadence"] == "weekly":
        return amount * 4.33
    if sub["cadence"] == "monthly":
        return amount
    if sub["cadence"] == "yearly":
        return amount / 12.0
    return 0.0
