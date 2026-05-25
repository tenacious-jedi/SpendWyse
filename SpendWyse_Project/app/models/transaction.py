import enum
from datetime import datetime, timezone
from app.extensions import db


class TransactionType(enum.Enum):
    debit = "debit"
    credit = "credit"


class TransactionSource(enum.Enum):
    manual = "manual"
    plaid = "plaid"


class Transaction(db.Model):
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="USD")
    transaction_type = db.Column(db.Enum(TransactionType), nullable=False, default=TransactionType.debit)

    merchant = db.Column(db.String(255), nullable=True)
    # Free-text label (e.g. raw Plaid category, user note). Structured tagging
    # lives on `tag_id`; this stays as an optional supplement / fallback.
    category = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    transaction_date = db.Column(db.Date, nullable=False)

    source = db.Column(db.Enum(TransactionSource), nullable=False, default=TransactionSource.manual)
    plaid_transaction_id = db.Column(db.String(255), unique=True, nullable=True)

    tag_id = db.Column(
        db.Integer, db.ForeignKey("tags.id", ondelete="SET NULL"), nullable=True, index=True
    )

    is_deleted = db.Column(db.Boolean, nullable=False, default=False)
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

    user = db.relationship("User", backref=db.backref("transactions", lazy="dynamic"))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "amount": str(self.amount),
            "currency": self.currency,
            "transaction_type": self.transaction_type.value,
            "merchant": self.merchant,
            "category": self.category,
            "notes": self.notes,
            "transaction_date": self.transaction_date.isoformat(),
            "source": self.source.value,
            "tag_id": self.tag_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
