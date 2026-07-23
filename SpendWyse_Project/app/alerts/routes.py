from datetime import datetime, timezone

from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity

from app.extensions import db
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


def _error(message: str, status: int):
    return jsonify({"error": message}), status


@alerts_bp.get("/")
@require_tier(*ALL_TIERS)
def list_alerts():
    user_id = _uid()
    page = max(1, request.args.get("page", 1, type=int))
    page_size = max(
        1,
        min(
            request.args.get("page_size", DEFAULT_PAGE_SIZE, type=int),
            MAX_PAGE_SIZE,
        ),
    )

    pagination = (
        Alert.query
        .filter_by(user_id=user_id)
        .order_by(Alert.created_at.desc())
        .paginate(page=page, per_page=page_size, error_out=False)
    )

    unread_count = (
        Alert.query
        .filter_by(user_id=user_id, read_at=None)
        .count()
    )

    return jsonify({
        "alerts": [a.to_dict() for a in pagination.items],
        "unread_count": unread_count,
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


@alerts_bp.patch("/<int:alert_id>/read")
@require_tier(*WRITE_TIERS)
def mark_read(alert_id: int):
    alert = Alert.query.filter_by(id=alert_id, user_id=_uid()).first()
    if not alert:
        return _error("alert not found", 404)

    # Idempotent: repeated mark-read calls keep the original read_at
    # so the UI can rely on it as the first-seen timestamp.
    if alert.read_at is None:
        alert.read_at = datetime.now(timezone.utc)
        db.session.commit()

    return jsonify({"alert": alert.to_dict()}), 200


@alerts_bp.post("/read-all")
@require_tier(*WRITE_TIERS)
def mark_all_read():
    now = datetime.now(timezone.utc)
    updated = (
        Alert.query
        .filter_by(user_id=_uid(), read_at=None)
        .update({Alert.read_at: now}, synchronize_session=False)
    )
    db.session.commit()
    return jsonify({"marked_read": updated}), 200
