from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import re
from secrets import token_hex
from threading import Lock
from time import perf_counter


request_id_context: ContextVar[str] = ContextVar("request_id", default="-")
trace_id_context: ContextVar[str] = ContextVar("trace_id", default="-")
VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
VALID_TRACEPARENT = re.compile(
    r"^[\da-f]{2}-([\da-f]{32})-([\da-f]{16})-([\da-f]{2})$",
    re.IGNORECASE,
)
HISTOGRAM_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def request_identifiers(request_id_header: str | None, traceparent: str | None) -> tuple[str, str]:
    request_id = (
        request_id_header
        if request_id_header and VALID_REQUEST_ID.fullmatch(request_id_header)
        else token_hex(12)
    )
    trace_match = VALID_TRACEPARENT.fullmatch(traceparent or "")
    trace_id = trace_match.group(1).lower() if trace_match else token_hex(16)
    return request_id, trace_id


def response_traceparent(trace_id: str) -> str:
    return f"00-{trace_id}-{token_hex(8)}-01"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_context.get(),
            "trace_id": trace_id_context.get(),
        }
        for field in (
            "event",
            "method",
            "route",
            "status_code",
            "duration_ms",
            "job_kind",
            "job_status",
            "resource",
        ):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def configure_logging(environment: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if environment == "production" else logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    ))
    for logger_name in ("flowforge", "flowforge.http", "flowforge.jobs", "flowforge.maintenance"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(**labels: str) -> str:
    return "{" + ",".join(
        f'{key}="{_escape_label(value)}"' for key, value in sorted(labels.items())
    ) + "}"


class MetricsRegistry:
    def __init__(self) -> None:
        self.lock = Lock()
        self.http_requests: dict[tuple[str, str, str], int] = defaultdict(int)
        self.http_duration_count: dict[tuple[str, str], int] = defaultdict(int)
        self.http_duration_sum: dict[tuple[str, str], float] = defaultdict(float)
        self.http_duration_buckets: dict[tuple[str, str, float], int] = defaultdict(int)
        self.rate_limit_rejections: dict[str, int] = defaultdict(int)
        self.quota_rejections: dict[str, int] = defaultdict(int)
        self.jobs: dict[tuple[str, str], int] = defaultdict(int)
        self.job_duration_count: dict[tuple[str, str], int] = defaultdict(int)
        self.job_duration_sum: dict[tuple[str, str], float] = defaultdict(float)
        self.maintenance: dict[str, int] = defaultdict(int)

    def record_http(self, method: str, route: str, status_code: int, duration: float) -> None:
        status_class = f"{status_code // 100}xx"
        route = route if route.startswith("/") else "unmatched"
        with self.lock:
            self.http_requests[(method, route, status_class)] += 1
            self.http_duration_count[(method, route)] += 1
            self.http_duration_sum[(method, route)] += duration
            for bucket in HISTOGRAM_BUCKETS:
                if duration <= bucket:
                    self.http_duration_buckets[(method, route, bucket)] += 1

    def record_rate_limit(self, scope: str = "http") -> None:
        with self.lock:
            self.rate_limit_rejections[scope] += 1

    def record_quota(self, resource: str) -> None:
        with self.lock:
            self.quota_rejections[resource] += 1

    def record_job(self, kind: str, status: str, duration: float) -> None:
        with self.lock:
            self.jobs[(kind, status)] += 1
            self.job_duration_count[(kind, status)] += 1
            self.job_duration_sum[(kind, status)] += duration

    def record_maintenance(self, action: str, count: int) -> None:
        with self.lock:
            self.maintenance[action] += count

    def render(self, gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] | None = None) -> str:
        lines = [
            "# HELP flowforge_http_requests_total HTTP requests by bounded route template.",
            "# TYPE flowforge_http_requests_total counter",
        ]
        with self.lock:
            for (method, route, status_class), value in sorted(self.http_requests.items()):
                lines.append(
                    "flowforge_http_requests_total"
                    + _labels(method=method, route=route, status_class=status_class)
                    + f" {value}"
                )
            lines.extend([
                "# HELP flowforge_http_request_duration_seconds HTTP request latency.",
                "# TYPE flowforge_http_request_duration_seconds histogram",
            ])
            for method, route in sorted(self.http_duration_count):
                base_labels = {"method": method, "route": route}
                for bucket in HISTOGRAM_BUCKETS:
                    value = self.http_duration_buckets[(method, route, bucket)]
                    lines.append(
                        "flowforge_http_request_duration_seconds_bucket"
                        + _labels(**base_labels, le=str(bucket))
                        + f" {value}"
                    )
                count = self.http_duration_count[(method, route)]
                lines.append(
                    "flowforge_http_request_duration_seconds_bucket"
                    + _labels(**base_labels, le="+Inf")
                    + f" {count}"
                )
                lines.append(
                    "flowforge_http_request_duration_seconds_sum"
                    + _labels(**base_labels)
                    + f" {self.http_duration_sum[(method, route)]:.6f}"
                )
                lines.append(
                    "flowforge_http_request_duration_seconds_count"
                    + _labels(**base_labels)
                    + f" {count}"
                )
            lines.extend([
                "# TYPE flowforge_rate_limit_rejections_total counter",
                *[
                    "flowforge_rate_limit_rejections_total"
                    + _labels(scope=scope)
                    + f" {value}"
                    for scope, value in sorted(self.rate_limit_rejections.items())
                ],
                "# TYPE flowforge_quota_rejections_total counter",
                *[
                    "flowforge_quota_rejections_total"
                    + _labels(resource=resource)
                    + f" {value}"
                    for resource, value in sorted(self.quota_rejections.items())
                ],
                "# TYPE flowforge_background_jobs_total counter",
                *[
                    "flowforge_background_jobs_total"
                    + _labels(kind=kind, status=status)
                    + f" {value}"
                    for (kind, status), value in sorted(self.jobs.items())
                ],
                "# TYPE flowforge_background_job_duration_seconds summary",
                *[
                    "flowforge_background_job_duration_seconds_sum"
                    + _labels(kind=kind, status=status)
                    + f" {self.job_duration_sum[(kind, status)]:.6f}"
                    for kind, status in sorted(self.job_duration_count)
                ],
                *[
                    "flowforge_background_job_duration_seconds_count"
                    + _labels(kind=kind, status=status)
                    + f" {self.job_duration_count[(kind, status)]}"
                    for kind, status in sorted(self.job_duration_count)
                ],
                "# TYPE flowforge_maintenance_actions_total counter",
                *[
                    "flowforge_maintenance_actions_total"
                    + _labels(action=action)
                    + f" {value}"
                    for action, value in sorted(self.maintenance.items())
                ],
            ])
        if gauges:
            gauge_names = sorted({name for name, _ in gauges})
            lines.extend(f"# TYPE {name} gauge" for name in gauge_names)
            for (name, label_pairs), value in sorted(gauges.items()):
                labels = dict(label_pairs)
                lines.append(name + (_labels(**labels) if labels else "") + f" {value}")
        return "\n".join(lines) + "\n"


metrics = MetricsRegistry()
http_logger = logging.getLogger("flowforge.http")


class RequestTimer:
    def __init__(self) -> None:
        self.started = perf_counter()

    def elapsed(self) -> float:
        return perf_counter() - self.started
