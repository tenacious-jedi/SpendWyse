from datetime import datetime, timezone
from app.extensions import db


class OutboxEvent(db.Model):
    """Transactional outbox row.

    Producers insert a row here in the SAME database transaction that writes
    the business data, so the event and the state change commit atomically.
    A separate relay process (see app/events/outbox.dispatch_pending) reads
    unpublished rows and delivers them to Kafka, guaranteeing at-least-once
    delivery even if the broker is unreachable at write time.
    """

    __tablename__ = "outbox_events"

    id = db.Column(db.BigInteger, primary_key=True)

    # The envelope's event_id, surfaced as a column so consumers can dedup on it
    # (at-least-once delivery means the same row may be published more than once).
    event_id = db.Column(db.String(36), unique=True, nullable=False)

    event_type = db.Column(db.String(255), nullable=False)
    topic = db.Column(db.String(255), nullable=False)

    # Kafka partition key; nullable because not every event needs ordering.
    aggregate_key = db.Column(db.String(255), nullable=True)

    # The full serialized envelope, delivered verbatim by the relay.
    envelope = db.Column(db.JSON, nullable=False)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # NULL until the relay confirms the broker acked the message.
    # Indexed because the relay's hot query is "pending rows ordered by id".
    published_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    # Delivery attempt counter and last failure, for observability and backoff.
    attempts = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.Text, nullable=True)
