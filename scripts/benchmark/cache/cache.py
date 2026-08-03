"""
Benchmark the Redis cache-aside layer on GET /routes/radius/{radius}.

Read-heavy mix (95% reads) against a bounded pool of search origins, which is
the point: a real map client re-issues the same searches, and the endpoint keys
its cache on the geohash prefix, so nearby origins share an entry anyway.

Radii are mixed because the prefix length falls out of the radius: 50km scans a
3-char prefix (effectively the whole Canmore dataset), 10km a 5-char one. The
cheap and expensive ends of the endpoint are both represented.

The 5% writes POST a route near Canmore, which invalidates every cached search
whose prefix the new route falls under — so the hit rate reflects real churn.

NOTE: both endpoints are rate-limited to 5/minute. Set RATE_LIMIT_ENABLED=false
on the api container for *both* runs, otherwise you are benchmarking 429s.

Usage:
    # CACHE_ENABLED=false on the api container, then:
    python scripts/benchmark/cache/cache.py --label no_cache
    # CACHE_ENABLED=true, restart, redis-cli FLUSHALL, then:
    python scripts/benchmark/cache/cache.py --label with_cache

Requires a seeded DB (scripts/seed.py).

Always runs REQUESTS requests and appends the summary to
scripts/benchmark/cache/results.csv, using the same columns as
scripts/benchmark/bbox/results.csv. "capped" is a bbox-specific stat with no
meaning here and is always 0; the cache-specific knobs (pool size, read/write
split) ride in the free-form "params" column.
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
WRITE_PCT = 5  # percent of requests that are POSTs
RADII_KM = [10, 25, 50]  # 5-, 4- and 3-char geohash prefixes respectively


@dataclass
class Result:
    status_code: int
    duration_ms: float
    op: str  # "read" or "write"


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


def seed_search_pool(client: httpx.Client, token: str) -> list[tuple[float, float, int]]:
    """Builds the pool of searches, dropping any origin whose cell is empty.

    Empty cells 404, which would otherwise show up in the error count and be
    mistaken for a real failure.
    """
    pool = []
    attempts = 0
    while len(pool) < POOL_SIZE and attempts < POOL_SIZE * 4:
        attempts += 1
        lat, lon = random_point()
        radius = random.choice(RADII_KM)
        resp = client.get(
            f"/routes/radius/{radius}",
            params={"lat": lat, "lon": lon},
            headers={"token": token},
        )
        if resp.status_code == 200:
            pool.append((lat, lon, radius))

    if not pool:
        raise SystemExit("No routes found — run scripts/seed.py first")
    logger.info("Seeded pool with %s searches (%s attempts)", len(pool), attempts)
    return pool


def read_request(
    client: httpx.Client, token: str, search: tuple[float, float, int]
) -> Result:
    lat, lon, radius = search

    start = time.perf_counter()
    resp = client.get(
        f"/routes/radius/{radius}",
        params={"lat": lat, "lon": lon},
        headers={"token": token},
    )
    duration_ms = (time.perf_counter() - start) * 1000
    return Result(resp.status_code, duration_ms, op="read")


def write_request(client: httpx.Client, token: str) -> Result:
    lat, lon = random_point()
    payload = {"name": f"bench-{uuid.uuid4().hex[:8]}", "lat": lat, "lon": lon}

    start = time.perf_counter()
    resp = client.post("/routes/", json=payload, headers={"token": token})
    duration_ms = (time.perf_counter() - start) * 1000
    return Result(resp.status_code, duration_ms, op="write")


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

    reads = [r for r in results if r.op == "read"]
    writes = [r for r in results if r.op == "write"]

    logger.info("=== %s ===", label)
    logger.info(
        "requests: %s  ok: %s  errors: %s  reads: %s  writes: %s",
        stats["requests"],
        stats["ok"],
        stats["errors"],
        len(reads),
        len(writes),
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


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--label",
        default="vanilla",
        help="tag for this run, used in the summary and CSV output",
    )
    args = parser.parse_args()

    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        token = get_token(client)
        pool = seed_search_pool(client, token)

        results = []
        for _ in range(REQUESTS):
            if random.randint(1, 100) <= WRITE_PCT:
                results.append(write_request(client, token))
            else:
                results.append(read_request(client, token, random.choice(pool)))

    stats = summarize(results, args.label)
    write_csv(
        stats,
        {
            "search_pool": len(pool),
            "radii_km": RADII_KM,
            "read_write_pct": f"{100 - WRITE_PCT}/{WRITE_PCT}",
        },
    )


if __name__ == "__main__":
    main()
