import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.requests import ClientDisconnect

from .config import Settings, get_settings
from sqlalchemy import text

from .database import User, init_database, session_factory, verify_database_revision
from .graphql_schema import graphql_router
from .model_client import LocalModelClient, ModelOutputError, ModelUnavailableError
from .schemas import HealthResponse
from .auth_routes import router as auth_router
from .artifact_routes import router as artifact_router
from .project_routes import router as project_router
from .internal_routes import router as internal_router
from .collaboration import router as collaboration_router
from .communications import router as communications_router
from .job_routes import router as job_router
from .storage_routes import router as storage_router
from .job_service import job_queue, job_worker
from .object_storage import object_storage
from .operational_routes import metrics_router, router as operational_router
from .process_intelligence import router as process_intelligence_router
from .work_management import router as work_management_router
from .knowledge import router as knowledge_router
from .enterprise import router as enterprise_router
from .enterprise_search import router as enterprise_search_router
from .work_graph import router as work_graph_router
from .work_intelligence import router as work_intelligence_router
from .change_proposals import router as change_proposals_router
from .assistant import router as assistant_router
from .identity_federation import identity_router, scim_router, sso_router
from .platform_admin import router as platform_router
from .public_api import router as public_api_router
from .quota_service import QuotaExceededError
from .rate_limit import build_rate_limiter
from .realtime import realtime_broker
from .telemetry import (
    RequestTimer,
    configure_logging,
    http_logger,
    metrics,
    request_id_context,
    request_identifiers,
    response_traceparent,
    trace_id_context,
)


settings = get_settings()
is_production = settings.environment.strip().lower() == "production"
configure_logging(settings.environment)
rate_limiter = build_rate_limiter(settings)


def is_client_disconnect(error: BaseException) -> bool:
    if isinstance(error, ClientDisconnect):
        return True
    nested = getattr(error, "exceptions", ())
    return bool(nested) and all(is_client_disconnect(item) for item in nested)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await realtime_broker.start()
    worker_task = None
    try:
        if is_production:
            await verify_database_revision()
        else:
            await init_database()
        await object_storage.start()
        await job_queue.start()
        await rate_limiter.start()
        if settings.embedded_worker_enabled:
            worker_task = asyncio.create_task(
                job_worker.run_forever(),
                name="embedded-background-worker",
            )
        yield
    finally:
        job_worker.stop()
        if worker_task:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
        await job_queue.stop()
        await rate_limiter.stop()
        await realtime_broker.stop()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="FlowForge process intelligence and collaboration API.",
    lifespan=lifespan,
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
    openapi_url=None if is_production else "/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "If-Match",
        "Traceparent",
        "X-Request-ID",
        "X-FlowForge-Storage-Token",
    ],
    expose_headers=[
        "X-Request-ID",
        "Traceparent",
        "RateLimit-Limit",
        "RateLimit-Remaining",
        "RateLimit-Reset",
        "Retry-After",
        "X-FlowForge-Instance",
    ],
)


@app.middleware("http")
async def request_controls(request: Request, call_next):
    request_id, trace_id = request_identifiers(
        request.headers.get("X-Request-ID"),
        request.headers.get("Traceparent"),
    )
    request_token = request_id_context.set(request_id)
    trace_token = trace_id_context.set(trace_id)
    timer = RequestTimer()
    response = None
    remaining = settings.request_rate_limit
    reset_after = settings.request_rate_window_seconds
    try:
        if request.method != "OPTIONS" and request.url.path not in {"/health", "/ready", "/status", "/metrics"}:
            allowed, remaining, reset_after = await rate_limiter.check(request)
            if not allowed:
                metrics.record_rate_limit()
                response = JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": "Request rate limit exceeded. Try again shortly.",
                        "code": "rate_limited",
                    },
                    headers={"Retry-After": str(reset_after)},
                )
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
    except ClientDisconnect:
        duration = timer.elapsed()
        http_logger.info(
            "Request cancelled by client",
            extra={
                "event": "http.request.cancelled",
                "method": request.method,
                "route": "unmatched",
                "status_code": 499,
                "duration_ms": round(duration * 1000, 2),
            },
        )
        response = Response(status_code=499)
    except Exception as error:
        if is_client_disconnect(error):
            duration = timer.elapsed()
            http_logger.info(
                "Request cancelled by client",
                extra={
                    "event": "http.request.cancelled",
                    "method": request.method,
                    "route": "unmatched",
                    "status_code": 499,
                    "duration_ms": round(duration * 1000, 2),
                },
            )
            response = Response(status_code=499)
        else:
            duration = timer.elapsed()
            metrics.record_http(request.method, "unmatched", 500, duration)
            http_logger.exception(
                "Unhandled request error",
                extra={
                    "event": "http.request.failed",
                    "method": request.method,
                    "route": "unmatched",
                    "status_code": 500,
                    "duration_ms": round(duration * 1000, 2),
                },
            )
            raise
    finally:
        if response is None:
            request_id_context.reset(request_token)
            trace_id_context.reset(trace_token)
    route_object = request.scope.get("route")
    route = getattr(route_object, "path", "unmatched")
    duration = timer.elapsed()
    metrics.record_http(request.method, route, response.status_code, duration)
    http_logger.info(
        "Request completed",
        extra={
            "event": "http.request.completed",
            "method": request.method,
            "route": route,
            "status_code": response.status_code,
            "duration_ms": round(duration * 1000, 2),
        },
    )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-FlowForge-Instance"] = settings.instance_id
    response.headers["Traceparent"] = response_traceparent(trace_id)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(self), display-capture=(self), geolocation=()")
    if request.url.path.startswith((settings.api_prefix, "/graphql", "/public/")):
        response.headers.setdefault("Cache-Control", "private, no-store")
    if request.url.path not in {"/health", "/ready", "/status", "/metrics"}:
        response.headers["RateLimit-Limit"] = str(settings.request_rate_limit)
        response.headers["RateLimit-Remaining"] = str(remaining)
        response.headers["RateLimit-Reset"] = str(reset_after)
    request_id_context.reset(request_token)
    trace_id_context.reset(trace_token)
    return response
app.include_router(project_router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(sso_router, prefix=settings.api_prefix)
app.include_router(identity_router, prefix=settings.api_prefix)
app.include_router(scim_router)
app.include_router(internal_router, prefix=settings.api_prefix)
app.include_router(collaboration_router, prefix=settings.api_prefix)
app.include_router(communications_router, prefix=settings.api_prefix)
app.include_router(job_router, prefix=settings.api_prefix)
app.include_router(storage_router, prefix=settings.api_prefix)
app.include_router(artifact_router, prefix=settings.api_prefix)
app.include_router(operational_router, prefix=settings.api_prefix)
app.include_router(process_intelligence_router, prefix=settings.api_prefix)
app.include_router(work_management_router, prefix=settings.api_prefix)
app.include_router(knowledge_router, prefix=settings.api_prefix)
app.include_router(enterprise_router, prefix=settings.api_prefix)
app.include_router(work_graph_router, prefix=settings.api_prefix)
app.include_router(work_intelligence_router, prefix=settings.api_prefix)
app.include_router(change_proposals_router, prefix=settings.api_prefix)
app.include_router(enterprise_search_router, prefix=settings.api_prefix)
app.include_router(assistant_router, prefix=settings.api_prefix)
app.include_router(platform_router, prefix=settings.api_prefix)
app.include_router(public_api_router)
app.include_router(metrics_router)
app.include_router(graphql_router, prefix="/graphql")


def get_model_client(config: Settings = Depends(get_settings)) -> LocalModelClient:
    return LocalModelClient(config)


async def database_is_ready() -> bool:
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@app.exception_handler(ModelUnavailableError)
async def model_unavailable_handler(_: Request, exc: ModelUnavailableError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": str(exc), "code": "model_unavailable"},
    )


@app.exception_handler(ModelOutputError)
async def model_output_handler(_: Request, exc: ModelOutputError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"detail": str(exc), "code": "invalid_model_output"},
    )


@app.exception_handler(QuotaExceededError)
async def quota_exceeded_handler(_: Request, exc: QuotaExceededError) -> JSONResponse:
    metrics.record_quota(exc.resource)
    quota_status = (
        status.HTTP_429_TOO_MANY_REQUESTS
        if "generation" in exc.resource
        else status.HTTP_409_CONFLICT
    )
    return JSONResponse(
        status_code=quota_status,
        content={
            "detail": str(exc),
            "code": "quota_exceeded",
            "resource": exc.resource,
            "limit": exc.limit,
            "used": exc.used,
        },
    )


@app.get("/health", response_model=HealthResponse)
async def health(
    config: Settings = Depends(get_settings),
    model: LocalModelClient = Depends(get_model_client),
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        database_reachable=await database_is_ready(),
        model=config.model_name,
        model_server_reachable=await model.is_reachable(),
        realtime_mode=realtime_broker.mode,
        realtime_server_reachable=await realtime_broker.is_ready(),
        job_queue_mode=job_queue.mode,
        job_queue_reachable=await job_queue.is_ready(),
        storage_mode=object_storage.mode,
        storage_reachable=await object_storage.is_ready(),
        rate_limit_mode=rate_limiter.mode,
        rate_limit_reachable=await rate_limiter.is_ready(),
    )


@app.get("/ready")
async def readiness() -> JSONResponse:
    database_ready, realtime_ready, queue_ready, storage_ready, rate_limit_ready = await asyncio.gather(
        database_is_ready(),
        realtime_broker.is_ready(),
        job_queue.is_ready(),
        object_storage.is_ready(),
        rate_limiter.is_ready(),
    )
    if not all((database_ready, realtime_ready, queue_ready, storage_ready, rate_limit_ready)):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "not_ready",
                "database": database_ready,
                "realtime": realtime_ready,
                "job_queue": queue_ready,
                "storage": storage_ready,
                "rate_limit": rate_limit_ready,
            },
        )
    return JSONResponse(
        content={
            "status": "ready",
            "database": "connected",
            "realtime": realtime_broker.mode,
            "job_queue": job_queue.mode,
            "storage": object_storage.mode,
            "rate_limit": rate_limiter.mode,
        }
    )


@app.get("/status", include_in_schema=False)
async def public_status() -> JSONResponse:
    """Return a credential-free, non-sensitive service status for status pages."""
    database_ready, realtime_ready, queue_ready, storage_ready, rate_limit_ready = await asyncio.gather(
        database_is_ready(), realtime_broker.is_ready(), job_queue.is_ready(),
        object_storage.is_ready(), rate_limiter.is_ready(),
    )
    components = {
        "api": "operational",
        "database": "operational" if database_ready else "degraded",
        "realtime": "operational" if realtime_ready else "degraded",
        "jobs": "operational" if queue_ready else "degraded",
        "storage": "operational" if storage_ready else "degraded",
        "traffic_controls": "operational" if rate_limit_ready else "degraded",
    }
    overall = "operational" if all(value == "operational" for value in components.values()) else "degraded"
    return JSONResponse(status_code=200 if overall == "operational" else 503, content={
        "status": overall,
        "components": components,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    })
