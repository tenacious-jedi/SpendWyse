import logging
from datetime import datetime, timezone
from typing import Optional

from app.extensions import db
from app.models.outbox_event import OutboxEvent
from .publisher import publish_envelope
from .schema import build_envelope

logger = logging.getLogger(__name__)

# After this many failed attempts a row keeps being retried but is logged as
# stuck, so a poison message is visible without blocking the rest of the batch.
STUCK_ATTEMPT_THRESHOLD = 10


def enqueue(event_type: str, payload: dict, key: Optional[str] = None) -> OutboxEvent:
    """Stage an event for delivery inside the caller's transaction.

    This adds the row to the current session but does NOT commit; the caller's
    own commit persists the event atomically with its business data. Replaces
    the old best-effort publish-after-commit, which could drop events.
    """
    envelope = build_envelope(event_type, payload)
    row = OutboxEvent(
        event_id=envelope["event_id"],
        event_type=event_type,
        topic=_topic_for(event_type),
        aggregate_key=key,
        envelope=envelope,
    )
    db.session.add(row)
    return row


def dispatch_pending(batch_size: int = 100) -> int:
    """Deliver unpublished outbox rows to Kafka. Returns the number published.

    Intended to be called in a loop by the relay process. Each row is only
    marked published after the broker acks it, so a delivery failure leaves the
    row pending for the next pass (at-least-once).
    """
    rows = _claim_batch(batch_size)
    if not rows:
        return 0

    published = 0
    for row in rows:
        try:
            publish_envelope(row.topic, row.envelope, key=row.aggregate_key)
        except Exception as exc:
            # Leave published_at NULL so the row is retried next pass.
            row.attempts += 1
            row.last_error = str(exc)[:2000]
            if row.attempts >= STUCK_ATTEMPT_THRESHOLD:
                logger.error(
                    "outbox row %s stuck after %d attempts: %s",
                    row.id, row.attempts, exc,
                )
            else:
                logger.warning(
                    "outbox delivery failed row=%s attempt=%d: %s",
                    row.id, row.attempts, exc,
                )
            continue

        row.published_at = datetime.now(timezone.utc)
        row.attempts += 1
        published += 1

    db.session.commit()
    return published


def _claim_batch(batch_size: int):
    """Fetch the oldest unpublished rows, locking them so multiple relay
    workers can run concurrently without double-publishing the same row.

    SKIP LOCKED is a Postgres feature; on other backends the with_for_update
    still serializes access, just without the skip optimization.
    """
    query = (
        OutboxEvent.query
        .filter(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.id.asc())
        .limit(batch_size)
    )
    try:
        query = query.with_for_update(skip_locked=True)
    except Exception:
        # Backend without SKIP LOCKED support; fall back to a plain read.
        pass
    return query.all()


def _topic_for(event_type: str) -> str:
    # Mirror the publisher's 1:1 mapping so enqueue and direct publish agree.
    return event_type
