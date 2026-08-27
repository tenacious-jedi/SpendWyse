from datetime import datetime, timezone
from decimal import Decimal

from plaid.model.transactions_sync_request import TransactionsSyncRequest

from app.events.outbox import enqueue
from app.events.schema import TRANSACTION_TAGGED
from app.extensions import db
from app.models.plaid_item import PlaidItem
from app.models.transaction import Transaction, TransactionSource, TransactionType
from app.tags.rule_engine import apply_rules
from .plaid_client import get_plaid_client


def sync_item(plaid_item: PlaidItem) -> dict:
    """Pull added/modified/removed transactions for one PlaidItem and upsert
    them, committing the cursor per page so a crash mid-sync resumes cleanly.

    Returns a small summary of what changed.
    """
    client = get_plaid_client()
    cursor = plaid_item.cursor or ""

    added = modified = removed = tagged = 0
    has_more = True

    while has_more:
        req = TransactionsSyncRequest(
            access_token=plaid_item.access_token,
            cursor=cursor,
        )
        resp = client.transactions_sync(req)

        tagged_this_page: list[Transaction] = []

        for plaid_txn in resp.added:
            txn = _to_transaction(plaid_txn, plaid_item.user_id)
            tag_id = apply_rules(plaid_item.user_id, txn)
            if tag_id:
                txn.tag_id = tag_id
                tagged += 1
                tagged_this_page.append(txn)
            db.session.add(txn)
            added += 1

        for plaid_txn in resp.modified:
            existing = Transaction.query.filter_by(
                plaid_transaction_id=plaid_txn.transaction_id
            ).first()
            if existing:
                _apply_plaid_fields(existing, plaid_txn)
                modified += 1

        for removed_txn in resp.removed:
            existing = Transaction.query.filter_by(
                plaid_transaction_id=removed_txn.transaction_id
            ).first()
            if existing:
                existing.is_deleted = True
                removed += 1

        cursor = resp.next_cursor
        has_more = resp.has_more

        # Persist cursor only after the page's rows are in the session.
        plaid_item.cursor = cursor
        plaid_item.last_synced_at = datetime.now(timezone.utc)

        # Flush to assign ids to the new rows, then stage their events in the
        # same transaction so a committed row always carries its event.
        db.session.flush()
        for txn in tagged_this_page:
            enqueue(
                TRANSACTION_TAGGED,
                {
                    "user_id": txn.user_id,
                    "transaction_id": txn.id,
                    "tag_id": txn.tag_id,
                },
                key=str(txn.user_id),
            )

        db.session.commit()

    return {
        "plaid_item_id": plaid_item.id,
        "added": added,
        "modified": modified,
        "removed": removed,
        "auto_tagged": tagged,
    }


def _to_transaction(plaid_txn, user_id: int) -> Transaction:
    txn = Transaction(
        user_id=user_id,
        source=TransactionSource.plaid,
        plaid_transaction_id=plaid_txn.transaction_id,
    )
    _apply_plaid_fields(txn, plaid_txn)
    return txn


def _apply_plaid_fields(txn: Transaction, plaid_txn) -> None:
    raw_amount = Decimal(str(plaid_txn.amount))
    # Plaid convention: positive = outflow (debit), negative = inflow (credit).
    txn.amount = abs(raw_amount)
    txn.transaction_type = (
        TransactionType.debit if raw_amount >= 0 else TransactionType.credit
    )
    txn.currency = (plaid_txn.iso_currency_code or "USD").upper()[:3]
    txn.transaction_date = plaid_txn.date
    txn.merchant = plaid_txn.merchant_name or plaid_txn.name
    txn.category = _extract_category(plaid_txn)


def _extract_category(plaid_txn) -> str | None:
    pfc = getattr(plaid_txn, "personal_finance_category", None)
    if pfc and getattr(pfc, "primary", None):
        return pfc.primary
    legacy = getattr(plaid_txn, "category", None) or []
    return legacy[0] if legacy else None
