import json
import logging
from functools import lru_cache
from typing import Optional

from flask import current_app
from kafka import KafkaProducer
from kafka.errors import KafkaError

from .schema import build_envelope

logger = logging.getLogger(__name__)


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


def publish(event_type: str, payload: dict, key: Optional[str] = None) -> bool:
    """Publish an event. Returns True on success, False on failure.

    Failures are logged but not raised; callers treat publish as best-effort.
    For exactly-once semantics use the outbox pattern instead.
    """
    if not current_app.config.get("KAFKA_BOOTSTRAP_SERVERS"):
        logger.info("kafka not configured; skip publish %s", event_type)
        return False

    topic = _topic_for(event_type)
    envelope = build_envelope(event_type, payload)

    try:
        _producer().send(topic, value=envelope, key=key)
        return True
    except KafkaError:
        logger.exception("kafka publish failed type=%s", event_type)
        return False
    except Exception:
        logger.exception("unexpected publish error type=%s", event_type)
        return False


def _topic_for(event_type: str) -> str:
    # 1:1 today; centralized so routing rules can change without touching callers.
    return event_type
