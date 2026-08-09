# Pending invitations to join a team. The invitee may not have an account yet,
# so invitations are keyed by email; a single-use token binds acceptance to the
# intended recipient. Only the SHA-256 hash of the token is stored (same posture
# as password_reset_tokens) — the raw secret is emailed once and never persisted.
# author- manishap

import enum
from datetime import datetime, timezone

from app.extensions import db


class InvitationStatus(enum.Enum):
    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"


class TeamInvitation(db.Model):
    __tablename__ = "team_invitations"

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(
        db.Integer,
        db.ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email = db.Column(db.String(255), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    status = db.Column(
        db.Enum(InvitationStatus), nullable=False, default=InvitationStatus.pending
    )
    invited_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    accepted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    accepted_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    team = db.relationship("Team", backref=db.backref("invitations", lazy="dynamic"))

    def is_pending(self) -> bool:
        if self.status != InvitationStatus.pending:
            return False
        return datetime.now(timezone.utc) < self.expires_at

    def to_dict(self) -> dict:
        # Never expose token_hash.
        return {
            "id": self.id,
            "team_id": self.team_id,
            "email": self.email,
            "status": self.status.value,
            "expires_at": self.expires_at.isoformat(),
            "created_at": self.created_at.isoformat(),
        }
