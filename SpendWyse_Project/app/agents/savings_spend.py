from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import func

from app.extensions import db
from app.models.transaction import Transaction, TransactionType


BASELINE_MONTHS = 3


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


def compare_to_baseline(
    user_id: int,
    tag_id: Optional[int],
    year: int,
    month: int,
) -> dict:
    """Compare a month's spend for a tag against the trailing
    BASELINE_MONTHS-month simple average.

    Months with no spend still count as $0 in the average, so callers
    get an honest "vs. last N months" number even for tags that only
    recently started seeing charges.

    pct_change is None when the baseline average is 0 to avoid a
    misleading infinity when the current month is any positive amount.
    """
    if not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")

    current = monthly_tag_spend(user_id, tag_id, year, month)

    baseline_periods: list[tuple[int, int]] = []
    y, m = year, month
    for _ in range(BASELINE_MONTHS):
        y, m = _previous_month(y, m)
        baseline_periods.append((y, m))

    per_month = [
        monthly_tag_spend(user_id, tag_id, py, pm) for py, pm in baseline_periods
    ]
    baseline_avg = (sum(per_month, Decimal("0")) / Decimal(BASELINE_MONTHS)).quantize(
        Decimal("0.01")
    )
    current_q = current.quantize(Decimal("0.01"))
    delta = (current_q - baseline_avg).quantize(Decimal("0.01"))

    if baseline_avg == 0:
        pct_change: Optional[Decimal] = None
    else:
        pct_change = ((delta / baseline_avg) * Decimal("100")).quantize(Decimal("0.1"))

    return {
        "tag_id": tag_id,
        "year": year,
        "month": month,
        "current": current_q,
        "baseline_avg": baseline_avg,
        "baseline_months": [
            {"year": py, "month": pm, "spend": per_month[i].quantize(Decimal("0.01"))}
            for i, (py, pm) in enumerate(baseline_periods)
        ],
        "delta": delta,
        "pct_change": pct_change,
    }


def _previous_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1
