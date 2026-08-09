# Invitation lifecycle for the team plan: create, accept, revoke.
# Token handling mirrors app/auth/password_reset.py — only the SHA-256 hash is
# stored and comparisons are constant-time. Seat limits and the single-active-
# membership rule are enforced here so routes stay thin.
# author- manishap

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.team import Team, TeamMember, TeamRole
from app.models.team_invitation import TeamInvitation, InvitationStatus
from app.models.user import User
from app.teams import team_service
from app.teams.team_service import TeamError

# Invitations are valid for seven days.
INVITE_TTL = timedelta(days=7)
TOKEN_BYTES = 32


def _now():
    return datetime.now(timezone.utc)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def pending_invitations(team_id: int):
    """Non-expired, still-pending invitations for a team."""
    invites = TeamInvitation.query.filter_by(
        team_id=team_id, status=InvitationStatus.pending
    ).all()
    return [inv for inv in invites if inv.is_pending()]


def create_invitation(team_id: int, actor_id: int, email: str) -> tuple[TeamInvitation, str]:
    """Owner invites an email to the team. Returns (invitation, raw_token).

    The raw token is returned once for emailing and never persisted.
    """
    email = _normalize_email(email)
    if not email or "@" not in email:
        raise TeamError("a valid email is required", 400)

    team = db.session.get(Team, team_id)
    if team is None:
        raise TeamError("team not found", 404)
    if team.owner_id != actor_id:
        raise TeamError("only the team owner can invite members", 403)

    # Already an active member? Nothing to invite.
    existing = (
        db.session.query(TeamMember)
        .join(User, User.id == TeamMember.user_id)
        .filter(
            TeamMember.team_id == team_id,
            TeamMember.left_at.is_(None),
            db.func.lower(User.email) == email,
        )
        .first()
    )
    if existing is not None:
        raise TeamError("that user is already a team member", 409)

    # Reserve a seat against both active members and outstanding invitations.
    seats_taken = team_service.active_member_count(team_id) + len(
        pending_invitations(team_id)
    )
    if seats_taken >= team.max_seats:
        raise TeamError("no seats available", 409)

    # A fresh invite supersedes any earlier pending one for the same email.
    for prior in pending_invitations(team_id):
        if _normalize_email(prior.email) == email:
            prior.status = InvitationStatus.revoked

    raw = secrets.token_urlsafe(TOKEN_BYTES)
    invitation = TeamInvitation(
        team_id=team_id,
        email=email,
        token_hash=_hash(raw),
        invited_by_id=actor_id,
        expires_at=_now() + INVITE_TTL,
    )
    db.session.add(invitation)
    db.session.commit()
    return invitation, raw


def accept_invitation(raw_token: str, user: User) -> Team:
    """Accept a pending invitation. Seats the user as a member of the team.

    The accepting user's email must match the invited email so a leaked or
    forwarded token cannot pull an arbitrary account onto the team.
    """
    token_hash = _hash(raw_token or "")
    invitation = TeamInvitation.query.filter_by(token_hash=token_hash).first()
    if invitation is None:
        raise TeamError("invalid or expired invitation", 404)
    if not hmac.compare_digest(invitation.token_hash, token_hash):
        raise TeamError("invalid or expired invitation", 404)
    if not invitation.is_pending():
        raise TeamError("invalid or expired invitation", 404)

    if _normalize_email(user.email) != _normalize_email(invitation.email):
        raise TeamError("this invitation was issued to a different email", 403)

    # One active team per user.
    current = team_service.get_active_membership(user.id)
    if current is not None:
        if current.team_id == invitation.team_id:
            raise TeamError("you already belong to this team", 409)
        raise TeamError("you already belong to a team", 409)

    team = db.session.get(Team, invitation.team_id)
    if team is None:
        raise TeamError("team not found", 404)

    # Re-check seats at acceptance; invites may have outlived their reservation.
    if team_service.active_member_count(team.id) >= team.max_seats:
        raise TeamError("no seats available", 409)

    # A prior soft-deleted membership is reactivated rather than re-inserted,
    # since (team_id, user_id) is unique.
    prior = TeamMember.query.filter_by(team_id=team.id, user_id=user.id).first()
    if prior is not None:
        prior.left_at = None
        prior.role = TeamRole.member
        prior.joined_at = _now()
    else:
        db.session.add(
            TeamMember(team_id=team.id, user_id=user.id, role=TeamRole.member)
        )

    invitation.status = InvitationStatus.accepted
    invitation.accepted_at = _now()
    invitation.accepted_user_id = user.id
    db.session.commit()
    return team


def revoke_invitation(team_id: int, actor_id: int, invitation_id: int) -> None:
    """Owner cancels an outstanding invitation."""
    team = db.session.get(Team, team_id)
    if team is None:
        raise TeamError("team not found", 404)
    if team.owner_id != actor_id:
        raise TeamError("only the team owner can revoke invitations", 403)

    invitation = db.session.get(TeamInvitation, invitation_id)
    if invitation is None or invitation.team_id != team_id:
        raise TeamError("invitation not found", 404)
    if invitation.status != InvitationStatus.pending:
        raise TeamError("invitation is no longer pending", 409)

    invitation.status = InvitationStatus.revoked
    db.session.commit()
