from datetime import date
from decimal import Decimal

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.models.tag import Tag
from app.utils.decorators import require_tier
from . import agents_bp
from .optimizer import run_audit
from .savings_spend import compare_to_baseline


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


def _parse_month(value: str):
    try:
        y, m = value.split("-")
        year, month = int(y), int(m)
    except (ValueError, AttributeError):
        return None
    # Upper-bound the year to date's own range (max 9999); otherwise a value
    # like 99999 passes here and raises ValueError when a date is built.
    if not (1 <= month <= 12 and 1900 < year <= 9999):
        return None
    return year, month


def _decimal_to_str(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return value


@agents_bp.get("/savings-spend/tag/<int:tag_id>")
@require_tier(*ALL_TIERS)
def savings_spend_tag(tag_id: int):
    user_id = _uid()

    tag = Tag.query.filter_by(id=tag_id, user_id=user_id).first()
    if not tag:
        return _error("tag not found", 404)

    month_param = request.args.get("month")
    if month_param:
        parsed = _parse_month(month_param)
        if parsed is None:
            return _error("month must be in YYYY-MM format", 400)
        year, month = parsed
    else:
        today = date.today()
        year, month = today.year, today.month

    result = compare_to_baseline(user_id, tag_id, year, month)

    result["current"] = _decimal_to_str(result["current"])
    result["baseline_avg"] = _decimal_to_str(result["baseline_avg"])
    result["delta"] = _decimal_to_str(result["delta"])
    result["pct_change"] = _decimal_to_str(result["pct_change"])
    result["baseline_months"] = [
        {**bm, "spend": _decimal_to_str(bm["spend"])}
        for bm in result["baseline_months"]
    ]
    result["tag_name"] = tag.name

    return jsonify(result), 200
