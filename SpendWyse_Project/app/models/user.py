import enum
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db
from app.models.alert import AlertLevel

TRIAL_DAYS = 30


class SubscriptionTier(enum.Enum):
    free_trial = "free_trial"
    free_readonly = "free_readonly"
    individual_monthly = "individual_monthly"
    individual_yearly = "individual_yearly"
    team = "team"


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    subscription_tier = db.Column(
        db.Enum(SubscriptionTier),
        nullable=False,
        default=SubscriptionTier.free_trial,
    )
    stripe_customer_id = db.Column(db.String(255), unique=True, nullable=True)
    trial_ends_at = db.Column(db.DateTime(timezone=True), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    alerts_email_enabled = db.Column(db.Boolean, nullable=False, default=True)
    alerts_email_min_level = db.Column(
        db.Enum(AlertLevel), nullable=False, default=AlertLevel.warn
    )
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

    subscription = db.relationship(
        "Subscription", back_populates="user", uselist=False
    )

    @property
    def effective_tier(self) -> SubscriptionTier:
        """Returns free_readonly once the trial window has closed."""
        if (
            self.subscription_tier == SubscriptionTier.free_trial
            and self.trial_ends_at
            and datetime.now(timezone.utc) > self.trial_ends_at
        ):
            return SubscriptionTier.free_readonly
        return self.subscription_tier

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "subscription_tier": self.effective_tier.value,
            "trial_ends_at": self.trial_ends_at.isoformat() if self.trial_ends_at else None,
            "is_active": self.is_active,
            "alerts_email_enabled": self.alerts_email_enabled,
            "alerts_email_min_level": self.alerts_email_min_level.value,
            "created_at": self.created_at.isoformat(),
        }
