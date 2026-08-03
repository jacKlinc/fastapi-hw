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
- `RATE_LIMIT_ENABLED=false` switches the limiter off wholesale, which benchmarking needs — 5/minute otherwise turns a 1000-request run into 995 429s

### Geohashing
- Geohash-based proximity search over 100k generated routes centred on Canmore. Benchmarked against brute force haversine — ~4x faster at 1k points.
- Query performance degrades beyond 20km radius due to unindexed prefix scan — a trie or sorted index would restore O(1) lookup at scale

### Bounding Box Search
- `GET /routes/bbox?min_lat=&min_lon=&max_lat=&max_lon=` returns routes inside a lat/lon box — the shape a map frontend actually asks for, since a viewport is a rectangle, not a radius.
- Public read (no token, no rate limit) so a React map can pan freely. Results are capped at `BBOX_LIMIT` (500) rows, but the response still carries the true `total_count` plus a `capped` flag so the client can tell "500 routes" from "500 shown of 12,000".
- Registered *before* `GET /routes/{route_id}` — FastAPI matches routes in declaration order, so `bbox` would otherwise be parsed as a `route_id` and 422.
- Backed by a composite `(lat, lon)` index (`ix_routes_lat_lon` in [app/db/models.py](app/db/models.py)). `create_all()` won't add an index to an already-existing table, so run [scripts/add_bbox_index.py](scripts/add_bbox_index.py) against a DB seeded before the index existed.

### Redis Caching

`GET /routes/radius/{radius}` is cache-aside over Redis ([app/core/cache.py](app/core/cache.py)): check the key, fall through to Postgres on a miss, write the result back with a 300s TTL.

**The first attempt cached the wrong endpoint.** `GET /routes/{route_id}` looks like the obvious candidate — it's the most-hit read — but it's a primary key lookup against a warm Postgres, and caching it moved the median from 4.0ms to 3.0ms at an 80% hit rate. Saving 1.2ms isn't worth a dependency. The radius search is the opposite: an unindexed geohash prefix scan returning up to a page of rows, which is where the time actually goes.

**The key falls out of how the query works.** The endpoint doesn't search by coordinates — it converts (radius, lat, lon) into a geohash prefix and runs `geohash LIKE 'c3j%'`. So the result depends on exactly two things, the prefix and the pagination window, and that pair *is* the cache key:

```
radius:c3j:offset=None:limit=100
```

Two useful properties come free. Nearby origins collapse onto the same key (a map panning by 200m re-hits the same entry rather than minting a new one), and the key space is bounded by the number of occupied cells rather than by coordinate precision — no rounding hacks needed.

**Invalidation is prefix-precise.** A new route only invalidates searches whose prefix it falls under, and since `calculate_geohash` only ever returns prefixes of length 0–10, a write has just 11 candidate prefixes to clear — a bounded loop, no `SCAN`. Because keys also carry the pagination signature, each prefix keeps a set of the keys scanning it (`radiuskeys:c3j`), written in the same pipeline as the value and expiring with it. `create_route` reads those 11 sets and deletes what it finds. Verified both ways: creating a route in Sydney leaves a cached Canmore search intact; creating one inside the cell drops it, and the next search returns the new route.

- 404s are deliberately **not** cached — otherwise a route created into an empty cell stays invisible for the whole TTL.
- Values are plain JSON strings, not RedisJSON, so a stock `redis:7-alpine` is enough — no modules.
- `pagination_signature` mirrors the endpoint's `if/elif` precedence. That duplication is the one genuine hazard in the keying — disagree about which window a request means and you cache one page's rows under another page's key — so a test sends every pagination style at once and asserts the branch the endpoint took is the one its key claims.
- The endpoint had to become `async def` + `AsyncSession` to use the cache helpers; it was the last sync route handler doing real query work.
- `CACHE_ENABLED=false` makes the `get_redis` dependency yield `None` and every call site no-ops. That's the switch the benchmark below uses for its baseline.

**A dead cache must not take the API down with it.** The first version was "correct" — it caught `RedisError` and fell through to Postgres — but with the Redis container stopped, a single read took **111 seconds**. `socket_connect_timeout` doesn't cover DNS resolution, and `getaddrinfo` for a vanished container hostname blocks for ~45s on its own. Two things fix it:

- every Redis call runs under `asyncio.wait_for(..., CACHE_TIMEOUT_SECONDS)` (0.25s), which bounds the whole await including name resolution
- a circuit breaker skips Redis entirely for 10s after 3 consecutive failures

`RadiusCache` owns both the client and its `CircuitBreaker`, so the failure state is per-instance rather than module-global — tests build an isolated cache instead of resetting globals between cases. Same test after those changes: 0.51s, 0.26s, then 6ms, 6ms, 6ms — and it re-warms automatically once Redis is back. Writes keep working throughout; invalidation that can't reach Redis is skipped, not retried.

### Pagination
`GET /routes/radius/{radius}` accepts four mutually exclusive pagination styles (see `pagination_params` in [app/schemas/routes.py](app/schemas/routes.py)), tried in this order:

| Style | Params | Notes |
| --- | --- | --- |
| Page-based | `page`, `pageSize` | Computes an offset internally; the familiar "page 3" UI |
| Keyset | `since_id` | `WHERE id > since_id` — no offset scan, stable under inserts |
| Cursor | `cursor` | Same as keyset but the id is base64-encoded and opaque; the response returns the next `cursor` |
| Offset | `offset`, `limit` | Default fallback (`limit=100`) |

`GET /routes/route-pag/{route_id}` is a separate endpoint using `fastapi-pagination`'s native `Page[RouteOut]` / `paginate()` for comparison against the hand-rolled versions above.

### Benchmarks

Results live in [scripts/benchmark/](scripts/benchmark/) as CSVs with a `label` column, appended to on each run.

Pagination ([radius.py](scripts/benchmark/radius.py), 1000 requests each):

| Label | mean ms | p95 ms |
| --- | --- | --- |
| vanilla (no pagination) | 17.0 | 24.1 |
| offset | 9.6 | 15.8 |
| page | 5.8 | 8.5 |
| keyset | 7.7 | 12.7 |
| cursor | 10.8 | 14.7 |

Bounding box ([bbox.py](scripts/benchmark/bbox/bbox.py), 1000 requests mixing 1km and 70km boxes):

| Label | mean ms | p50 ms | p95 ms |
| --- | --- | --- | --- |
| no_index | 20.9 | 19.8 | 27.1 |
| with_index | 13.0 | 6.5 | 22.3 |

The `(lat, lon)` index roughly halves the median. p95 barely moves because the large "zoomed out" boxes are limit-bound, not scan-bound — the index can't help when you're returning 500 rows either way.

Redis cache ([cache.py](scripts/benchmark/cache/cache.py), 1000 requests, 95% reads over a 200-search pool at 10/25/50km):

| Label | mean ms | p50 ms | p95 ms | p99 ms |
| --- | --- | --- | --- | --- |
| no_cache | 12.5 | 7.7 | 28.4 | 38.0 |
| with_cache | 5.8 | 4.6 | 10.9 | 27.3 |

Mean more than halves and p95 drops 62%. The tail is where it shows most: p95 is dominated by the 50km searches, which resolve to a 3-character prefix and scan essentially the whole seeded dataset — exactly the queries a cache should be absorbing. p99 improves least, because that's the 5% writes, which the cache makes marginally *slower* (they now do invalidation work on top of the insert).

For comparison, the same benchmark against `GET /routes/{id}` gave 4.9 → 4.0ms mean. Picking the right endpoint mattered more than anything in the cache implementation.

Two things the benchmark does deliberately:

- **Bounded search pool.** Random origins would miss every time and report the cache as worthless; a real map client re-issues overlapping searches. The pool is validated at startup so empty cells (which 404) don't land in the error count.
- **Writes stay in the mix** at 5%, so the numbers include invalidation churn rather than measuring a frozen dataset. Note that `keyspace_misses` from `redis-cli INFO` overstates the read miss rate here — each write probes 11 prefix index sets, most of which don't exist.

Both runs need `RATE_LIMIT_ENABLED=false`, otherwise 5/minute means you're benchmarking 429s:

```bash
CACHE_ENABLED=false RATE_LIMIT_ENABLED=false docker compose up -d api
uv run python scripts/benchmark/cache/cache.py --label no_cache

CACHE_ENABLED=true RATE_LIMIT_ENABLED=false docker compose up -d api
docker compose exec redis redis-cli FLUSHALL
uv run python scripts/benchmark/cache/cache.py --label with_cache
```

Caveat learned the hard way: rebuild the Docker image before benchmarking, or you'll benchmark the old code and record wildly inflated latency.

## File Structure
```
app/
  api/
    routes/
      auth.py       # register + token endpoints
      routes.py     # CRUD, bbox, radius + pagination endpoints
  schemas/
    routes.py       # request/response models + pagination params
  core/
    cache.py        # radius cache-aside + geohash-prefix invalidation + breaker
    config.py       # pydantic-settings config from .env
    logging.py      # logging dictConfig setup
    security.py     # JWT encrypt/decrypt, password hashing
  db/
    models.py
    session.py
  main.py           # app factory, lifespan, middleware
scripts/
  seed.py           # generate 100k routes around Canmore
  add_bbox_index.py # one-off (lat, lon) index creation
  benchmark/        # latency benchmarks + results CSVs
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

Redis settings default to `localhost:6379` with caching on (see `Settings` in [app/core/config.py](app/core/config.py)); compose points the API at the `redis` service. `CACHE_ENABLED` and `RATE_LIMIT_ENABLED` are shell-overridable in [docker-compose.yml](docker-compose.yml) so the benchmark A/B needs no file edits.

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
- The collector's `debug` exporter (`otel/collector.yml`) just dumps detailed output to stdout — fine for confirming traces/logs are flowing, but logs aren't persisted anywhere queryable (traces are, via Jaeger below).
- App logs only reach the collector because `app/core/logging.py`'s `"app"` logger has `propagate: True`, letting records bubble up to the root logger where the OTel logging auto-instrumentation attaches its OTLP export handler.

### Trace viewer (Jaeger)

The collector also exports traces via a second OTLP exporter (`otlp/jaeger` in `otel/collector.yml`) aimed at Jaeger's own native OTLP receiver.

- Jaeger UI: http://localhost:16686 — pick the `fastapi-hw` service to browse spans.

Jaeger's all-in-one image stores traces in memory only, so they're lost on container restart — fine for local dev, not a persistent trace store.

### Metrics dashboard (Prometheus + Grafana)

The collector also exports metrics via a `prometheus` exporter (`otel/collector.yml`, port `8889`), which Prometheus scrapes every 5s (`otel/prometheus.yml`). Grafana comes preconfigured with Prometheus as its default datasource (`otel/grafana-datasources.yml`).

- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (login `admin` / `admin`)

Useful metric names to graph in Grafana: `http_server_duration_milliseconds_count`, `http_server_active_requests`, `http_server_response_size_bytes_sum`.