import logging
import os
import signal
import time

from app import create_app
from app.events.outbox import dispatch_pending

logger = logging.getLogger("outbox_relay")

# Idle poll interval; when a batch fully drains we loop immediately instead.
POLL_INTERVAL_SECONDS = float(os.getenv("OUTBOX_RELAY_INTERVAL_SECONDS", "2"))
BATCH_SIZE = int(os.getenv("OUTBOX_RELAY_BATCH_SIZE", "100"))

_shutdown = False


def _stop(*_):
    global _shutdown
    logger.info("shutdown signal received; finishing current batch")
    _shutdown = True


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    app = create_app()
    if not app.config.get("KAFKA_BOOTSTRAP_SERVERS"):
        logger.error("KAFKA_BOOTSTRAP_SERVERS not configured; relay cannot run")
        return

    logger.info("outbox relay started batch_size=%d", BATCH_SIZE)
    while not _shutdown:
        with app.app_context():
            try:
                published = dispatch_pending(BATCH_SIZE)
            except Exception:
                # A full-batch failure (e.g. DB blip) should not kill the relay.
                logger.exception("outbox dispatch pass failed")
                published = 0

        # A full batch likely means more is waiting, so drain without sleeping.
        if published < BATCH_SIZE:
            time.sleep(POLL_INTERVAL_SECONDS)

    logger.info("outbox relay stopped")


if __name__ == "__main__":
    main()
