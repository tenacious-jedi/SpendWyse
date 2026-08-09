from flask import request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.models.team import Team
from app.models.user import User
from app.extensions import db
from app.utils.decorators import require_tier
from app.utils.notifier import send_email
from app.teams import team_service, invitation_service
from app.teams.team_service import TeamError
from . import teams_bp


def _error(message: str, status: int):
    return jsonify({"error": message}), status


def _uid() -> int:
    return int(get_jwt_identity())


def _member_dict(member) -> dict:
    user = member.user
    return {
        "user_id": member.user_id,
        "role": member.role.value,
        "email": user.email if user else None,
        "first_name": user.first_name if user else None,
        "last_name": user.last_name if user else None,
        "joined_at": member.joined_at.isoformat(),
    }


def _team_dict(team: Team) -> dict:
    members = team_service.list_active_members(team.id)
    data = team.to_dict()
    data["seats_used"] = len(members)
    data["members"] = [_member_dict(m) for m in members]
    return data


@teams_bp.post("/")
@require_tier("team")
def create_team():
    data = request.get_json(silent=True) or {}
    try:
        team = team_service.create_team(_uid(), data.get("name", ""))
    except TeamError as exc:
        db.session.rollback()
        return _error(exc.message, exc.status)
    return jsonify({"team": _team_dict(team)}), 201


@teams_bp.get("/me")
@jwt_required()
def my_team():
    membership = team_service.get_active_membership(_uid())
    if membership is None:
        return _error("you do not belong to a team", 404)
    team = db.session.get(Team, membership.team_id)
    return jsonify({"team": _team_dict(team), "role": membership.role.value}), 200


@teams_bp.get("/<int:team_id>/members")
@jwt_required()
def list_members(team_id: int):
    # Only active members of the team may view its roster.
    if team_service.get_membership(team_id, _uid()) is None:
        return _error("team not found", 404)
    members = team_service.list_active_members(team_id)
    return jsonify({"members": [_member_dict(m) for m in members]}), 200


@teams_bp.delete("/<int:team_id>/members/<int:user_id>")
@jwt_required()
def remove_member(team_id: int, user_id: int):
    try:
        team_service.remove_member(team_id, _uid(), user_id)
    except TeamError as exc:
        db.session.rollback()
        return _error(exc.message, exc.status)
    return jsonify({"message": "member removed"}), 200


@teams_bp.post("/<int:team_id>/leave")
@jwt_required()
def leave_team(team_id: int):
    try:
        team_service.leave_team(team_id, _uid())
    except TeamError as exc:
        db.session.rollback()
        return _error(exc.message, exc.status)
    return jsonify({"message": "left team"}), 200


def _send_invite_email(team: Team, email: str, raw_token: str) -> None:
    base = current_app.config.get("TEAM_INVITE_URL", "")
    link = f"{base}?token={raw_token}" if base else raw_token
    body = (
        f"Hi,\n\n"
        f"You've been invited to join the \"{team.name}\" team on SpendWyse. "
        f"Use the link below within the next 7 days to accept:\n\n"
        f"{link}\n\n"
        f"If you weren't expecting this, you can ignore this email.\n\n"
        f"— SpendWyse"
    )
    error = send_email(email, "[SpendWyse] You've been invited to a team", body)
    if error:
        current_app.logger.warning("team invite email failed: %s", error)


@teams_bp.post("/<int:team_id>/invitations")
@jwt_required()
def create_invitation(team_id: int):
    data = request.get_json(silent=True) or {}
    try:
        invitation, raw_token = invitation_service.create_invitation(
            team_id, _uid(), data.get("email", "")
        )
    except TeamError as exc:
        db.session.rollback()
        return _error(exc.message, exc.status)

    team = db.session.get(Team, team_id)
    _send_invite_email(team, invitation.email, raw_token)
    return jsonify({"invitation": invitation.to_dict()}), 201


@teams_bp.get("/<int:team_id>/invitations")
@jwt_required()
def list_invitations(team_id: int):
    # Owner-only view of outstanding invitations.
    team = db.session.get(Team, team_id)
    if team is None or team.owner_id != _uid():
        return _error("team not found", 404)
    invites = invitation_service.pending_invitations(team_id)
    return jsonify({"invitations": [i.to_dict() for i in invites]}), 200


@teams_bp.delete("/<int:team_id>/invitations/<int:invitation_id>")
@jwt_required()
def revoke_invitation(team_id: int, invitation_id: int):
    try:
        invitation_service.revoke_invitation(team_id, _uid(), invitation_id)
    except TeamError as exc:
        db.session.rollback()
        return _error(exc.message, exc.status)
    return jsonify({"message": "invitation revoked"}), 200


@teams_bp.post("/invitations/accept")
@jwt_required()
def accept_invitation():
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return _error("token is required", 400)

    user = db.session.get(User, _uid())
    if user is None or not user.is_active:
        return _error("user not found", 404)

    try:
        team = invitation_service.accept_invitation(token, user)
    except TeamError as exc:
        db.session.rollback()
        return _error(exc.message, exc.status)
    return jsonify({"message": "joined team", "team": _team_dict(team)}), 200
