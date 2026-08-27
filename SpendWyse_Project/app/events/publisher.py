import json
import logging
from functools import lru_cache
from typing import Optional

from flask import current_app
from kafka import KafkaProducer

from .schema import build_envelope

logger = logging.getLogger(__name__)

# The relay blocks on delivery confirmation; cap the wait so a wedged broker
# surfaces as a retryable failure instead of hanging the dispatch loop.
PUBLISH_TIMEOUT_SECONDS = 10


@lru_cache(maxsize=1)
def _producer() -> KafkaProducer:
    bootstrap = current_app.config["KAFKA_BOOTSTRAP_SERVERS"]
    return KafkaProducer(
        bootstrap_servers=[s.strip() for s in bootstrap.split(",") if s.strip()],
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None,
        retries=3,
        acks="all",
        linger_ms=10,
    )


def publish_envelope(topic: str, envelope: dict, key: Optional[str] = None) -> None:
    """Deliver a prebuilt envelope, blocking until the broker acks it.

    Raises on any delivery failure so the caller (the outbox relay) can leave
    the row pending and retry. Do not use this on a request path; use enqueue
    to stage the event transactionally instead.
    """
    if not current_app.config.get("KAFKA_BOOTSTRAP_SERVERS"):
        raise RuntimeError("KAFKA_BOOTSTRAP_SERVERS is not configured")

    future = _producer().send(topic, value=envelope, key=key)
    # Block on the ack; raises KafkaError if the broker never confirms.
    future.get(timeout=PUBLISH_TIMEOUT_SECONDS)


def publish(event_type: str, payload: dict, key: Optional[str] = None) -> bool:
    """Best-effort fire-and-forget publish. Returns True on success.

    Kept for callers that can tolerate lost events. Anything that must not be
    dropped should stage the event with app.events.outbox.enqueue instead.
    """
    if not current_app.config.get("KAFKA_BOOTSTRAP_SERVERS"):
        logger.info("kafka not configured; skip publish %s", event_type)
        return False

    envelope = build_envelope(event_type, payload)
    try:
        publish_envelope(_topic_for(event_type), envelope, key=key)
        return True
    except Exception:
        logger.exception("kafka publish failed type=%s", event_type)
        return False


def _topic_for(event_type: str) -> str:
    # 1:1 today; centralized so routing rules can change without touching callers.
    return event_type
