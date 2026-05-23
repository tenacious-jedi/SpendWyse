from typing import Optional

from app.models.tag_rule import TagRule, RuleMatchType
from app.models.transaction import Transaction


def apply_rules(user_id: int, transaction: Transaction) -> Optional[int]:
    # Lower `priority` value wins; ties broken by rule id.
    rules = (
        TagRule.query
        .filter_by(user_id=user_id, is_active=True)
        .order_by(TagRule.priority.asc(), TagRule.id.asc())
        .all()
    )

    merchant = (transaction.merchant or "").lower()
    notes = (transaction.notes or "").lower()
    category = (transaction.category or "").lower()

    for rule in rules:
        if _matches(rule, merchant, notes, category):
            return rule.tag_id
    return None


def _matches(rule: TagRule, merchant: str, notes: str, category: str) -> bool:
    needle = (rule.match_value or "").lower().strip()
    if not needle:
        return False

    if rule.match_type == RuleMatchType.merchant_exact:
        return merchant == needle
    if rule.match_type == RuleMatchType.merchant_contains:
        return needle in merchant
    if rule.match_type == RuleMatchType.keyword:
        return needle in merchant or needle in notes or needle in category
    if rule.match_type == RuleMatchType.plaid_pfc:
        # Placeholder: match against `category` until a dedicated plaid_pfc field
        # is added to Transaction during the Plaid integration.
        return needle == category
    return False
