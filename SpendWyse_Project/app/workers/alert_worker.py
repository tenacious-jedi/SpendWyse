import json
import logging
import signal

from flask import Flask
from kafka import KafkaConsumer

from app.events.schema import TRANSACTION_TAGGED
from app.tags.alert_service import check_caps_and_notify

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
                    try:
                        _handle(app, msg.value)
                    except Exception:
                        logger.exception(
                            "consumer handler failed event_id=%s",
                            (msg.value or {}).get("event_id"),
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

    with app.app_context():
        check_caps_and_notify(int(user_id), only_tag_id=tag_id)
