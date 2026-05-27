import calendar
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func

from app.extensions import db
from app.models.spend_cap import SpendCap, CapPeriod
from app.models.transaction import Transaction, TransactionType


def period_window(period: CapPeriod, on_date: date) -> tuple[date, date]:
    if period == CapPeriod.weekly:
        # ISO week: Monday (weekday=0) through Sunday (weekday=6).
        start = on_date - timedelta(days=on_date.weekday())
        end = start + timedelta(days=6)
        return start, end

    if period == CapPeriod.monthly:
        start = on_date.replace(day=1)
        last_day = calendar.monthrange(on_date.year, on_date.month)[1]
        end = on_date.replace(day=last_day)
        return start, end

    if period == CapPeriod.yearly:
        return date(on_date.year, 1, 1), date(on_date.year, 12, 31)

    raise ValueError(f"unsupported period: {period}")


def _spent_in_window(user_id: int, tag_id: int, start: date, end: date) -> Decimal:
    total = db.session.query(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).filter(
        Transaction.user_id == user_id,
        Transaction.tag_id == tag_id,
        Transaction.transaction_type == TransactionType.debit,
        Transaction.is_deleted == False,  # noqa: E712 (SQLAlchemy needs ==)
        Transaction.transaction_date >= start,
        Transaction.transaction_date <= end,
    ).scalar()
    return Decimal(total)


def evaluate_cap(cap: SpendCap, on_date: Optional[date] = None) -> dict:
    if on_date is None:
        on_date = date.today()

    start, end = period_window(cap.period, on_date)
    spent = _spent_in_window(cap.user_id, cap.tag_id, start, end)

    pct = float((spent / cap.limit_amount) * 100)

    if pct >= cap.alert_pct:
        status = "alert"
    elif pct >= cap.warn_pct:
        status = "warn"
    else:
        status = "ok"

    return {
        "cap_id": cap.id,
        "tag_id": cap.tag_id,
        "period": cap.period.value,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "limit_amount": str(cap.limit_amount),
        "spent": str(spent),
        "remaining": str(cap.limit_amount - spent),
        "pct": round(pct, 1),
        "warn_pct": cap.warn_pct,
        "alert_pct": cap.alert_pct,
        "currency": cap.currency,
        "status": status,
    }


def evaluate_all_for_user(user_id: int, on_date: Optional[date] = None) -> list[dict]:
    caps = SpendCap.query.filter_by(user_id=user_id, is_active=True).all()
    return [evaluate_cap(cap, on_date) for cap in caps]
