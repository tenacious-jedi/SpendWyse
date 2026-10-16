from datetime import date
from decimal import Decimal, InvalidOperation

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.models.tag import Tag
from app.utils.dates import parse_month
from app.utils.decorators import require_tier
from . import agents_bp
from .optimizer import run_audit
from .savings_spend import (
    BASELINE_MONTHS,
    STATUS_TOLERANCE_PCT,
    compare_to_baseline,
    summarize_all_tags,
)


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

MIN_BASELINE_MONTHS = 1
MAX_BASELINE_MONTHS = 12


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


def _decimal_to_str(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return value


def _resolve_month(month_param):
    """Resolve a ?month=YYYY-MM arg to (year, month).

    Returns the current month when the arg is absent, or None when it is
    present but unparseable so the caller can return a 400.
    """
    if not month_param:
        today = date.today()
        return today.year, today.month
    return parse_month(month_param)


def _resolve_tolerance(raw):
    """Resolve a ?tolerance_pct= arg to a Decimal.

    Returns the default band when the arg is absent, or None when it is
    present but not a non-negative finite number so the caller can return a 400.
    """
    if raw is None:
        return STATUS_TOLERANCE_PCT
    try:
        value = Decimal(raw)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not value.is_finite() or value < 0:
        return None
    return value


def _resolve_baseline_months(raw):
    """Resolve a ?baseline_months= arg to an int.

    Returns the default window when the arg is absent, or None when it is
    present but not an integer in [MIN_BASELINE_MONTHS, MAX_BASELINE_MONTHS]
    so the caller can return a 400.
    """
    if raw is None:
        return BASELINE_MONTHS
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if not MIN_BASELINE_MONTHS <= value <= MAX_BASELINE_MONTHS:
        return None
    return value


@agents_bp.get("/savings-spend/tag/<int:tag_id>")
@require_tier(*ALL_TIERS)
def savings_spend_tag(tag_id: int):
    user_id = _uid()

    tag = Tag.query.filter_by(id=tag_id, user_id=user_id).first()
    if not tag:
        return _error("tag not found", 404)

    resolved = _resolve_month(request.args.get("month"))
    if resolved is None:
        return _error("month must be in YYYY-MM format", 400)
    year, month = resolved

    tolerance = _resolve_tolerance(request.args.get("tolerance_pct"))
    if tolerance is None:
        return _error("tolerance_pct must be a non-negative number", 400)

    baseline_months = _resolve_baseline_months(request.args.get("baseline_months"))
    if baseline_months is None:
        return _error(
            f"baseline_months must be an integer between "
            f"{MIN_BASELINE_MONTHS} and {MAX_BASELINE_MONTHS}",
            400,
        )

    result = compare_to_baseline(
        user_id, tag_id, year, month,
        tolerance_pct=tolerance,
        baseline_months=baseline_months,
    )

    result["current"] = _decimal_to_str(result["current"])
    result["baseline_avg"] = _decimal_to_str(result["baseline_avg"])
    result["delta"] = _decimal_to_str(result["delta"])
    result["pct_change"] = _decimal_to_str(result["pct_change"])
    result["baseline_months"] = [
        {**bm, "spend": _decimal_to_str(bm["spend"])}
        for bm in result["baseline_months"]
    ]
    # projection is None for past months; stringify its money fields otherwise.
    if result["projection"] is not None:
        proj = result["projection"]
        for f in ("projected", "projected_delta", "projected_pct_change"):
            proj[f] = _decimal_to_str(proj[f])
    result["tag_name"] = tag.name

    return jsonify(result), 200


@agents_bp.get("/savings-spend/summary")
@require_tier(*ALL_TIERS)
def savings_spend_summary():
    user_id = _uid()

    resolved = _resolve_month(request.args.get("month"))
    if resolved is None:
        return _error("month must be in YYYY-MM format", 400)
    year, month = resolved

    tolerance = _resolve_tolerance(request.args.get("tolerance_pct"))
    if tolerance is None:
        return _error("tolerance_pct must be a non-negative number", 400)

    baseline_months = _resolve_baseline_months(request.args.get("baseline_months"))
    if baseline_months is None:
        return _error(
            f"baseline_months must be an integer between "
            f"{MIN_BASELINE_MONTHS} and {MAX_BASELINE_MONTHS}",
            400,
        )

    result = summarize_all_tags(
        user_id, year, month,
        tolerance_pct=tolerance,
        baseline_months=baseline_months,
    )

    money_fields = ("current", "baseline_avg", "delta", "pct_change")
    result["tags"] = [
        {**row, **{f: _decimal_to_str(row[f]) for f in money_fields}}
        for row in result["tags"]
    ]
    result["totals"] = {
        k: _decimal_to_str(v) for k, v in result["totals"].items()
    }
    # Counts stay ints; _decimal_to_str leaves non-Decimals untouched.
    result["scorecard"] = {
        k: _decimal_to_str(v) for k, v in result["scorecard"].items()
    }

    return jsonify(result), 200
