from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.utils.decorators import require_tier
from . import agents_bp
from .optimizer import run_audit


ALL_TIERS = (
    "free_trial",
    "free_readonly",
    "individual_monthly",
    "individual_yearly",
    "team",
)

MIN_LOOKBACK_DAYS = 60
MAX_LOOKBACK_DAYS = 730
DEFAULT_LOOKBACK_DAYS = 365


def _error(message: str, status: int):
    return jsonify({"error": message}), status


def _uid() -> int:
    return int(get_jwt_identity())


@agents_bp.get("/optimizer/audit")
@require_tier(*ALL_TIERS)
def optimizer_audit():
    try:
        lookback = int(request.args.get("lookback_days", DEFAULT_LOOKBACK_DAYS))
    except ValueError:
        return _error("lookback_days must be an integer", 400)
    if not MIN_LOOKBACK_DAYS <= lookback <= MAX_LOOKBACK_DAYS:
        return _error(
            f"lookback_days must be between {MIN_LOOKBACK_DAYS} and {MAX_LOOKBACK_DAYS}",
            400,
        )

    return jsonify(run_audit(_uid(), lookback_days=lookback)), 200
