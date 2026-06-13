import enum
from datetime import datetime, timezone

from app.extensions import db


class AlertLevel(enum.Enum):
    warn = "warn"
    alert = "alert"


class Alert(db.Model):
    __tablename__ = "alerts"
    # Same cap should not notify twice at the same level within one period.
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "spend_cap_id", "period_start", "level",
            name="uq_alert_dedup",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    spend_cap_id = db.Column(
        db.Integer,
        db.ForeignKey("spend_caps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    level = db.Column(db.Enum(AlertLevel), nullable=False)
    period_start = db.Column(db.Date, nullable=False)

    spent = db.Column(db.Numeric(12, 2), nullable=False)
    limit_amount = db.Column(db.Numeric(12, 2), nullable=False)
    pct = db.Column(db.Float, nullable=False)

    delivered_at = db.Column(db.DateTime(timezone=True), nullable=True)
    delivery_error = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    user = db.relationship("User", backref=db.backref("alerts", lazy="dynamic"))
    spend_cap = db.relationship("SpendCap", backref=db.backref("alerts", lazy="dynamic"))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "spend_cap_id": self.spend_cap_id,
            "level": self.level.value,
            "period_start": self.period_start.isoformat(),
            "spent": str(self.spent),
            "limit_amount": str(self.limit_amount),
            "pct": self.pct,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "delivery_error": self.delivery_error,
            "created_at": self.created_at.isoformat(),
        }
