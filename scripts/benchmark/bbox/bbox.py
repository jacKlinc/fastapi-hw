"""
Benchmark GET /routes/bbox.

No auth token needed (bbox is a public read endpoint) and no rate limit to
worry about, unlike scripts/benchmark/radius.py. Exercises a mix of small
("zoomed in") and large ("zoomed out", likely to hit BBOX_LIMIT) boxes
scattered around the seeded Canmore data.

Usage:
    python scripts/benchmark/bbox.py --label no_index
    python scripts/benchmark/bbox.py --label with_index

Always runs REQUESTS requests and appends the summary to scripts/benchmark/bbox_results.csv
(kept separate from results.csv since that file's columns don't include the
"capped" stat this benchmark also tracks).
"""

import argparse
import csv
import logging
import math
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"
REQUESTS = 1_000
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "bbox_results.csv")

# Matches the data seeded by scripts/seed.py
CANMORE_LAT = 51.0884
CANMORE_LON = -115.3479
SEED_RADIUS_KM = 50

# "Zoomed in" and "zoomed out" box half-widths, in km
SMALL_HALF_KM = 1
LARGE_HALF_KM = 70  # wider than SEED_RADIUS_KM so it reliably hits BBOX_LIMIT

KM_PER_DEG_LAT = 111.0


@dataclass
class Result:
    status_code: int
    duration_ms: float
    box_size: str | None = None
    row_count: int | None = None
    total_count: int | None = None
    capped: bool | None = None


def random_bbox(box_size: str) -> dict:
    half_km = SMALL_HALF_KM if box_size == "small" else LARGE_HALF_KM
    r = SEED_RADIUS_KM * math.sqrt(random.random())
    theta = random.uniform(0, 2 * math.pi)
    center_lat = CANMORE_LAT + (r / KM_PER_DEG_LAT) * math.cos(theta)
    center_lon = CANMORE_LON + (
        r / (KM_PER_DEG_LAT * math.cos(math.radians(CANMORE_LAT)))
    ) * math.sin(theta)

    dlat = half_km / KM_PER_DEG_LAT
    dlon = half_km / (KM_PER_DEG_LAT * math.cos(math.radians(center_lat)))
    return {
        "min_lat": center_lat - dlat,
        "max_lat": center_lat + dlat,
        "min_lon": center_lon - dlon,
        "max_lon": center_lon + dlon,
    }


def run_request(client: httpx.Client, box_size: str) -> Result:
    params = random_bbox(box_size)

    start = time.perf_counter()
    resp = client.get("/routes/bbox", params=params)
    duration_ms = (time.perf_counter() - start) * 1000

    if resp.status_code != 200:
        return Result(resp.status_code, duration_ms, box_size=box_size)

    body = resp.json()
    return Result(
        status_code=resp.status_code,
        duration_ms=duration_ms,
        box_size=box_size,
        row_count=len(body["routes"]),
        total_count=body["total_count"],
        capped=body["capped"],
    )


def percentile(sorted_values: list[float], pct: float) -> float:
    index = min(len(sorted_values) - 1, int(len(sorted_values) * pct))
    return sorted_values[index]


def summarize(results: list[Result], label: str) -> dict:
    latencies = sorted(r.duration_ms for r in results if r.status_code == 200)
    errors = [r for r in results if r.status_code != 200]
    capped = [r for r in results if r.capped]

    stats = {
        "label": label,
        "requests": len(results),
        "ok": len(latencies),
        "errors": len(errors),
        "capped": len(capped),
        "min_ms": min(latencies) if latencies else None,
        "mean_ms": sum(latencies) / len(latencies) if latencies else None,
        "p50_ms": percentile(latencies, 0.50) if latencies else None,
        "p95_ms": percentile(latencies, 0.95) if latencies else None,
        "p99_ms": percentile(latencies, 0.99) if latencies else None,
        "max_ms": max(latencies) if latencies else None,
    }

    logger.info("=== %s ===", label)
    logger.info(
        "requests: %s  ok: %s  errors: %s  capped: %s",
        stats["requests"],
        stats["ok"],
        stats["errors"],
        stats["capped"],
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
        results = [
            run_request(client, box_size=random.choice(["small", "large"]))
            for _ in range(REQUESTS)
        ]

    stats = summarize(results, args.label)
    write_csv(stats, {"small_half_km": SMALL_HALF_KM, "large_half_km": LARGE_HALF_KM})


if __name__ == "__main__":
    main()
