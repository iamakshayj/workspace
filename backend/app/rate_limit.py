import asyncio
from hashlib import sha256
from ipaddress import ip_address
import logging
from time import time

from fastapi import Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from .auth import SESSION_COOKIE
from .config import Settings


logger = logging.getLogger("flowforge.http")
INCREMENT_WINDOW = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


class RequestRateLimiter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.redis: Redis | None = None
        self.local_counts: dict[tuple[str, int], int] = {}
        self.local_lock = asyncio.Lock()

    @property
    def mode(self) -> str:
        return "redis" if self.settings.redis_url else "local"

    async def start(self) -> None:
        if self.settings.redis_url:
            self.redis = Redis.from_url(
                self.settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                health_check_interval=30,
            )
            await self.redis.ping()

    async def stop(self) -> None:
        if self.redis:
            await self.redis.aclose()
            self.redis = None

    async def is_ready(self) -> bool:
        if not self.settings.redis_url:
            return True
        if not self.redis:
            return False
        try:
            return bool(await self.redis.ping())
        except (OSError, RedisError):
            return False

    def identity(self, request: Request) -> str:
        session_token = request.cookies.get(SESSION_COOKIE)
        client = request.client.host if request.client else "unknown"
        if self.settings.rate_limit_trust_forwarded_for:
            forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
            try:
                client = str(ip_address(forwarded))
            except ValueError:
                pass
        raw_identity = f"session:{session_token}" if session_token else f"client:{client}"
        return sha256(raw_identity.encode("utf-8")).hexdigest()[:32]

    async def check(self, request: Request) -> tuple[bool, int, int]:
        now = int(time())
        window = self.settings.request_rate_window_seconds
        window_id = now // window
        reset_after = window - (now % window)
        identity = self.identity(request)
        if self.redis:
            try:
                count = int(await self.redis.eval(
                    INCREMENT_WINDOW,
                    1,
                    f"flowforge:rate:{identity}:{window_id}",
                    window + 1,
                ))
            except (OSError, RedisError):
                logger.exception("Distributed rate limiting failed open")
                return True, self.settings.request_rate_limit, reset_after
        else:
            async with self.local_lock:
                key = (identity, window_id)
                count = self.local_counts.get(key, 0) + 1
                self.local_counts[key] = count
                if len(self.local_counts) > 10_000:
                    self.local_counts = {
                        item_key: value
                        for item_key, value in self.local_counts.items()
                        if item_key[1] >= window_id - 1
                    }
        remaining = max(0, self.settings.request_rate_limit - count)
        return count <= self.settings.request_rate_limit, remaining, reset_after


request_rate_limiter: RequestRateLimiter | None = None


def build_rate_limiter(settings: Settings) -> RequestRateLimiter:
    global request_rate_limiter
    request_rate_limiter = RequestRateLimiter(settings)
    return request_rate_limiter
