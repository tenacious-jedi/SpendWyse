# Running SpendWyse with Docker

`compose.yaml` defines the full stack:

| Service        | What it runs                          | Notes                                       |
|----------------|---------------------------------------|---------------------------------------------|
| `db`           | PostgreSQL 16                         | Data persisted in the `postgres_data` volume |
| `kafka`        | Apache Kafka 3.7 (KRaft, single node) | Internal `kafka:9092`, host `localhost:29092` |
| `migrate`      | `flask db upgrade` (one-shot)         | Runs to completion before the app starts    |
| `server`       | Gunicorn (`run:app`) on port 8000     | The Flask API                               |
| `worker`       | `worker.py` — Kafka alert consumer    | Depends on kafka                            |
| `outbox-relay` | `outbox_relay.py` — outbox dispatcher | Publishes pending events to Kafka           |

## First-time setup

Create your environment file (secrets are read from `.env`, not baked into the image):

```bash
cp .env.example .env
```

Then fill in the real secrets in `.env` — at minimum `SECRET_KEY` and
`JWT_SECRET_KEY`, plus `PLAID_*` / `STRIPE_*` if you exercise those flows.

Note: the `DATABASE_URL` and `KAFKA_BOOTSTRAP_SERVERS` values in `.env` (which
point at `localhost`, for running the app directly on your machine) are
overridden by `compose.yaml` to the in-cluster hostnames `db` and `kafka`, so
you do not need to change them for Docker.

## Build and run

```bash
docker compose up --build
```

The API is then available at http://localhost:8000 (liveness probe:
`GET /api/health/`, deep readiness: `GET /api/health/deep`).

Startup order is handled automatically: the app services wait for `db` and
`kafka` to be healthy and for the `migrate` job to finish successfully.

## Common commands

```bash
# Run in the background
docker compose up --build -d

# Tail logs for one service
docker compose logs -f server

# Re-run migrations after adding a new revision
docker compose run --rm migrate

# Open a shell in the app image
docker compose run --rm server bash

# Stop everything (keep data)
docker compose down

# Stop and wipe the postgres + kafka volumes
docker compose down -v
```

## Deploying the image

```bash
docker build -t spendwyse-app .
# For a different target arch (e.g. Apple Silicon -> amd64 cloud):
docker build --platform=linux/amd64 -t spendwyse-app .
```

Provide the environment variables from `.env` through your platform's secret
manager, run `flask db upgrade` once against the target database, and start the
web/worker/relay processes with the commands shown in the table above.
