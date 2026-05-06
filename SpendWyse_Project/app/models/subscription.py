import enum
from datetime import datetime, timezone
from app.extensions import db


class Plan(enum.Enum):
    individual_monthly = "individual_monthly"
    individual_yearly = "individual_yearly"
    team = "team"


class SubscriptionStatus(enum.Enum):
    active = "active"
    past_due = "past_due"
    cancelled = "cancelled"
    incomplete = "incomplete"


class Subscription(db.Model):
    __tablename__ = "subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    stripe_subscription_id = db.Column(db.String(255), unique=True, nullable=True)
    stripe_customer_id = db.Column(db.String(255), nullable=False)
    plan = db.Column(db.Enum(Plan), nullable=False)
    status = db.Column(db.Enum(SubscriptionStatus), nullable=False, default=SubscriptionStatus.active)
    current_period_start = db.Column(db.DateTime(timezone=True), nullable=True)
    current_period_end = db.Column(db.DateTime(timezone=True), nullable=True)
    cancel_at_period_end = db.Column(db.Boolean, nullable=False, default=False)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=True)
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

    user = db.relationship("User", back_populates="subscription")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "plan": self.plan.value,
            "status": self.status.value,
            "current_period_start": self.current_period_start.isoformat() if self.current_period_start else None,
            "current_period_end": self.current_period_end.isoformat() if self.current_period_end else None,
            "cancel_at_period_end": self.cancel_at_period_end,
        }
