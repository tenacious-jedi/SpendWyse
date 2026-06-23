from datetime import datetime, timezone

from app.extensions import db


class PasswordResetToken(db.Model):
    __tablename__ = "password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Only the SHA-256 hash of the secret lives here.
    # The raw secret is emailed once and never persisted.
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    user = db.relationship("User", backref=db.backref("password_reset_tokens", lazy="dynamic"))

    def is_consumable(self) -> bool:
        if self.used_at is not None:
            return False
        return datetime.now(timezone.utc) < self.expires_at
