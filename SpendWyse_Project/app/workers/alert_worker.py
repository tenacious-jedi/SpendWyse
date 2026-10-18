import json
import logging
import signal

from flask import Flask
from kafka import KafkaConsumer

from app.events.idempotency import already_processed, mark_processed
from app.events.schema import TRANSACTION_TAGGED
from app.tags.alert_service import check_caps_and_notify
from app.utils.correlation import reset_correlation_id, set_correlation_id

logger = logging.getLogger(__name__)

_shutdown = False


def _stop(*_):
    global _shutdown
    logger.info("shutdown signal received; draining in-flight batch")
    _shutdown = True


def consume_forever(app: Flask) -> None:
    bootstrap = app.config["KAFKA_BOOTSTRAP_SERVERS"]
    group_id = app.config["KAFKA_CONSUMER_GROUP"]

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    consumer = KafkaConsumer(
        TRANSACTION_TAGGED,
        bootstrap_servers=[s.strip() for s in bootstrap.split(",") if s.strip()],
        group_id=group_id,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    logger.info(
        "alert worker started group=%s topic=%s", group_id, TRANSACTION_TAGGED
    )

    try:
        while not _shutdown:
            batch = consumer.poll(timeout_ms=1000, max_records=10)
            if not batch:
                continue

            for _tp, messages in batch.items():
                for msg in messages:
                    value = msg.value or {}
                    try:
                        _handle(app, value)
                    except Exception:
                        logger.exception(
                            "consumer handler failed event_id=%s correlation_id=%s",
                            value.get("event_id"),
                            value.get("correlation_id"),
                        )
            # Commit offsets per poll-batch; failed messages are not retried.
            # The Alert UNIQUE constraint makes re-processing safe if we add
            # DLQ replay later.
            consumer.commit()
    finally:
        consumer.close()
        logger.info("alert worker stopped")


def _handle(app: Flask, envelope: dict) -> None:
    if not envelope or envelope.get("event_type") != TRANSACTION_TAGGED:
        return

    payload = envelope.get("payload") or {}
    user_id = payload.get("user_id")
    tag_id = payload.get("tag_id")
    if not user_id:
        return

    event_id = envelope.get("event_id")
    correlation_id = envelope.get("correlation_id")
    group_id = app.config["KAFKA_CONSUMER_GROUP"]

    # Carry the producing request's correlation id for the duration of handling
    # so this consumer's log lines (and any current_app.logger lines downstream)
    # tie back to the originating request. Reset after to avoid leaking it to
    # the next message handled on this thread.
    token = set_correlation_id(correlation_id) if correlation_id else None
    try:
        with app.app_context():
            # At-least-once delivery can redeliver an event; skip if we already
            # handled it. Only events carrying an event_id can be deduped.
            if event_id and already_processed(group_id, event_id):
                logger.info(
                    "skipping already-processed event_id=%s correlation_id=%s",
                    event_id, correlation_id,
                )
                return

            check_caps_and_notify(int(user_id), only_tag_id=tag_id)

            # Record only after successful processing so a crash mid-handling
            # leaves the event unmarked and safely reprocessable.
            if event_id:
                mark_processed(group_id, event_id)
    finally:
        if token is not None:
            reset_correlation_id(token)
