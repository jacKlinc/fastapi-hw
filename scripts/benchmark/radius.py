"""
Benchmark GET /routes/radius/{radius}.

NOTE: the endpoint is rate-limited to 5/minute (see routes.py). Bump or
disable slowapi's limiter before running anything beyond a handful of
requests, otherwise you're mostly benchmarking 429 responses.

Usage:
    python scripts/benchmark/radius.py --label vanilla
    python scripts/benchmark/radius.py --label offset --offset 100 --limit 50
    python scripts/benchmark/radius.py --label page --page 2 --pageSize 50
    python scripts/benchmark/radius.py --label keyset --keyset 67

Always runs REQUESTS requests and appends the summary to scripts/benchmark/results.csv.
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
REQUESTS = 1_000
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "results.csv")

# Matches the data seeded by scripts/seed.py
CANMORE_LAT = 51.0884
CANMORE_LON = -115.3479
RADIUS = 50


@dataclass
class Result:
    status_code: int
    duration_ms: float
    since_id: int | None = None
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
    client: httpx.Client, token: str, extra_params: dict, since_id: int | None = None
) -> Result:
    params = {"lat": CANMORE_LAT, "lon": CANMORE_LON, **extra_params}
    if since_id is not None:
        params["since_id"] = since_id

    start = time.perf_counter()
    resp = client.get(
        f"/routes/radius/{RADIUS}",
        params=params,
        headers={"token": token},
    )
    duration_ms = (time.perf_counter() - start) * 1000

    if resp.status_code != 200:
        return Result(resp.status_code, duration_ms)

    json_resp = resp.json()
    next_since_id = json_resp[-1]["id"] if json_resp else None
    return Result(resp.status_code, duration_ms, next_since_id, len(json_resp))


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


def write_csv(stats: dict, extra_params: dict):
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "params": str(extra_params),
        **stats,
    }
    with open(OUTPUT_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not os.path.exists(OUTPUT_PATH):
            writer.writeheader()
        writer.writerow(row)


def build_params(args: argparse.Namespace) -> dict:
    params = {}
    if args.offset is not None:
        params["offset"] = args.offset
    if args.limit is not None:
        params["limit"] = args.limit
    if args.page is not None:
        params["page"] = args.page
    if args.page_size is not None:
        params["pageSize"] = args.page_size
    return params


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--label",
        default="vanilla",
        help="tag for this run, used in the summary and CSV output",
    )
    parser.add_argument("--offset", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--page", type=int, default=None)
    parser.add_argument("--pageSize", type=int, default=None, dest="page_size")
    parser.add_argument(
        "--since_id",
        type=int,
        default=None,
        help="keyset pagination: walk forward starting from this id",
    )
    args = parser.parse_args()

    extra_params = build_params(args)
    keyset = args.since_id is not None

    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        token = get_token(client)
        results = []
        since_id = args.since_id
        for _ in range(REQUESTS):
            result = run_request(client, token, extra_params, since_id if keyset else None)
            results.append(result)
            if result.status_code != 200:
                break
            if keyset:
                since_id = result.since_id

    stats = summarize(results, args.label)
    write_csv(stats, extra_params)


if __name__ == "__main__":
    main()
