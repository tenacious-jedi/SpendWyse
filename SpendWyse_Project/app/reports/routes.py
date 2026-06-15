from datetime import date

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.models.alert import Alert
from app.models.spend_cap import SpendCap
from app.tags.cap_evaluator import evaluate_all_for_user
from app.utils.decorators import require_tier
from . import reports_bp
from .queries import month_totals, monthly_report, trend_report


ALL_TIERS = (
    "free_trial",
    "free_readonly",
    "individual_monthly",
    "individual_yearly",
    "team",
)

MIN_TREND_MONTHS = 1
MAX_TREND_MONTHS = 24
DEFAULT_TREND_MONTHS = 6
RECENT_ALERTS_LIMIT = 5


def _error(message: str, status: int):
    return jsonify({"error": message}), status


def _uid() -> int:
    return int(get_jwt_identity())


def _parse_month(value: str) -> tuple[int, int] | None:
    try:
        y, m = value.split("-")
        year, month = int(y), int(m)
        if 1 <= month <= 12 and year > 1900:
            return year, month
    except (ValueError, AttributeError):
        pass
    return None


@reports_bp.get("/monthly")
@require_tier(*ALL_TIERS)
def monthly():
    month_param = request.args.get("month")
    if month_param:
        parsed = _parse_month(month_param)
        if parsed is None:
            return _error("month must be in YYYY-MM format", 400)
        year, month = parsed
    else:
        today = date.today()
        year, month = today.year, today.month

    return jsonify(monthly_report(_uid(), year, month)), 200


@reports_bp.get("/trend")
@require_tier(*ALL_TIERS)
def trend():
    tag_id_raw = request.args.get("tag_id")
    tag_id: int | None
    if tag_id_raw:
        try:
            tag_id = int(tag_id_raw)
        except ValueError:
            return _error("tag_id must be an integer", 400)
    else:
        tag_id = None

    try:
        months = int(request.args.get("months", DEFAULT_TREND_MONTHS))
    except ValueError:
        return _error("months must be an integer", 400)
    if not MIN_TREND_MONTHS <= months <= MAX_TREND_MONTHS:
        return _error(
            f"months must be between {MIN_TREND_MONTHS} and {MAX_TREND_MONTHS}",
            400,
        )

    return jsonify({
        "tag_id": tag_id,
        "months": months,
        "series": trend_report(_uid(), tag_id, months),
    }), 200


@reports_bp.get("/summary")
@require_tier(*ALL_TIERS)
def summary():
    user_id = _uid()
    today = date.today()
    last_month_year, last_month = (
        (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    )

    this_month = month_totals(user_id, today.year, today.month)
    last_month_totals = month_totals(user_id, last_month_year, last_month)

    cap_statuses = evaluate_all_for_user(user_id)
    counts = {"ok": 0, "warn": 0, "alert": 0}
    for c in cap_statuses:
        counts[c["status"]] = counts.get(c["status"], 0) + 1

    active_caps_total = SpendCap.query.filter_by(
        user_id=user_id, is_active=True
    ).count()

    recent_alerts = (
        Alert.query
        .filter_by(user_id=user_id)
        .order_by(Alert.created_at.desc())
        .limit(RECENT_ALERTS_LIMIT)
        .all()
    )

    return jsonify({
        "this_month": this_month,
        "last_month": last_month_totals,
        "active_caps": {
            "total": active_caps_total,
            "ok": counts["ok"],
            "warn": counts["warn"],
            "alert": counts["alert"],
        },
        "recent_alerts": [a.to_dict() for a in recent_alerts],
    }), 200
