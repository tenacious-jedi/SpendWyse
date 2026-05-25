import enum
from datetime import datetime, timezone
from app.extensions import db


class TeamRole(enum.Enum):
    owner = "owner"
    member = "member"


class Team(db.Model):
    __tablename__ = "teams"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    max_seats = db.Column(db.Integer, nullable=False, default=5)
    stripe_subscription_id = db.Column(db.String(255), unique=True, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    members = db.relationship("TeamMember", back_populates="team", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "owner_id": self.owner_id,
            "max_seats": self.max_seats,
        }


class TeamMember(db.Model):
    __tablename__ = "team_members"

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    role = db.Column(db.Enum(TeamRole), nullable=False, default=TeamRole.member)
    joined_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # Soft-delete: set when the member leaves; active membership = NULL.
    left_at = db.Column(db.DateTime(timezone=True), nullable=True)

    team = db.relationship("Team", back_populates="members")
    user = db.relationship("User")

    __table_args__ = (db.UniqueConstraint("team_id", "user_id"),)
