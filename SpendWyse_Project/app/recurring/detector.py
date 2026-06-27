from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import Optional

from app.extensions import db
from app.models.transaction import Transaction, TransactionType


MIN_CHARGES = 3
LOOKBACK_DAYS = 365
AMOUNT_TOLERANCE = Decimal("0.15")

# Day-count windows that count as each cadence.
# Designed to absorb weekend deferrals and short-month effects.
CADENCES = [
    ("weekly", 6, 8),
    ("monthly", 26, 33),
    ("yearly", 340, 385),
]


def detect_recurring(user_id: int, lookback_days: int = LOOKBACK_DAYS) -> list[dict]:
    """Return a list of likely recurring charges for the user.

    Heuristic: group debit transactions by merchant, then for each merchant
    with at least MIN_CHARGES charges, check whether the intervals between
    consecutive charges fit a known cadence and the amounts are stable.
    """
    cutoff = date.today() - timedelta(days=lookback_days)

    rows = (
        db.session.query(Transaction)
        .filter(
            Transaction.user_id == user_id,
            Transaction.transaction_type == TransactionType.debit,
            Transaction.is_deleted == False,  # noqa: E712
            Transaction.transaction_date >= cutoff,
            Transaction.merchant.isnot(None),
        )
        .order_by(Transaction.transaction_date.asc())
        .all()
    )

    groups: dict[str, list[Transaction]] = defaultdict(list)
    for txn in rows:
        key = (txn.merchant or "").strip().lower()
        if key:
            groups[key].append(txn)

    results: list[dict] = []
    for merchant_key, charges in groups.items():
        if len(charges) < MIN_CHARGES:
            continue

        candidate = _classify(charges)
        if candidate:
            results.append(candidate)

    results.sort(key=lambda r: Decimal(r["avg_amount"]), reverse=True)
    return results


def _classify(charges: list[Transaction]) -> Optional[dict]:
    intervals = [
        (charges[i + 1].transaction_date - charges[i].transaction_date).days
        for i in range(len(charges) - 1)
    ]
    if not intervals:
        return None

    cadence_label, hits = _best_cadence_fit(intervals)
    if not cadence_label:
        return None

    if not _amounts_stable(charges):
        return None

    amounts = [Decimal(str(c.amount)) for c in charges]
    avg = sum(amounts) / len(amounts)

    confidence = _confidence(hits, len(intervals), amounts)
    last = charges[-1]
    next_expected = _project_next(last.transaction_date, cadence_label)

    return {
        # Use the original-case form from the most recent charge for display.
        "merchant": last.merchant,
        "cadence": cadence_label,
        "avg_amount": str(avg.quantize(Decimal("0.01"))),
        "min_amount": str(min(amounts)),
        "max_amount": str(max(amounts)),
        "currency": last.currency,
        "charge_count": len(charges),
        "last_seen": last.transaction_date.isoformat(),
        "next_expected": next_expected.isoformat() if next_expected else None,
        "confidence": confidence,
    }


def _best_cadence_fit(intervals: list[int]) -> tuple[Optional[str], int]:
    best_label: Optional[str] = None
    best_hits = 0
    for label, lo, hi in CADENCES:
        hits = sum(1 for d in intervals if lo <= d <= hi)
        if hits > best_hits:
            best_hits = hits
            best_label = label

    # Need a clear majority of intervals to back the cadence claim.
    if best_hits < max(2, len(intervals) // 2 + 1):
        return None, 0
    return best_label, best_hits


def _amounts_stable(charges: list[Transaction]) -> bool:
    amounts = [Decimal(str(c.amount)) for c in charges]
    mid = Decimal(str(median(amounts)))
    if mid == 0:
        return False
    for a in amounts:
        if abs(a - mid) / mid > AMOUNT_TOLERANCE:
            return False
    return True


def _confidence(hits: int, total_intervals: int, amounts: list[Decimal]) -> str:
    interval_ratio = hits / total_intervals if total_intervals else 0
    mid = Decimal(str(median(amounts)))
    if mid == 0:
        amount_spread = Decimal("1")
    else:
        amount_spread = max(abs(a - mid) for a in amounts) / mid

    if interval_ratio >= 0.9 and amount_spread <= Decimal("0.05"):
        return "high"
    if interval_ratio >= 0.7 and amount_spread <= Decimal("0.10"):
        return "medium"
    return "low"


def _project_next(last_seen: date, cadence: str) -> Optional[date]:
    if cadence == "weekly":
        return last_seen + timedelta(days=7)
    if cadence == "monthly":
        return last_seen + timedelta(days=30)
    if cadence == "yearly":
        return last_seen + timedelta(days=365)
    return None
