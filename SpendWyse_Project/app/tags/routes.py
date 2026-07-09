from decimal import Decimal, InvalidOperation
from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.tag import Tag
from app.models.tag_rule import TagRule, RuleMatchType
from app.models.spend_cap import SpendCap, CapPeriod
from app.tags.cap_evaluator import evaluate_cap, evaluate_all_for_user
from app.utils.decorators import require_tier
from . import tags_bp, tag_rules_bp, spend_caps_bp

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


def _error(message: str, status: int):
    return jsonify({"error": message}), status


def _uid() -> int:
    return int(get_jwt_identity())


def _parent_creates_cycle(tag_id: int, proposed_parent_id, user_id: int) -> bool:
    """Walk up from the proposed parent; return True if `tag_id` appears.

    Also catches self-parenting and corrupted chains (defensive ceiling).
    """
    if proposed_parent_id is None:
        return False
    if proposed_parent_id == tag_id:
        return True

    visited = set()
    current_id = proposed_parent_id
    while current_id is not None:
        if current_id == tag_id or current_id in visited:
            return True
        visited.add(current_id)
        parent = Tag.query.filter_by(id=current_id, user_id=user_id).first()
        if parent is None:
            return False
        current_id = parent.parent_id
    return False


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
@tags_bp.get("/")
@require_tier(*ALL_TIERS)
def list_tags():
    tags = Tag.query.filter_by(user_id=_uid()).order_by(Tag.name.asc()).all()
    return jsonify({"tags": [t.to_dict() for t in tags]}), 200


@tags_bp.post("/")
@require_tier(*WRITE_TIERS)
def create_tag():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return _error("name is required", 400)

    parent_id = data.get("parent_id")
    if parent_id is not None:
        parent = Tag.query.filter_by(id=parent_id, user_id=_uid()).first()
        if not parent:
            return _error("parent_id does not refer to a tag you own", 400)

    tag = Tag(
        user_id=_uid(),
        name=name,
        color=data.get("color"),
        parent_id=parent_id,
        is_default=bool(data.get("is_default", False)),
        plaid_pfc_key=data.get("plaid_pfc_key"),
    )
    db.session.add(tag)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _error("tag with that name already exists", 409)
    return jsonify({"tag": tag.to_dict()}), 201


@tags_bp.put("/<int:tag_id>")
@require_tier(*WRITE_TIERS)
def update_tag(tag_id: int):
    tag = Tag.query.filter_by(id=tag_id, user_id=_uid()).first()
    if not tag:
        return _error("tag not found", 404)

    data = request.get_json(silent=True) or {}

    if "parent_id" in data:
        new_parent = data["parent_id"]
        if new_parent is not None:
            parent = Tag.query.filter_by(id=new_parent, user_id=_uid()).first()
            if not parent:
                return _error("parent_id does not refer to a tag you own", 400)
        if _parent_creates_cycle(tag.id, new_parent, _uid()):
            return _error("parent_id would create a cycle", 400)
        tag.parent_id = new_parent

    for field in ("name", "color", "plaid_pfc_key"):
        if field in data:
            setattr(tag, field, data[field])
    if "is_default" in data:
        tag.is_default = bool(data["is_default"])

    db.session.commit()
    return jsonify({"tag": tag.to_dict()}), 200


@tags_bp.delete("/<int:tag_id>")
@require_tier(*WRITE_TIERS)
def delete_tag(tag_id: int):
    tag = Tag.query.filter_by(id=tag_id, user_id=_uid()).first()
    if not tag:
        return _error("tag not found", 404)

    db.session.delete(tag)
    db.session.commit()
    return jsonify({"message": "tag deleted"}), 200


# ---------------------------------------------------------------------------
# Tag rules
# ---------------------------------------------------------------------------
@tag_rules_bp.get("/")
@require_tier(*ALL_TIERS)
def list_rules():
    rules = (
        TagRule.query
        .filter_by(user_id=_uid())
        .order_by(TagRule.priority.asc(), TagRule.id.asc())
        .all()
    )
    return jsonify({"rules": [r.to_dict() for r in rules]}), 200


@tag_rules_bp.post("/")
@require_tier(*WRITE_TIERS)
def create_rule():
    data = request.get_json(silent=True) or {}

    tag_id = data.get("tag_id")
    match_type_raw = data.get("match_type")
    match_value = (data.get("match_value") or "").strip()

    if not tag_id:
        return _error("tag_id is required", 400)
    if match_type_raw not in {m.value for m in RuleMatchType}:
        return _error("match_type is invalid", 400)
    if not match_value:
        return _error("match_value is required", 400)

    tag = Tag.query.filter_by(id=tag_id, user_id=_uid()).first()
    if not tag:
        return _error("tag not found", 404)

    try:
        priority = int(data.get("priority", 100))
    except (ValueError, TypeError):
        return _error("priority must be an integer", 400)

    rule = TagRule(
        user_id=_uid(),
        tag_id=tag_id,
        match_type=RuleMatchType(match_type_raw),
        match_value=match_value,
        priority=priority,
        is_active=bool(data.get("is_active", True)),
    )
    db.session.add(rule)
    db.session.commit()
    return jsonify({"rule": rule.to_dict()}), 201


@tag_rules_bp.put("/<int:rule_id>")
@require_tier(*WRITE_TIERS)
def update_rule(rule_id: int):
    rule = TagRule.query.filter_by(id=rule_id, user_id=_uid()).first()
    if not rule:
        return _error("rule not found", 404)

    data = request.get_json(silent=True) or {}

    if "tag_id" in data:
        tag = Tag.query.filter_by(id=data["tag_id"], user_id=_uid()).first()
        if not tag:
            return _error("tag not found", 404)
        rule.tag_id = data["tag_id"]

    if "match_type" in data:
        if data["match_type"] not in {m.value for m in RuleMatchType}:
            return _error("match_type is invalid", 400)
        rule.match_type = RuleMatchType(data["match_type"])

    if "match_value" in data:
        value = (data["match_value"] or "").strip()
        if not value:
            return _error("match_value cannot be empty", 400)
        rule.match_value = value

    if "priority" in data:
        try:
            rule.priority = int(data["priority"])
        except (ValueError, TypeError):
            return _error("priority must be an integer", 400)

    if "is_active" in data:
        rule.is_active = bool(data["is_active"])

    db.session.commit()
    return jsonify({"rule": rule.to_dict()}), 200


@tag_rules_bp.delete("/<int:rule_id>")
@require_tier(*WRITE_TIERS)
def delete_rule(rule_id: int):
    rule = TagRule.query.filter_by(id=rule_id, user_id=_uid()).first()
    if not rule:
        return _error("rule not found", 404)

    db.session.delete(rule)
    db.session.commit()
    return jsonify({"message": "rule deleted"}), 200


# ---------------------------------------------------------------------------
# Spend caps
# ---------------------------------------------------------------------------
@spend_caps_bp.get("/")
@require_tier(*ALL_TIERS)
def list_caps():
    caps = SpendCap.query.filter_by(user_id=_uid()).all()
    return jsonify({"caps": [c.to_dict() for c in caps]}), 200


@spend_caps_bp.get("/status")
@require_tier(*ALL_TIERS)
def caps_status_all():
    return jsonify({"caps": evaluate_all_for_user(_uid())}), 200


@spend_caps_bp.get("/<int:cap_id>/status")
@require_tier(*ALL_TIERS)
def cap_status_one(cap_id: int):
    cap = SpendCap.query.filter_by(id=cap_id, user_id=_uid()).first()
    if not cap:
        return _error("cap not found", 404)
    return jsonify({"cap": evaluate_cap(cap)}), 200


@spend_caps_bp.post("/")
@require_tier(*WRITE_TIERS)
def create_cap():
    data = request.get_json(silent=True) or {}

    tag_id = data.get("tag_id")
    period_raw = data.get("period", "monthly")
    limit_amount_raw = data.get("limit_amount")

    if not tag_id:
        return _error("tag_id is required", 400)
    if period_raw not in {p.value for p in CapPeriod}:
        return _error("period must be weekly, monthly, or yearly", 400)

    try:
        limit_amount = Decimal(str(limit_amount_raw))
        if limit_amount <= 0:
            raise InvalidOperation
    except (InvalidOperation, TypeError):
        return _error("limit_amount must be a positive number", 400)

    tag = Tag.query.filter_by(id=tag_id, user_id=_uid()).first()
    if not tag:
        return _error("tag not found", 404)

    cap = SpendCap(
        user_id=_uid(),
        tag_id=tag_id,
        period=CapPeriod(period_raw),
        limit_amount=limit_amount,
        currency=(data.get("currency", "USD") or "USD").upper()[:3],
        warn_pct=int(data.get("warn_pct", 80)),
        alert_pct=int(data.get("alert_pct", 100)),
        is_active=bool(data.get("is_active", True)),
    )
    db.session.add(cap)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _error("a cap for this tag and period already exists", 409)
    return jsonify({"cap": cap.to_dict()}), 201


@spend_caps_bp.put("/<int:cap_id>")
@require_tier(*WRITE_TIERS)
def update_cap(cap_id: int):
    cap = SpendCap.query.filter_by(id=cap_id, user_id=_uid()).first()
    if not cap:
        return _error("cap not found", 404)

    data = request.get_json(silent=True) or {}

    if "limit_amount" in data:
        try:
            amt = Decimal(str(data["limit_amount"]))
            if amt <= 0:
                raise InvalidOperation
            cap.limit_amount = amt
        except (InvalidOperation, TypeError):
            return _error("limit_amount must be a positive number", 400)

    if "period" in data:
        if data["period"] not in {p.value for p in CapPeriod}:
            return _error("period must be weekly, monthly, or yearly", 400)
        cap.period = CapPeriod(data["period"])

    for field in ("warn_pct", "alert_pct"):
        if field in data:
            try:
                setattr(cap, field, int(data[field]))
            except (ValueError, TypeError):
                return _error(f"{field} must be an integer", 400)

    if "currency" in data:
        cap.currency = (data["currency"] or "USD").upper()[:3]

    if "is_active" in data:
        cap.is_active = bool(data["is_active"])

    db.session.commit()
    return jsonify({"cap": cap.to_dict()}), 200


@spend_caps_bp.delete("/<int:cap_id>")
@require_tier(*WRITE_TIERS)
def delete_cap(cap_id: int):
    cap = SpendCap.query.filter_by(id=cap_id, user_id=_uid()).first()
    if not cap:
        return _error("cap not found", 404)

    db.session.delete(cap)
    db.session.commit()
    return jsonify({"message": "cap deleted"}), 200
