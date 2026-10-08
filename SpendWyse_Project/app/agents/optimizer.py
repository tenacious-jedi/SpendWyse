from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func

from app.extensions import db
from app.models.transaction import Transaction, TransactionType
from app.recurring.detector import detect_recurring
from .categorizer import categorize


# Heuristic thresholds — collected at the top so they are easy to tune.
ANNUAL_RENEWAL_WINDOW_DAYS = 60
TRIAL_FIRST_CHARGE_MAX = Decimal("1.00")
TRIAL_MIN_LATER_RATIO = Decimal("3")
CATEGORY_HEAVY_THRESHOLD = Decimal("0.5")
PRICE_INCREASE_THRESHOLD = Decimal("1.10")
# Recurring charges below this amount are almost always bank micro-fees
# or card-verification charges rather than real subscriptions. Filtering
# them keeps the audit signal-to-noise high.
MIN_RECURRING_AMOUNT = Decimal("1.00")

# Minimum charge count -- within the audit lookback window -- to conclude
# a subscription has been running for at least 12 months. Weekly is 52
# not 48 (52/4.33 = 12.0mo); yearly is 2 charges (~24mo).
LONG_RUNNING_MIN_CHARGES = {
    "weekly": 52,
    "monthly": 12,
    "yearly": 2,
}

# Merchant patterns that hide the real service behind a payment processor.
PROCESSOR_PATTERNS = [
    "paddle.net",
    "stripe*",
    "sq *",
    "tst*",
    "sp *",
    "charge.com",
    "fastspring",
]


def run_audit(user_id: int, lookback_days: int = 365) -> dict:
    subs = detect_recurring(user_id, lookback_days=lookback_days)

    enriched = []
    for s in subs:
        if Decimal(s["avg_amount"]) < MIN_RECURRING_AMOUNT:
            continue
        s = dict(s)
        s["category"] = categorize(s.get("merchant"))
        s["monthly_cost"] = str(_monthly_cost(s).quantize(Decimal("0.01")))
        enriched.append(s)

    # Decimal start value so an empty audit sums to Decimal("0"), not int 0,
    # which has no .quantize() and would 500 the whole endpoint.
    monthly_burn = sum(
        (Decimal(s["monthly_cost"]) for s in enriched), Decimal("0")
    )

    by_category = _group_by_category(enriched)

    issues: list[dict] = []
    issues.extend(_find_duplicates(by_category))
    issues.extend(_find_trial_conversions(user_id, enriched, lookback_days))
    issues.extend(_find_upcoming_annual_renewals(enriched))
    issues.extend(_find_suspicious_merchants(enriched))
    issues.extend(_find_category_heavy(by_category, monthly_burn))
    issues.extend(_find_price_increases(enriched))
    issues.extend(_find_long_running(enriched))

    # Rank by dollar impact so the caller can render the actionable
    # (duplicates, trial conversions, price hikes) above the merely
    # informational (heads-up renewals, category-heavy notes).
    issues.sort(key=lambda i: Decimal(i["potential_savings_monthly"]), reverse=True)
    total_potential_savings = sum(
        (Decimal(i["potential_savings_monthly"]) for i in issues), Decimal("0")
    )

    return {
        "summary": {
            "monthly_burn": str(monthly_burn.quantize(Decimal("0.01"))),
            "subscription_count": len(enriched),
            "issue_count": len(issues),
            "total_potential_savings": str(total_potential_savings.quantize(Decimal("0.01"))),
            "lookback_days": lookback_days,
        },
        "by_category": [
            {
                "category": cat,
                "monthly_cost": str(sum(Decimal(s["monthly_cost"]) for s in items).quantize(Decimal("0.01"))),
                "count": len(items),
                "merchants": [s["merchant"] for s in items],
            }
            for cat, items in by_category.items()
        ],
        "subscriptions": enriched,
        "issues": issues,
    }


def _monthly_cost(sub: dict) -> Decimal:
    amount = Decimal(sub["avg_amount"])
    cadence = sub["cadence"]
    if cadence == "weekly":
        return amount * Decimal("4.33")
    if cadence == "monthly":
        return amount
    if cadence == "yearly":
        return amount / Decimal("12")
    return Decimal("0")


def _group_by_category(subs: list[dict]) -> dict[Optional[str], list[dict]]:
    grouped: dict[Optional[str], list[dict]] = defaultdict(list)
    for s in subs:
        grouped[s["category"]].append(s)
    return grouped


def _find_duplicates(by_category: dict[Optional[str], list[dict]]) -> list[dict]:
    issues = []
    for cat, items in by_category.items():
        if cat is None or len(items) < 2:
            continue
        costs = sorted(Decimal(s["monthly_cost"]) for s in items)
        # Worst-case savings if the user kept only the cheapest in the category.
        potential = sum(costs) - costs[0]
        issues.append({
            "type": "duplicate_service",
            "category": cat,
            "merchants": [s["merchant"] for s in items],
            "monthly_cost_combined": str(sum(costs).quantize(Decimal("0.01"))),
            "potential_savings_monthly": str(potential.quantize(Decimal("0.01"))),
            "rationale": (
                f"{len(items)} {cat.replace('_', ' ')} subscriptions costing "
                f"${sum(costs):.2f}/mo combined; consolidating could save up to "
                f"${potential:.2f}/mo."
            ),
        })
    return issues


def _find_trial_conversions(user_id: int, subs: list[dict], lookback_days: int) -> list[dict]:
    cutoff = date.today() - timedelta(days=lookback_days)
    issues = []
    for s in subs:
        merchant = s["merchant"]
        if not merchant:
            continue
        # Case-insensitive match: the recurring detector groups by
        # lowercased merchant name, so the raw string here may not
        # match rows stored with different casing (Plaid varies).
        first = (
            Transaction.query
            .filter(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.debit,
                Transaction.is_deleted == False,  # noqa: E712
                Transaction.transaction_date >= cutoff,
                func.lower(Transaction.merchant) == merchant.lower(),
            )
            .order_by(Transaction.transaction_date.asc())
            .first()
        )
        if not first:
            continue

        first_amount = Decimal(str(first.amount))
        avg_amount = Decimal(s["avg_amount"])
        if first_amount > TRIAL_FIRST_CHARGE_MAX:
            continue
        if avg_amount < first_amount * TRIAL_MIN_LATER_RATIO:
            continue

        issues.append({
            "type": "free_trial_converted",
            "merchant": merchant,
            "first_charge": str(first_amount),
            "first_charge_date": first.transaction_date.isoformat(),
            "current_amount": s["avg_amount"],
            "cadence": s["cadence"],
            "potential_savings_monthly": s["monthly_cost"],
            "rationale": (
                f"First charge was ${first_amount} on {first.transaction_date.isoformat()}; "
                f"now charging ${s['avg_amount']} per {s['cadence'].rstrip('ly')}."
            ),
        })
    return issues


def _find_upcoming_annual_renewals(subs: list[dict]) -> list[dict]:
    today = date.today()
    cutoff = today + timedelta(days=ANNUAL_RENEWAL_WINDOW_DAYS)
    issues = []
    for s in subs:
        if s["cadence"] != "yearly":
            continue
        nxt = s.get("next_expected")
        if not nxt:
            continue
        next_date = date.fromisoformat(nxt)
        if today <= next_date <= cutoff:
            issues.append({
                "type": "annual_renewal_upcoming",
                "merchant": s["merchant"],
                "amount": s["avg_amount"],
                "next_expected": nxt,
                "days_until": (next_date - today).days,
                "potential_savings_monthly": "0.00",
                "rationale": (
                    f"Annual subscription of ${s['avg_amount']} renews on {nxt} "
                    f"({(next_date - today).days} days away)."
                ),
            })
    return issues


def _find_suspicious_merchants(subs: list[dict]) -> list[dict]:
    issues = []
    for s in subs:
        merchant = (s.get("merchant") or "").lower()
        for pattern in PROCESSOR_PATTERNS:
            if pattern in merchant:
                issues.append({
                    "type": "suspicious_merchant",
                    "merchant": s["merchant"],
                    "monthly_cost": s["monthly_cost"],
                    "potential_savings_monthly": "0.00",
                    "rationale": (
                        "Merchant name looks like a payment processor; "
                        "the actual service is unclear — verify what this is."
                    ),
                })
                break
    return issues


def _find_category_heavy(
    by_category: dict[Optional[str], list[dict]],
    total_burn: Decimal,
) -> list[dict]:
    if total_burn <= 0:
        return []
    issues = []
    for cat, items in by_category.items():
        if cat is None:
            continue
        cat_total = sum(Decimal(s["monthly_cost"]) for s in items)
        share = cat_total / total_burn
        if share >= CATEGORY_HEAVY_THRESHOLD:
            issues.append({
                "type": "category_heavy",
                "category": cat,
                "monthly_cost": str(cat_total.quantize(Decimal("0.01"))),
                "share_of_total": f"{(share * 100).quantize(Decimal('0.1'))}%",
                "potential_savings_monthly": "0.00",
                "rationale": (
                    f"{cat.replace('_', ' ').title()} is "
                    f"{(share * 100).quantize(Decimal('0.1'))}% of your subscription burn."
                ),
            })
    return issues


def _find_price_increases(subs: list[dict]) -> list[dict]:
    issues = []
    for s in subs:
        try:
            low = Decimal(s["min_amount"])
            high = Decimal(s["max_amount"])
        except (KeyError, ValueError):
            continue
        if low <= 0 or high <= low:
            continue
        ratio = high / low
        if ratio < PRICE_INCREASE_THRESHOLD:
            continue

        pct = ((ratio - Decimal("1")) * Decimal("100")).quantize(Decimal("0.1"))
        # Monthly-equivalent of the per-cadence delta, so this can be
        # compared and summed against the other issue savings figures.
        savings = _monthly_from_amount(high - low, s["cadence"]).quantize(Decimal("0.01"))
        issues.append({
            "type": "price_increased",
            "merchant": s["merchant"],
            "cadence": s["cadence"],
            "min_amount": str(low.quantize(Decimal("0.01"))),
            "max_amount": str(high.quantize(Decimal("0.01"))),
            "pct_increase": f"{pct}%",
            "monthly_cost": s["monthly_cost"],
            "potential_savings_monthly": str(savings),
            "currency": s.get("currency"),
            "rationale": (
                f"{s['merchant']} went from ${low.quantize(Decimal('0.01'))} to "
                f"${high.quantize(Decimal('0.01'))} per {s['cadence'].rstrip('ly')} "
                f"({pct}% increase)."
            ),
        })
    return issues


def _find_long_running(subs: list[dict]) -> list[dict]:
    issues = []
    for s in subs:
        cadence = s["cadence"]
        min_charges = LONG_RUNNING_MIN_CHARGES.get(cadence)
        if min_charges is None:
            continue
        if s["charge_count"] < min_charges:
            continue

        months = _approx_months_running(cadence, s["charge_count"])
        issues.append({
            "type": "long_running",
            "merchant": s["merchant"],
            "cadence": cadence,
            "charge_count": s["charge_count"],
            "months_running_min": months,
            "monthly_cost": s["monthly_cost"],
            "potential_savings_monthly": s["monthly_cost"],
            "rationale": (
                f"{s['merchant']} has been charging you for at least "
                f"{months} months ({s['charge_count']} charges observed); "
                f"if you no longer use it, canceling saves "
                f"${s['monthly_cost']}/mo."
            ),
        })
    return issues


def _approx_months_running(cadence: str, charge_count: int) -> int:
    # Conservative floor so "at least N months" is always honest.
    if cadence == "weekly":
        return int(charge_count / Decimal("4.33"))
    if cadence == "monthly":
        return charge_count
    if cadence == "yearly":
        return charge_count * 12
    return 0


def _monthly_from_amount(amount: Decimal, cadence: str) -> Decimal:
    if cadence == "weekly":
        return amount * Decimal("4.33")
    if cadence == "monthly":
        return amount
    if cadence == "yearly":
        return amount / Decimal("12")
    return Decimal("0")
