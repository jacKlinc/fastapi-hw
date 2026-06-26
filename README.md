# FastAPI Routes API

A REST API for managing geographic routes. Users register, authenticate via JWT, and create or retrieve routes stored with lat/lon coordinates and a geohash.

## System Design Features


![alt text](docs/diagrams/Auth-Flow.drawio.png)

### JWT
- This uses JSON Web Tokens (JWT) to authenticate user requests
- The tokens are valid for 30 days which obviously too long for production but works well for a project piece

### Rate Limiting
- `slowapi`'s built-in rate limiting is a great fit for FastAPI
- 5 requests a minute was chosen for ease of testing

### Geohashing
- Geohash-based proximity search over 100k generated routes centred on Canmore. Benchmarked against brute force haversine — ~4x faster at 1k points.
- Query performance degrades beyond 20km radius due to unindexed prefix scan — a trie or sorted index would restore O(1) lookup at scale


## File Structure
```
app/
  api/
    routes/
      auth.py       # register + token endpoints
      routes.py     # CRUD route endpoints
  core/
    config.py       # pydantic-settings config from .env
    logging.py      # logging dictConfig setup
    security.py     # JWT encrypt/decrypt, password hashing
  db/
    models.py
    session.py
  main.py           # app factory, lifespan, middleware
```

## Running

```bash
# Start Postgres
docker compose up -d

# Run API (hot reload)
uv run uvicorn app.main:app --reload
```

Connect to the DB directly:
```bash
docker exec -it fastapi-hw-db-1 psql -U myuser -d mydatabase
```

## Logging

Logging is configured in `app/core/logging.py` using Python's `logging.dictConfig` and initialised via FastAPI's `lifespan` hook.

**FastAPI-specific patterns used:**

- **`lifespan` for setup/teardown** — logging is configured in the `lifespan` async context manager rather than at module import time, so it runs after uvicorn's own loggers are initialised. This avoids a race where `dictConfig` resets uvicorn's handlers.

- **`disable_existing_loggers: False`** — the dictConfig keeps uvicorn's built-in `uvicorn` and `uvicorn.access` loggers intact. Overriding these breaks uvicorn's startup banner and access log format.

- **`logging.getLogger(__name__)` per module** — each router file gets its own logger (`app.api.routes.routes`, `app.api.routes.auth`) so log output is traceable to its source without extra fields.


## Docker

Run the full stack (API + Postgres) with Docker Compose:

```bash
docker compose up -d --build
```

This builds the API image from the [Dockerfile](Dockerfile), starts Postgres, and waits for its healthcheck before starting the API. The app is then available at `http://localhost:8000`.

Requires a `.env` file (see [.template.env](.template.env)) with at least:

```
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_DB=
POSTGRES_PORT=
POSTGRES_HOST=
JWT_SECRET=
```

Useful commands:

```bash
docker compose logs -f api      # tail API logs
docker compose down             # stop containers
docker compose down -v          # stop and wipe the Postgres volume
```

## Kubernetes (minikube)

[resources.yml](resources.yml) holds the Kubernetes manifests, generated from `docker-compose.yml` via `kompose convert -f docker-compose.yml -o resources.yml` — re-run that if the compose file changes.

```bash
minikube start

# Build the image into minikube's own Docker daemon so the cluster can see it
eval $(minikube docker-env)
docker build -t fastapi-hw-api:latest .

kubectl apply -f resources.yml

kubectl get pods
kubectl get svc

minikube service api --url
```

To run the API image standalone against an existing Postgres instance:

```bash
docker build -t fast-api .
docker run --env-file .env -p 8000:8000 fast-api
```


## OpenTelemetry

Traces, metrics, and logs are exported over OTLP to a local [OpenTelemetry Collector](otel/collector.yml), which prints them to its own console.

The `api` service in [docker-compose.yml](docker-compose.yml) runs the app wrapped in `opentelemetry-instrument` (see [Dockerfile](Dockerfile)) and points `OTEL_EXPORTER_OTLP_ENDPOINT` at the `otel-collector` service. Start everything with `docker compose up -d --build`, then tail the collector to see telemetry arrive:

```bash
docker compose logs -f otel-collector
```

Notes:
- The collector's `debug` exporter (`otel/collector.yml`) just dumps detailed output to stdout — fine for confirming traces/logs are flowing, but traces and logs aren't persisted anywhere queryable.
- App logs only reach the collector because `app/core/logging.py`'s `"app"` logger has `propagate: True`, letting records bubble up to the root logger where the OTel logging auto-instrumentation attaches its OTLP export handler.

### Metrics dashboard (Prometheus + Grafana)

The collector also exports metrics via a `prometheus` exporter (`otel/collector.yml`, port `8889`), which Prometheus scrapes every 5s (`otel/prometheus.yml`). Grafana comes preconfigured with Prometheus as its default datasource (`otel/grafana-datasources.yml`).

- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (login `admin` / `admin`)

Useful metric names to graph in Grafana: `http_server_duration_milliseconds_count`, `http_server_active_requests`, `http_server_response_size_bytes_sum`.