from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity

from app.models.alert import Alert
from app.tags.alert_service import check_caps_and_notify
from app.utils.decorators import require_tier
from . import alerts_bp


ALL_TIERS = (
    "free_trial",
    "free_readonly",
    "individual_monthly",
    "individual_yearly",
    "team",
)
WRITE_TIERS = (
    "free_trial",
    "individual_monthly",
    "individual_yearly",
    "team",
)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _uid() -> int:
    return int(get_jwt_identity())


@alerts_bp.get("/")
@require_tier(*ALL_TIERS)
def list_alerts():
    page = max(1, request.args.get("page", 1, type=int))
    page_size = min(
        request.args.get("page_size", DEFAULT_PAGE_SIZE, type=int),
        MAX_PAGE_SIZE,
    )

    pagination = (
        Alert.query
        .filter_by(user_id=_uid())
        .order_by(Alert.created_at.desc())
        .paginate(page=page, per_page=page_size, error_out=False)
    )

    return jsonify({
        "alerts": [a.to_dict() for a in pagination.items],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": pagination.total,
            "pages": pagination.pages,
            "has_next": pagination.has_next,
            "has_prev": pagination.has_prev,
        },
    }), 200


@alerts_bp.get("/<int:alert_id>")
@require_tier(*ALL_TIERS)
def get_alert(alert_id: int):
    alert = Alert.query.filter_by(id=alert_id, user_id=_uid()).first()
    if not alert:
        return jsonify({"error": "alert not found"}), 404
    return jsonify({"alert": alert.to_dict()}), 200


@alerts_bp.post("/check")
@require_tier(*WRITE_TIERS)
def trigger_check():
    """Run cap evaluation and notification on demand for the current user."""
    actions = check_caps_and_notify(_uid())
    return jsonify({"actions": actions}), 200
