import calendar
from datetime import date
from typing import Optional

from sqlalchemy import case, func

from app.extensions import db
from app.models.tag import Tag
from app.models.transaction import Transaction, TransactionType


TOP_MERCHANTS = 10


def _month_window(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _previous_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def monthly_report(user_id: int, year: int, month: int) -> dict:
    start, end = _month_window(year, month)

    totals = db.session.query(
        func.coalesce(
            func.sum(
                case(
                    (Transaction.transaction_type == TransactionType.debit, Transaction.amount),
                    else_=0,
                )
            ),
            0,
        ).label("total_spent"),
        func.coalesce(
            func.sum(
                case(
                    (Transaction.transaction_type == TransactionType.credit, Transaction.amount),
                    else_=0,
                )
            ),
            0,
        ).label("total_income"),
    ).filter(
        Transaction.user_id == user_id,
        Transaction.is_deleted == False,  # noqa: E712
        Transaction.transaction_date >= start,
        Transaction.transaction_date <= end,
    ).one()

    by_tag_rows = (
        db.session.query(
            Transaction.tag_id,
            Tag.name,
            func.coalesce(func.sum(Transaction.amount), 0).label("spent"),
            func.count(Transaction.id).label("count"),
        )
        .outerjoin(Tag, Tag.id == Transaction.tag_id)
        .filter(
            Transaction.user_id == user_id,
            Transaction.transaction_type == TransactionType.debit,
            Transaction.is_deleted == False,  # noqa: E712
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
        .group_by(Transaction.tag_id, Tag.name)
        .order_by(func.sum(Transaction.amount).desc())
        .all()
    )

    by_merchant_rows = (
        db.session.query(
            Transaction.merchant,
            func.coalesce(func.sum(Transaction.amount), 0).label("spent"),
            func.count(Transaction.id).label("count"),
        )
        .filter(
            Transaction.user_id == user_id,
            Transaction.transaction_type == TransactionType.debit,
            Transaction.is_deleted == False,  # noqa: E712
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
            Transaction.merchant.isnot(None),
        )
        .group_by(Transaction.merchant)
        .order_by(func.sum(Transaction.amount).desc())
        .limit(TOP_MERCHANTS)
        .all()
    )

    return {
        "month": f"{year:04d}-{month:02d}",
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "total_spent": str(totals.total_spent),
        "total_income": str(totals.total_income),
        "by_tag": [
            {
                "tag_id": row.tag_id,
                "tag_name": row.name,
                "spent": str(row.spent),
                "count": row.count,
            }
            for row in by_tag_rows
        ],
        "by_merchant": [
            {
                "merchant": row.merchant,
                "spent": str(row.spent),
                "count": row.count,
            }
            for row in by_merchant_rows
        ],
    }


def trend_report(user_id: int, tag_id: Optional[int], months: int) -> list[dict]:
    today = date.today()
    year, month = today.year, today.month

    windows: list[tuple[int, int]] = []
    for _ in range(months):
        windows.append((year, month))
        year, month = _previous_month(year, month)
    windows.reverse()

    results = []
    for y, m in windows:
        start, end = _month_window(y, m)
        q = db.session.query(
            func.coalesce(func.sum(Transaction.amount), 0)
        ).filter(
            Transaction.user_id == user_id,
            Transaction.transaction_type == TransactionType.debit,
            Transaction.is_deleted == False,  # noqa: E712
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
        if tag_id is not None:
            q = q.filter(Transaction.tag_id == tag_id)

        results.append({
            "month": f"{y:04d}-{m:02d}",
            "spent": str(q.scalar()),
        })

    return results


def month_totals(user_id: int, year: int, month: int) -> dict:
    """Lightweight version of monthly_report; just the top-line numbers."""
    start, end = _month_window(year, month)

    row = db.session.query(
        func.coalesce(
            func.sum(
                case(
                    (Transaction.transaction_type == TransactionType.debit, Transaction.amount),
                    else_=0,
                )
            ),
            0,
        ).label("spent"),
        func.coalesce(
            func.sum(
                case(
                    (Transaction.transaction_type == TransactionType.credit, Transaction.amount),
                    else_=0,
                )
            ),
            0,
        ).label("income"),
    ).filter(
        Transaction.user_id == user_id,
        Transaction.is_deleted == False,  # noqa: E712
        Transaction.transaction_date >= start,
        Transaction.transaction_date <= end,
    ).one()

    return {
        "month": f"{year:04d}-{month:02d}",
        "spent": str(row.spent),
        "income": str(row.income),
    }
