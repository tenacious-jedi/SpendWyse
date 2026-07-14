from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import func

from app.extensions import db
from app.models.transaction import Transaction, TransactionType


def monthly_tag_spend(
    user_id: int,
    tag_id: Optional[int],
    year: int,
    month: int,
) -> Decimal:
    if not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")

    period_start = date(year, month, 1)
    if month == 12:
        period_end = date(year + 1, 1, 1)
    else:
        period_end = date(year, month + 1, 1)

    total = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.user_id == user_id,
            Transaction.tag_id == tag_id,
            Transaction.transaction_type == TransactionType.debit,
            Transaction.is_deleted.is_(False),
            Transaction.transaction_date >= period_start,
            Transaction.transaction_date < period_end,
        )
        .scalar()
    )

    return Decimal(total)
