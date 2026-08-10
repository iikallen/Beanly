#!/usr/bin/env python3
"""Small dependency-free load probe for safe read paths in the synthetic tenant."""

from __future__ import annotations

import argparse
import concurrent.futures
import math
import os
import statistics
import time
from urllib.request import Request, urlopen


def hit(url: str, token: str | None, organization_id: str | None, timeout: float) -> float:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if organization_id:
        headers["X-Organization-ID"] = organization_id
    started = time.perf_counter()
    with urlopen(Request(url, headers=headers), timeout=timeout) as response:
        if response.status >= 400:
            raise RuntimeError(f"HTTP {response.status}: {url}")
        response.read()
    return (time.perf_counter() - started) * 1000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--path", action="append", default=["/health/ready"])
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--max-p95-ms", type=float, default=300)
    args = parser.parse_args()
    if not args.base_url.startswith("https://"):
        parser.error("base_url must use https://")

    token = os.environ.get("LOAD_ACCESS_TOKEN")
    organization_id = os.environ.get("LOAD_ORGANIZATION_ID")
    urls = [f"{args.base_url.rstrip('/')}{args.path[index % len(args.path)]}" for index in range(args.requests)]
    latencies: list[float] = []
    errors: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(hit, url, token, organization_id, args.timeout) for url in urls]
        for future in concurrent.futures.as_completed(futures):
            try:
                latencies.append(future.result())
            except Exception as exc:  # the summary is more useful than the first failure
                errors.append(str(exc))

    if not latencies:
        print(f"load probe failed: {len(errors)} errors, no successful requests")
        return 1
    ordered = sorted(latencies)
    p95 = ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]
    print(
        f"requests={args.requests} ok={len(latencies)} errors={len(errors)} "
        f"mean_ms={statistics.mean(latencies):.1f} p95_ms={p95:.1f}"
    )
    if errors or p95 > args.max_p95_ms:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
