"""Bounded, read-only mixed-workload release gate for a deployed Workspace stack.

The suite exercises the application surfaces users keep open together: dashboard data,
work, calendar, chat, search, and readiness. It deliberately performs no mutations.
"""
import argparse
import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import perf_counter

import httpx


@dataclass(frozen=True)
class Observation:
    scenario: str
    status: int
    duration_ms: float
    request_id: str = ""
    instance: str = ""


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, round((len(values) - 1) * quantile))]


def graphql(query: str, variables: dict | None = None) -> tuple[str, str, dict]:
    return "POST", "/graphql", {"query": query, "variables": variables or {}}


def scenarios() -> list[tuple[str, str, str, dict | None]]:
    now = datetime.now(timezone.utc)
    month_end = now + timedelta(days=31)
    return [
        ("projects", "GET", "/api/v1/projects?first=24", None),
        ("work", "GET", "/api/v1/work/overview", None),
        ("search", "GET", "/api/v1/search?q=project&mode=keyword&limit=20&remember=false", None),
        ("chat", *graphql("query ScaleChat { communicationContacts { unreadCount } communicationChannels { id unreadCount } }")),
        ("calendar", *graphql(
            "query ScaleCalendar($start: DateTime!, $end: DateTime!) { calendarEvents(startsAfter: $start, startsBefore: $end) { id startsAt endsAt } }",
            {"start": now.isoformat(), "end": month_end.isoformat()},
        )),
        ("readiness", "GET", "/ready", None),
    ]


async def run(args: argparse.Namespace) -> int:
    timeout = httpx.Timeout(args.timeout)
    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), timeout=timeout, limits=limits) as client:
        login = await client.post("/api/v1/auth/login", json={"email": args.email, "password": args.password})
        login.raise_for_status()
        workload = scenarios()
        semaphore = asyncio.Semaphore(args.concurrency)

        async def execute(index: int) -> Observation:
            name, method, path, body = workload[index % len(workload)]
            async with semaphore:
                started = perf_counter()
                try:
                    response = await client.request(method, path, json=body)
                    status = response.status_code
                    if status < 500 and method == "POST":
                        payload = response.json()
                        if payload.get("errors"):
                            status = 599
                    return Observation(name, status, (perf_counter() - started) * 1000,
                                       response.headers.get("X-Request-ID", ""),
                                       response.headers.get("X-FlowForge-Instance", ""))
                except (httpx.HTTPError, ValueError):
                    return Observation(name, 0, (perf_counter() - started) * 1000)

        started = perf_counter()
        observations = await asyncio.gather(*(execute(index) for index in range(args.requests)))
        wall_seconds = perf_counter() - started

    by_scenario: dict[str, list[Observation]] = defaultdict(list)
    for item in observations:
        by_scenario[item.scenario].append(item)
    failed = [item for item in observations if item.status == 0 or item.status >= 500]
    throttled = [item for item in observations if item.status == 429]
    request_ids = [item.request_id for item in observations if item.request_id]
    instances = {item.instance for item in observations if item.instance}
    print(f"mixed_requests={len(observations)} concurrency={args.concurrency} wall={wall_seconds:.3f}s throughput={len(observations) / max(wall_seconds, .001):.2f}/s")
    for name, items in sorted(by_scenario.items()):
        durations = [item.duration_ms for item in items]
        statuses = Counter(item.status for item in items)
        print(f"{name}: count={len(items)} p50={percentile(durations, .50):.1f}ms p95={percentile(durations, .95):.1f}ms p99={percentile(durations, .99):.1f}ms statuses={dict(statuses)}")
    problems = []
    if failed:
        problems.append(f"{len(failed)} transport/server/GraphQL failures")
    if throttled and not args.allow_throttling:
        problems.append(f"{len(throttled)} unexpected rate-limit responses")
    if percentile([item.duration_ms for item in observations], .95) > args.max_p95_ms:
        problems.append(f"overall p95 exceeded {args.max_p95_ms:.0f}ms")
    if len(request_ids) != len(set(request_ids)) or len(request_ids) != len(observations):
        problems.append("request IDs are missing or duplicated")
    if len(instances) < args.min_instances:
        problems.append(f"observed {len(instances)} instances; expected {args.min_instances}")
    if problems:
        print("FAILED: " + "; ".join(problems))
        return 1
    print(f"PASSED: instances={sorted(instances)} unique_request_ids={len(request_ids)}")
    return 0


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--requests", type=int, default=600)
    parser.add_argument("--concurrency", type=int, default=30)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--max-p95-ms", type=float, default=1000)
    parser.add_argument("--min-instances", type=int, default=1)
    parser.add_argument("--allow-throttling", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 500 or not 1 <= args.requests <= 100_000:
        parser.error("concurrency must be 1..500 and requests must be 1..100000")
    return args


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(arguments())))
