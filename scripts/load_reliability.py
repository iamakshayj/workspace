"""Bounded authenticated HTTP load check for a deployed FlowForge API.

Read-only by default. This script never creates projects, jobs, or attachments.
"""
import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
from time import perf_counter

import httpx


@dataclass(frozen=True)
class Observation:
    status_code: int
    duration: float
    instance_id: str = ""
    request_id: str = ""


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percent))
    return ordered[index]


async def run(args: argparse.Namespace) -> int:
    limits = httpx.Limits(
        max_connections=args.concurrency,
        max_keepalive_connections=args.concurrency,
    )
    timeout = httpx.Timeout(args.timeout)
    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"),
        limits=limits,
        timeout=timeout,
        follow_redirects=False,
    ) as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": args.email, "password": args.password},
        )
        login.raise_for_status()
        semaphore = asyncio.Semaphore(args.concurrency)

        async def request_once() -> Observation:
            async with semaphore:
                started = perf_counter()
                try:
                    response = await client.get(args.path)
                    return Observation(
                        response.status_code,
                        perf_counter() - started,
                        response.headers.get("X-FlowForge-Instance", ""),
                        response.headers.get("X-Request-ID", ""),
                    )
                except httpx.HTTPError:
                    return Observation(0, perf_counter() - started)

        started = perf_counter()
        observations = await asyncio.gather(
            *(request_once() for _ in range(args.requests))
        )
        wall_time = perf_counter() - started

    statuses = Counter(item.status_code for item in observations)
    latencies = [item.duration for item in observations]
    failures = sum(count for code, count in statuses.items() if code == 0 or code >= 500)
    throttled = statuses.get(429, 0)
    instances = {item.instance_id for item in observations if item.instance_id}
    request_ids = {item.request_id for item in observations if item.request_id}
    print(f"requests={args.requests} concurrency={args.concurrency} wall={wall_time:.3f}s")
    print(f"throughput={args.requests / max(wall_time, 0.001):.2f} req/s statuses={dict(statuses)}")
    print(
        "latency "
        f"p50={percentile(latencies, 0.50) * 1000:.1f}ms "
        f"p95={percentile(latencies, 0.95) * 1000:.1f}ms "
        f"p99={percentile(latencies, 0.99) * 1000:.1f}ms"
    )
    print(f"instances={sorted(instances)} unique_request_ids={len(request_ids)}")
    if failures:
        print(f"FAILED: {failures} transport or server errors")
        return 1
    if args.expect_rate_limit and throttled == 0:
        print("FAILED: the run expected at least one 429 response")
        return 1
    if not args.expect_rate_limit and throttled:
        print(f"FAILED: {throttled} requests were throttled unexpectedly")
        return 1
    if percentile(latencies, 0.95) * 1000 > args.max_p95_ms:
        print(f"FAILED: p95 exceeded {args.max_p95_ms:.0f}ms")
        return 1
    if len(instances) < args.min_instances:
        print(
            f"FAILED: observed {len(instances)} API instances; "
            f"expected at least {args.min_instances}"
        )
        return 1
    if len(request_ids) != args.requests:
        print("FAILED: response request IDs were missing or duplicated")
        return 1
    print("PASSED")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--path", default="/api/v1/projects")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--max-p95-ms", type=float, default=750.0)
    parser.add_argument("--expect-rate-limit", action="store_true")
    parser.add_argument("--min-instances", type=int, default=1)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1:
        parser.error("requests and concurrency must be positive")
    if args.concurrency > 500:
        parser.error("concurrency is capped at 500 for operator safety")
    return args


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
