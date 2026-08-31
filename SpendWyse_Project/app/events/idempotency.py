import logging

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.processed_event import ProcessedEvent

logger = logging.getLogger(__name__)


def already_processed(consumer_group: str, event_id: str) -> bool:
    """Return True if this consumer group has already handled the event."""
    return db.session.query(
        ProcessedEvent.query.filter_by(
            consumer_group=consumer_group, event_id=event_id
        ).exists()
    ).scalar()


def mark_processed(consumer_group: str, event_id: str) -> bool:
    """Record that the event has been handled. Returns False if another worker
    recorded it first (a redelivery race), True on a fresh insert.
    """
    db.session.add(
        ProcessedEvent(consumer_group=consumer_group, event_id=event_id)
    )
    try:
        db.session.commit()
    except IntegrityError:
        # Concurrent worker already claimed this event_id; benign.
        db.session.rollback()
        return False
    return True
