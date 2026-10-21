from datetime import datetime, timezone
from app.extensions import db


class ProcessedEvent(db.Model):
    """Idempotency ledger for event consumers.

    The outbox delivers at-least-once, so a consumer may see the same event_id
    more than once. A row here records that a given consumer group has already
    handled an event, letting the worker skip redundant reprocessing. Keyed by
    consumer group so independent consumers each get to process an event once.

    Also used for inbound provider webhooks (e.g. Stripe), where the group names
    the provider and event_id is the provider's event id — hence event_id is
    wide enough for external ids, not just our 36-char uuids.
    """

    __tablename__ = "processed_events"
    __table_args__ = (
        db.UniqueConstraint(
            "consumer_group", "event_id", name="uq_processed_events_group_event"
        ),
    )

    id = db.Column(db.BigInteger, primary_key=True)
    consumer_group = db.Column(db.String(255), nullable=False)
    event_id = db.Column(db.String(255), nullable=False)

    processed_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
