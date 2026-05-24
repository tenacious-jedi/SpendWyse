import enum
from datetime import datetime, timezone
from app.extensions import db


class CapPeriod(enum.Enum):
    weekly = "weekly"
    monthly = "monthly"
    yearly = "yearly"


class SpendCap(db.Model):
    __tablename__ = "spend_caps"
    __table_args__ = (
        db.UniqueConstraint("user_id", "tag_id", "period", name="uq_cap_user_tag_period"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tag_id = db.Column(
        db.Integer, db.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True
    )

    period = db.Column(db.Enum(CapPeriod), nullable=False, default=CapPeriod.monthly)
    limit_amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="USD")
    warn_pct = db.Column(db.Integer, nullable=False, default=80)
    alert_pct = db.Column(db.Integer, nullable=False, default=100)
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

    user = db.relationship("User", backref=db.backref("spend_caps", lazy="dynamic"))
    tag = db.relationship("Tag", backref=db.backref("spend_caps", lazy="dynamic"))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tag_id": self.tag_id,
            "period": self.period.value,
            "limit_amount": str(self.limit_amount),
            "currency": self.currency,
            "warn_pct": self.warn_pct,
            "alert_pct": self.alert_pct,
            "is_active": self.is_active,
        }
