# Membership and lifecycle rules for the multi-user "team" plan.
# Routes stay thin; all invariants (single active membership, owner protection,
# seat limits, soft-delete) live here so they are enforced in one place.
# author- manishap

from datetime import datetime, timezone

from app.extensions import db
from app.models.team import Team, TeamMember, TeamRole


class TeamError(Exception):
    """Raised for team rule violations; carries an HTTP status for the route layer."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.message = message
        self.status = status


def _now():
    return datetime.now(timezone.utc)


def get_active_membership(user_id: int):
    """The user's current (not-left) membership, or None."""
    return (
        TeamMember.query.filter_by(user_id=user_id, left_at=None)
        .order_by(TeamMember.joined_at.desc())
        .first()
    )


def get_membership(team_id: int, user_id: int):
    """Active membership of a user in a specific team, or None."""
    return TeamMember.query.filter_by(
        team_id=team_id, user_id=user_id, left_at=None
    ).first()


def active_member_count(team_id: int) -> int:
    return TeamMember.query.filter_by(team_id=team_id, left_at=None).count()


def list_active_members(team_id: int):
    return (
        TeamMember.query.filter_by(team_id=team_id, left_at=None)
        .order_by(TeamMember.joined_at.asc())
        .all()
    )


def create_team(owner_id: int, name: str) -> Team:
    """Create a team owned by owner_id and seat them as the owner member."""
    if not name or not name.strip():
        raise TeamError("name is required", 400)

    # A user may only belong to one active team at a time.
    if get_active_membership(owner_id) is not None:
        raise TeamError("user already belongs to a team", 409)

    team = Team(name=name.strip(), owner_id=owner_id)
    db.session.add(team)
    # Flush so team.id is available for the owner's membership row.
    db.session.flush()

    owner_member = TeamMember(
        team_id=team.id, user_id=owner_id, role=TeamRole.owner
    )
    db.session.add(owner_member)
    db.session.commit()
    return team


def remove_member(team_id: int, actor_id: int, target_user_id: int) -> None:
    """Owner removes another member. Soft-deletes the membership (frees a seat)."""
    team = db.session.get(Team, team_id)
    if team is None:
        raise TeamError("team not found", 404)
    if team.owner_id != actor_id:
        raise TeamError("only the team owner can remove members", 403)
    if target_user_id == team.owner_id:
        raise TeamError("the owner cannot be removed", 400)

    membership = get_membership(team_id, target_user_id)
    if membership is None:
        raise TeamError("member not found", 404)

    membership.left_at = _now()
    db.session.commit()


def leave_team(team_id: int, user_id: int) -> None:
    """A non-owner member leaves the team."""
    team = db.session.get(Team, team_id)
    if team is None:
        raise TeamError("team not found", 404)
    if team.owner_id == user_id:
        raise TeamError(
            "the owner cannot leave; transfer ownership or delete the team", 400
        )

    membership = get_membership(team_id, user_id)
    if membership is None:
        raise TeamError("you are not a member of this team", 404)

    membership.left_at = _now()
    db.session.commit()
