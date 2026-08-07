"""
Benchmark exact haversine search against the geohash prefix search.

This is the control the other benchmarks never had: bbox, cache and pagination all
compare a config toggle, none compares against the naive approach the optimisations
are supposed to beat. GET /routes/haversine/{radius} computes real great-circle
distance for every row with no index to help it.

Three passes:

  latency  -- 1000 HTTP requests over a bounded pool of origins, one label per technique
  sql      -- the same queries timed directly against Postgres, no HTTP overhead
  accuracy -- how much of the truth the geohash approximation actually returns

Use --sql for any claim about the techniques themselves. The HTTP pass cannot
isolate them: with a small row limit both queries early-exit on the primary key
index and you measure selectivity, and with a large one JSON serialization is 96%
of the request. Both artifacts are documented in the README.

The accuracy pass matters more than the latency one. A faster search that silently
drops matches isn't faster, it's wrong, and the recall figure is the size of that
trade.

NOTE: run the geohash label with CACHE_ENABLED=false, or it measures Redis hit
latency instead of the prefix scan. Both labels need RATE_LIMIT_ENABLED=false.

Usage:
    CACHE_ENABLED=false RATE_LIMIT_ENABLED=false docker compose up -d --build api
    uv run python scripts/benchmark/haversine/haversine.py --label haversine
    uv run python scripts/benchmark/haversine/haversine.py --label geohash_no_index
    uv run python scripts/add_geohash_index.py
    uv run python scripts/benchmark/haversine/haversine.py --label geohash_indexed
    uv run python scripts/benchmark/haversine/haversine.py --accuracy

    # query-level, needs DB env vars rather than a running API:
    PYTHONPATH=. POSTGRES_HOST=localhost POSTGRES_PORT=5433 ... \
        uv run python scripts/benchmark/haversine/haversine.py --sql --label haversine_sql

Requires a seeded DB (scripts/seed.py). Appends to
scripts/benchmark/haversine/results.csv using the same columns as the other
benchmarks; "capped" is bbox-specific and always 0 here.
"""

import argparse
import csv
import logging
import math
import os
import random
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"
REQUESTS = 1_000
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "results.csv")

# Matches the data seeded by scripts/seed.py
CANMORE_LAT = 51.0884
CANMORE_LON = -115.3479
SEED_RADIUS_KM = 50
KM_PER_DEG_LAT = 111.0

POOL_SIZE = 200  # distinct search origins in rotation
RADII_KM = [10, 25, 50]  # 5-, 4- and 3-char geohash prefixes respectively

# Both endpoints ORDER BY id, so a small limit lets Postgres walk the primary key
# index and stop at the Nth match — never evaluating the predicate over the table.
# At limit=100 that made the benchmark measure selectivity instead of technique
# (see the Benchmarks section of the README). 10k is past the early exit for every
# radius here, so the query actually runs.
ROW_LIMIT = 10_000

SQL_REQUESTS = 200  # --sql pass: each query does real work, no need for 1000

ACCURACY_ORIGINS = 50
TRUTH_LIMIT = 100_000  # uncapped, for the accuracy pass only


@dataclass
class Result:
    status_code: int
    duration_ms: float
    row_count: int | None = None


def random_point() -> tuple[float, float]:
    """Uniform point in a disc around Canmore, matching the seeded data."""
    r = SEED_RADIUS_KM * math.sqrt(random.random())
    theta = random.uniform(0, 2 * math.pi)
    lat = CANMORE_LAT + (r / KM_PER_DEG_LAT) * math.cos(theta)
    lon = CANMORE_LON + (
        r / (KM_PER_DEG_LAT * math.cos(math.radians(CANMORE_LAT)))
    ) * math.sin(theta)
    return lat, lon


def get_token(client: httpx.Client) -> str:
    username = uuid.uuid4().hex
    password = "benchmark_password"
    client.post(
        "/auth/register",
        params={
            "username": username,
            "email": f"{username}@bench.test",
            "password": password,
        },
    )
    resp = client.post(
        "/auth/token", params={"username": username, "password": password}
    )
    resp.raise_for_status()
    return resp.json()["token"]


def haversine_ids(client, token, lat, lon, radius, limit=None) -> tuple[int, list[int]]:
    params = {"lat": lat, "lon": lon}
    if limit is not None:
        params["limit"] = limit
    resp = client.get(f"/routes/haversine/{radius}", params=params)
    if resp.status_code != 200:
        return resp.status_code, []
    return resp.status_code, [r["id"] for r in resp.json()]


def geohash_ids(client, token, lat, lon, radius, limit=None) -> tuple[int, list[int]]:
    params = {"lat": lat, "lon": lon}
    if limit is not None:
        params["limit"] = limit
    resp = client.get(
        f"/routes/radius/{radius}", params=params, headers={"token": token}
    )
    if resp.status_code != 200:  # radius 404s on an empty cell, haversine returns []
        return resp.status_code, []
    return resp.status_code, [r["id"] for r in resp.json()["routes"]]


def fetcher_for(label: str):
    """Labels are free text so index/no-index runs can be told apart in the CSV."""
    return geohash_ids if label.startswith("geohash") else haversine_ids


def seed_search_pool(client, token, fetch) -> list[tuple[float, float, int]]:
    """Builds the pool of searches, dropping origins that return nothing.

    Empty cells would otherwise show up as errors on the geohash side (404) and as
    trivially fast empty responses on the haversine side.
    """
    pool = []
    attempts = 0
    while len(pool) < POOL_SIZE and attempts < POOL_SIZE * 4:
        attempts += 1
        lat, lon = random_point()
        radius = random.choice(RADII_KM)
        status_code, ids = fetch(client, token, lat, lon, radius, limit=ROW_LIMIT)
        if status_code == 200 and ids:
            pool.append((lat, lon, radius))

    if not pool:
        raise SystemExit("No routes found — run scripts/seed.py first")
    logger.info("Seeded pool with %s searches (%s attempts)", len(pool), attempts)
    return pool


def run_request(client, token, fetch, search) -> Result:
    lat, lon, radius = search

    start = time.perf_counter()
    status_code, ids = fetch(client, token, lat, lon, radius, limit=ROW_LIMIT)
    duration_ms = (time.perf_counter() - start) * 1000

    return Result(status_code, duration_ms, row_count=len(ids))


def percentile(sorted_values: list[float], pct: float) -> float:
    index = min(len(sorted_values) - 1, int(len(sorted_values) * pct))
    return sorted_values[index]


def summarize(results: list[Result], label: str) -> dict:
    latencies = sorted(r.duration_ms for r in results if r.status_code == 200)
    errors = [r for r in results if r.status_code != 200]

    stats = {
        "label": label,
        "requests": len(results),
        "ok": len(latencies),
        "errors": len(errors),
        "capped": 0,  # bbox-specific column, kept for schema parity
        "min_ms": min(latencies) if latencies else None,
        "mean_ms": sum(latencies) / len(latencies) if latencies else None,
        "p50_ms": percentile(latencies, 0.50) if latencies else None,
        "p95_ms": percentile(latencies, 0.95) if latencies else None,
        "p99_ms": percentile(latencies, 0.99) if latencies else None,
        "max_ms": max(latencies) if latencies else None,
    }

    logger.info("=== %s ===", label)
    logger.info(
        "requests: %s  ok: %s  errors: %s",
        stats["requests"],
        stats["ok"],
        stats["errors"],
    )
    if errors:
        codes: dict[int, int] = {}
        for r in errors:
            codes[r.status_code] = codes.get(r.status_code, 0) + 1
        logger.info("error breakdown: %s", codes)
    if latencies:
        logger.info("min:    %.1fms", stats["min_ms"])
        logger.info("mean:   %.1fms", stats["mean_ms"])
        logger.info("p50:    %.1fms", stats["p50_ms"])
        logger.info("p95:    %.1fms", stats["p95_ms"])
        logger.info("p99:    %.1fms", stats["p99_ms"])
        logger.info("max:    %.1fms", stats["max_ms"])

    return stats


def write_csv(stats: dict, extra_params: dict):
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "params": str(extra_params),
        **stats,
    }
    # Checked before open(), which would otherwise create the file first
    existed = os.path.exists(OUTPUT_PATH)
    with open(OUTPUT_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not existed:
            writer.writeheader()
        writer.writerow(row)


def run_sql(label: str):
    """Times the two queries directly against Postgres, no HTTP in the way.

    The HTTP passes can't isolate the technique. With a small limit both queries
    early-exit on the primary key index and measure selectivity; with a large one
    JSON serialization swamps everything (160ms of a 166ms request at limit=10k).
    COUNT(*) has neither problem: no rows to serialize and no early exit, so the
    predicate runs over the table exactly as the technique demands.

    Needs DB env vars (POSTGRES_HOST=localhost POSTGRES_PORT=5433 ...), unlike the
    HTTP passes which only need a running API -- hence the local imports, so those
    passes stay runnable without app config.
    """
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

    from sqlalchemy import func, select

    from app.api.routes.routes import calculate_geohash, haversine_km
    from app.db.models import Routes
    from app.db.session import engine

    use_geohash = label.startswith("geohash")
    pool = [(*random_point(), random.choice(RADII_KM)) for _ in range(POOL_SIZE)]

    results = []
    with engine.connect() as conn:
        for lat, lon, radius in (random.choice(pool) for _ in range(SQL_REQUESTS)):
            if use_geohash:
                prefix = calculate_geohash(radius, lat, lon)
                where = Routes.geohash.startswith(prefix)
            else:
                where = haversine_km(lat, lon) <= radius
            stmt = select(func.count()).select_from(Routes).where(where)

            start = time.perf_counter()
            conn.execute(stmt).scalar_one()
            results.append(Result(200, (time.perf_counter() - start) * 1000))

    stats = summarize(results, label)
    write_csv(
        stats,
        {"search_pool": POOL_SIZE, "radii_km": RADII_KM, "query": "count(*)"},
    )


def run_accuracy(client: httpx.Client, token: str):
    """Compares the geohash result set against the haversine truth set.

    Both sides are fetched uncapped so recall means what it says — with both capped
    at 100 rows you'd be comparing two truncated lists, not a search against reality.
    """
    per_radius: dict[int, list[tuple[int, int, int]]] = {r: [] for r in RADII_KM}
    origins = 0
    attempts = 0

    while origins < ACCURACY_ORIGINS and attempts < ACCURACY_ORIGINS * 4:
        attempts += 1
        lat, lon = random_point()
        radius = random.choice(RADII_KM)

        _, truth = haversine_ids(client, token, lat, lon, radius, limit=TRUTH_LIMIT)
        if not truth:
            continue
        _, found = geohash_ids(client, token, lat, lon, radius, limit=TRUTH_LIMIT)

        truth_set, found_set = set(truth), set(found)
        per_radius[radius].append(
            (len(truth_set & found_set), len(truth_set), len(found_set))
        )
        origins += 1

    logger.info("=== accuracy over %s origins ===", origins)
    logger.info("%-8s %8s %10s %10s %10s", "radius", "origins", "recall", "false+", "truth")

    totals = [0, 0, 0]
    summary = {}
    for radius in RADII_KM:
        samples = per_radius[radius]
        if not samples:
            continue
        hits = sum(s[0] for s in samples)
        truth = sum(s[1] for s in samples)
        found = sum(s[2] for s in samples)
        totals = [totals[0] + hits, totals[1] + truth, totals[2] + found]

        recall = hits / truth if truth else 0.0
        false_pos = (found - hits) / found if found else 0.0
        summary[f"recall_{radius}km"] = round(recall, 4)
        logger.info(
            "%-8s %8s %9.1f%% %9.1f%% %10s",
            f"{radius}km",
            len(samples),
            recall * 100,
            false_pos * 100,
            truth // len(samples),
        )

    hits, truth, found = totals
    overall_recall = hits / truth if truth else 0.0
    overall_false_pos = (found - hits) / found if found else 0.0
    logger.info(
        "overall: recall %.1f%%  false positives %.1f%%",
        overall_recall * 100,
        overall_false_pos * 100,
    )

    stats = {
        "label": "accuracy",
        "requests": origins * 2,
        "ok": origins * 2,
        "errors": 0,
        "capped": 0,
        "min_ms": None,
        "mean_ms": None,
        "p50_ms": None,
        "p95_ms": None,
        "p99_ms": None,
        "max_ms": None,
    }
    write_csv(
        stats,
        {
            "origins": origins,
            "recall": round(overall_recall, 4),
            "false_positive_rate": round(overall_false_pos, 4),
            **summary,
        },
    )


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--label",
        default="haversine",
        help=(
            "tag for this run and the technique it selects: anything starting with "
            "'geohash' hits /routes/radius, anything else hits /routes/haversine "
            "(e.g. geohash_no_index, geohash_indexed)"
        ),
    )
    parser.add_argument(
        "--accuracy",
        action="store_true",
        help="run the recall comparison instead of the latency benchmark",
    )
    parser.add_argument(
        "--sql",
        action="store_true",
        help="time the queries directly against Postgres, skipping HTTP entirely",
    )
    args = parser.parse_args()

    if args.sql:
        run_sql(args.label)
        return

    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        token = get_token(client)

        if args.accuracy:
            run_accuracy(client, token)
            return

        fetch = fetcher_for(args.label)
        pool = seed_search_pool(client, token, fetch)
        results = [
            run_request(client, token, fetch, random.choice(pool))
            for _ in range(REQUESTS)
        ]

    stats = summarize(results, args.label)
    write_csv(
        stats,
        {
            "search_pool": len(pool),
            "radii_km": RADII_KM,
            "row_limit": ROW_LIMIT,
        },
    )


if __name__ == "__main__":
    main()
