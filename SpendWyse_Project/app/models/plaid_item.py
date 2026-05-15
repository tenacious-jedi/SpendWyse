from datetime import datetime, timezone
from app.extensions import db


class PlaidItem(db.Model):
    __tablename__ = "plaid_items"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    plaid_item_id = db.Column(db.String(255), unique=True, nullable=False)
    access_token = db.Column(db.Text, nullable=False)
    institution_id = db.Column(db.String(100), nullable=True)
    institution_name = db.Column(db.String(255), nullable=True)
    cursor = db.Column(db.Text, nullable=True)
    last_synced_at = db.Column(db.DateTime(timezone=True), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

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

    user = db.relationship("User", backref=db.backref("plaid_items", lazy="dynamic"))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "institution_id": self.institution_id,
            "institution_name": self.institution_name,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
        }
