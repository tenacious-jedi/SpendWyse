import logging
from datetime import datetime, timezone
from decimal import Decimal

from plaid.model.transactions_sync_request import TransactionsSyncRequest
from sqlalchemy import text

from app.events.outbox import enqueue
from app.events.schema import TRANSACTION_TAGGED
from app.extensions import db
from app.models.plaid_item import PlaidItem
from app.models.transaction import Transaction, TransactionSource, TransactionType
from app.tags.rule_engine import apply_rules
from .plaid_client import get_plaid_client

logger = logging.getLogger(__name__)

# Namespace for plaid-sync advisory locks, so the item-id keys can't collide
# with any other advisory-lock use. Both args to pg_*_advisory_lock are int4.
_SYNC_LOCK_NAMESPACE = 4271


def _acquire_sync_lock(item_id: int) -> bool:
    """Take a non-blocking, session-level advisory lock for this item's sync.

    Session-level (not xact-level) so it survives the per-page commits below.
    Returns True if acquired, False if another sync already holds it. On a
    backend without advisory locks (e.g. sqlite in tests) locking is a no-op.
    """
    if db.session.get_bind().dialect.name != "postgresql":
        return True
    got = db.session.execute(
        text("SELECT pg_try_advisory_lock(:ns, :key)"),
        {"ns": _SYNC_LOCK_NAMESPACE, "key": item_id},
    ).scalar()
    return bool(got)


def _release_sync_lock(item_id: int) -> None:
    if db.session.get_bind().dialect.name != "postgresql":
        return
    try:
        # A failed sync may have left the session mid-transaction; clear it so
        # the unlock runs cleanly. Session-level locks outlive the rollback.
        db.session.rollback()
        db.session.execute(
            text("SELECT pg_advisory_unlock(:ns, :key)"),
            {"ns": _SYNC_LOCK_NAMESPACE, "key": item_id},
        )
        db.session.commit()
    except Exception:
        # Never mask the original outcome; the lock also frees when the
        # connection is eventually recycled.
        logger.exception("failed to release plaid sync lock for item %s", item_id)


def sync_item(plaid_item: PlaidItem) -> dict:
    """Pull added/modified/removed transactions for one PlaidItem and upsert
    them, committing the cursor per page so a crash mid-sync resumes cleanly.

    A session-level advisory lock serializes syncs for one item: a concurrent
    sync (e.g. a manual /sync racing a webhook-triggered one) that can't get
    the lock skips rather than racing to insert the same plaid_transaction_id
    and hitting the UNIQUE constraint. Returns a small summary of what changed.
    """
    if not _acquire_sync_lock(plaid_item.id):
        logger.info(
            "plaid sync already in progress for item %s; skipping", plaid_item.id
        )
        return {"plaid_item_id": plaid_item.id, "skipped": "sync_in_progress"}

    try:
        return _run_sync(plaid_item)
    finally:
        _release_sync_lock(plaid_item.id)


def _run_sync(plaid_item: PlaidItem) -> dict:
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
