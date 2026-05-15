from datetime import datetime, timezone
from app.extensions import db


class Tag(db.Model):
    __tablename__ = "tags"
    __table_args__ = (
        db.UniqueConstraint("user_id", "name", name="uq_tag_user_name"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("tags.id"), nullable=True, index=True)

    name = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(7), nullable=True)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    plaid_pfc_key = db.Column(db.String(100), nullable=True, index=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = db.relationship("User", backref=db.backref("tags", lazy="dynamic"))
    parent = db.relationship("Tag", remote_side="Tag.id", backref="children")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "is_default": self.is_default,
            "plaid_pfc_key": self.plaid_pfc_key,
            "parent_id": self.parent_id,
            "created_at": self.created_at.isoformat(),
        }
