from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import func

from app.extensions import db
from app.models.tag import Tag
from app.models.transaction import Transaction, TransactionType


BASELINE_MONTHS = 3

# A tag within this percentage of its baseline is treated as steady rather than
# a mover, so small month-to-month noise doesn't read as "over" or "under".
STATUS_TOLERANCE_PCT = Decimal("10")


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    if not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")

    period_start = date(year, month, 1)
    if month == 12:
        period_end = date(year + 1, 1, 1)
    else:
        period_end = date(year, month + 1, 1)

    return period_start, period_end


def monthly_tag_spend(
    user_id: int,
    tag_id: Optional[int],
    year: int,
    month: int,
) -> Decimal:
    period_start, period_end = _month_bounds(year, month)

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


def monthly_spend_by_tag(
    user_id: int,
    year: int,
    month: int,
) -> dict[Optional[int], Decimal]:
    """Total debit spend for a month grouped by tag_id, in a single query.

    Returned as {tag_id: total}; untagged spend lands under the None key.
    Only tags with spend in the month appear, so callers should treat a
    missing tag_id as $0.
    """
    period_start, period_end = _month_bounds(year, month)

    rows = (
        db.session.query(
            Transaction.tag_id,
            func.coalesce(func.sum(Transaction.amount), 0),
        )
        .filter(
            Transaction.user_id == user_id,
            Transaction.transaction_type == TransactionType.debit,
            Transaction.is_deleted.is_(False),
            Transaction.transaction_date >= period_start,
            Transaction.transaction_date < period_end,
        )
        .group_by(Transaction.tag_id)
        .all()
    )

    return {tag_id: Decimal(total) for tag_id, total in rows}


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


def _status(baseline_avg: Decimal, delta: Decimal, pct_change: Optional[Decimal]) -> str:
    """Classify a tag as over / under / on_track relative to its baseline."""
    if baseline_avg == 0:
        # No baseline to compare against; any positive spend is new activity.
        return "over" if delta > 0 else "on_track"
    if pct_change > STATUS_TOLERANCE_PCT:
        return "over"
    if pct_change < -STATUS_TOLERANCE_PCT:
        return "under"
    return "on_track"


def summarize_all_tags(user_id: int, year: int, month: int) -> dict:
    """Compare every tag's spend for a month against its trailing
    BASELINE_MONTHS-month average, ranked by the biggest increase first.

    Tags with no spend in either the target month or the baseline window are
    omitted (nothing to report). Untagged spend and any orphaned tag ids are
    excluded; only the user's own named tags are ranked. Totals cover exactly
    the tags returned, so they reconcile with the row list.
    """
    if not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")

    tag_names = {t.id: t.name for t in Tag.query.filter_by(user_id=user_id).all()}

    target_map = monthly_spend_by_tag(user_id, year, month)

    baseline_periods: list[tuple[int, int]] = []
    y, m = year, month
    for _ in range(BASELINE_MONTHS):
        y, m = _previous_month(y, m)
        baseline_periods.append((y, m))
    baseline_maps = [monthly_spend_by_tag(user_id, py, pm) for py, pm in baseline_periods]

    rows = []
    total_current = Decimal("0")
    total_baseline = Decimal("0")
    for tag_id, name in tag_names.items():
        current = target_map.get(tag_id, Decimal("0"))
        baseline_vals = [bm.get(tag_id, Decimal("0")) for bm in baseline_maps]
        baseline_avg = sum(baseline_vals, Decimal("0")) / Decimal(BASELINE_MONTHS)

        current_q = current.quantize(Decimal("0.01"))
        baseline_q = baseline_avg.quantize(Decimal("0.01"))
        # Nothing spent here in the whole window; skip so the summary stays signal.
        if current_q == 0 and baseline_q == 0:
            continue

        delta = (current_q - baseline_q).quantize(Decimal("0.01"))
        if baseline_q == 0:
            # pct_change against a $0 baseline would be a misleading infinity.
            pct_change: Optional[Decimal] = None
        else:
            pct_change = ((delta / baseline_q) * Decimal("100")).quantize(Decimal("0.1"))

        rows.append({
            "tag_id": tag_id,
            "tag_name": name,
            "current": current_q,
            "baseline_avg": baseline_q,
            "delta": delta,
            "pct_change": pct_change,
            "status": _status(baseline_q, delta, pct_change),
        })
        total_current += current_q
        total_baseline += baseline_q

    # Biggest overspend first; savings (negative delta) sink to the bottom.
    rows.sort(key=lambda r: r["delta"], reverse=True)

    total_current = total_current.quantize(Decimal("0.01"))
    total_baseline = total_baseline.quantize(Decimal("0.01"))
    return {
        "year": year,
        "month": month,
        "baseline_months": BASELINE_MONTHS,
        "tags": rows,
        "totals": {
            "current": total_current,
            "baseline_avg": total_baseline,
            "delta": (total_current - total_baseline).quantize(Decimal("0.01")),
        },
    }


def _previous_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1
