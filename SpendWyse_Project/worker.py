import logging

from app import create_app
from app.workers.alert_worker import consume_forever


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    app = create_app()
    consume_forever(app)


if __name__ == "__main__":
    main()
