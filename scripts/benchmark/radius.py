"""
Benchmark GET /routes/radius/{radius}.

NOTE: the endpoint is rate-limited to 5/minute (see routes.py). Bump or
disable slowapi's limiter before running anything beyond a handful of
requests, otherwise you're mostly benchmarking 429 responses.

Usage:
    python scripts/benchmark/radius.py --label vanilla --requests 50
    python scripts/benchmark/radius.py --label offset --requests 50 \\
        --param page=1 --param page_size=100 --output scripts/benchmark/results.csv
"""

import argparse
import csv
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"

# Matches the data seeded by scripts/seed.py
CANMORE_LAT = 51.0884
CANMORE_LON = -115.3479


@dataclass
class Result:
    status_code: int
    duration_ms: float
    row_count: int | None = None


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


def run_request(
    client: httpx.Client,
    radius: int,
    lat: float,
    lon: float,
    token: str,
    extra_params: dict,
) -> Result:
    start = time.perf_counter()
    resp = client.get(
        f"/routes/radius/{radius}",
        params={"lat": lat, "lon": lon, **extra_params},
        headers={"token": token},
    )
    duration_ms = (time.perf_counter() - start) * 1000
    row_count = len(resp.json()) if resp.status_code == 200 else None
    return Result(resp.status_code, duration_ms, row_count)


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


def write_csv(path: str, stats: dict, extra_params: dict):
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "params": str(extra_params),
        **stats,
    }
    file_exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--radius", type=int, default=50)
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument(
        "--token",
        default=None,
        help="reuse an existing JWT instead of registering a new user",
    )
    parser.add_argument(
        "--label",
        default="vanilla",
        help="tag for this run, used in the summary and CSV output",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="extra query param as key=value, repeatable (e.g. --param page=1 --param page_size=100)",
    )
    parser.add_argument(
        "--output", default=None, help="CSV file to append this run's summary stats to"
    )
    args = parser.parse_args()

    extra_params = dict(p.split("=", 1) for p in args.param)

    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        token = args.token or get_token(client)
        results = [
            run_request(
                client, args.radius, CANMORE_LAT, CANMORE_LON, token, extra_params
            )
            for _ in range(args.requests)
        ]

    stats = summarize(results, args.label)
    if args.output:
        write_csv(args.output, stats, extra_params)


if __name__ == "__main__":
    main()
