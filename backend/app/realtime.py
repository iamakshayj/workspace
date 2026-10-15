import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
import hashlib
import json
import logging
import time
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

from .config import get_settings


logger = logging.getLogger("flowforge.realtime")
RealtimeHandler = Callable[[dict[str, Any], "RealtimeEnvelope"], Awaitable[None]]


class RealtimeUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class RealtimeEnvelope:
    event_id: str
    origin_instance_id: str
    topic: str
    payload: dict[str, Any]
    exclude_connection_id: str | None = None


class InMemoryRealtimeBus:
    """Process-local development bus with the same contract as Redis."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self.instances: dict[str, RealtimeBroker] = {}
        self.presence: dict[str, dict[str, tuple[float, dict[str, Any]]]] = {}
        self.lock = asyncio.Lock()

    async def register(self, broker: "RealtimeBroker") -> None:
        async with self.lock:
            self.instances[broker.instance_id] = broker

    async def unregister(self, broker: "RealtimeBroker") -> None:
        async with self.lock:
            self.instances.pop(broker.instance_id, None)

    async def publish(self, envelope: RealtimeEnvelope) -> None:
        async with self.lock:
            instances = list(self.instances.values())
        await asyncio.gather(
            *(instance.deliver(envelope) for instance in instances),
            return_exceptions=True,
        )

    async def upsert_presence(
        self,
        room_id: str,
        connection_id: str,
        presence: dict[str, Any],
        ttl_seconds: int,
    ) -> None:
        async with self.lock:
            self.presence.setdefault(room_id, {})[connection_id] = (
                self.clock() + ttl_seconds,
                presence,
            )

    async def remove_presence(self, room_id: str, connection_id: str) -> None:
        async with self.lock:
            room = self.presence.get(room_id)
            if not room:
                return
            room.pop(connection_id, None)
            if not room:
                self.presence.pop(room_id, None)

    async def list_presence(
        self,
        room_id: str,
    ) -> tuple[list[dict[str, Any]], bool]:
        async with self.lock:
            room = self.presence.get(room_id, {})
            now = self.clock()
            stale = [
                connection_id
                for connection_id, (expires_at, _) in room.items()
                if expires_at <= now
            ]
            for connection_id in stale:
                room.pop(connection_id, None)
            if not room:
                self.presence.pop(room_id, None)
            records = [record for _, record in room.values()]
        return unique_presence(records), bool(stale)


LOCAL_REALTIME_BUS = InMemoryRealtimeBus()


def unique_presence(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    users: dict[str, dict[str, Any]] = {}
    for record in records:
        user_id = record.get("id")
        if isinstance(user_id, str) and user_id:
            users[user_id] = record
    return sorted(
        users.values(),
        key=lambda user: (
            str(user.get("display_name") or "").lower(),
            str(user.get("id") or ""),
        ),
    )


class RealtimeBroker:
    _PRESENCE_LIST_SCRIPT = """
local members = redis.call('SMEMBERS', KEYS[1])
local records = {}
local stale = 0
for _, connection_id in ipairs(members) do
  local value = redis.call('GET', ARGV[1] .. connection_id)
  if value then
    table.insert(records, value)
  else
    redis.call('SREM', KEYS[1], connection_id)
    stale = stale + 1
  end
end
table.insert(records, 1, tostring(stale))
return records
"""
    _PRESENCE_REMOVE_SCRIPT = """
redis.call('DEL', KEYS[2])
redis.call('SREM', KEYS[1], ARGV[1])
if redis.call('SCARD', KEYS[1]) == 0 then
  redis.call('DEL', KEYS[1])
end
return 1
"""

    def __init__(
        self,
        redis_url: str | None,
        *,
        channel_prefix: str = "flowforge",
        presence_ttl_seconds: int = 45,
        memory_bus: InMemoryRealtimeBus | None = None,
    ) -> None:
        self.redis_url = redis_url
        self.channel_prefix = channel_prefix.strip(":") or "flowforge"
        self.presence_ttl_seconds = presence_ttl_seconds
        self.memory_bus = memory_bus or LOCAL_REALTIME_BUS
        self.instance_id = str(uuid4())
        self.handlers: dict[str, dict[str, RealtimeHandler]] = {}
        self.handlers_lock = asyncio.Lock()
        self.redis: Redis | None = None
        self.pubsub: Any = None
        self.listener_task: asyncio.Task | None = None
        self.started = False
        self.stopping = False
        self.subscriber_ready = False

    @property
    def mode(self) -> str:
        return "redis" if self.redis_url else "local"

    async def start(self) -> None:
        if self.started:
            return
        self.stopping = False
        if not self.redis_url:
            await self.memory_bus.register(self)
            self.subscriber_ready = True
            self.started = True
            return
        try:
            self.redis = Redis.from_url(
                self.redis_url,
                decode_responses=True,
                health_check_interval=30,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            await self.redis.ping()
            await self._open_pubsub()
        except (OSError, RedisError) as error:
            if self.redis:
                await self.redis.aclose()
            self.redis = None
            raise RealtimeUnavailableError(
                "Redis is required for production realtime services but is unavailable."
            ) from error
        self.started = True
        self.listener_task = asyncio.create_task(
            self._listen_forever(),
            name=f"realtime-listener-{self.instance_id}",
        )

    async def stop(self) -> None:
        if not self.started and not self.redis:
            return
        self.stopping = True
        if self.listener_task:
            self.listener_task.cancel()
            try:
                await self.listener_task
            except asyncio.CancelledError:
                pass
            self.listener_task = None
        if self.pubsub:
            await self.pubsub.aclose()
            self.pubsub = None
        if self.redis:
            await self.redis.aclose()
            self.redis = None
        if not self.redis_url:
            await self.memory_bus.unregister(self)
        async with self.handlers_lock:
            self.handlers.clear()
        self.subscriber_ready = False
        self.started = False

    async def is_ready(self) -> bool:
        if not self.started or not self.subscriber_ready:
            return False
        if not self.redis_url:
            return True
        if not self.redis:
            return False
        try:
            return bool(await self.redis.ping())
        except (OSError, RedisError):
            return False

    async def subscribe(self, topic: str, handler: RealtimeHandler) -> str:
        if not self.started:
            raise RealtimeUnavailableError("Realtime broker has not started.")
        token = str(uuid4())
        async with self.handlers_lock:
            self.handlers.setdefault(topic, {})[token] = handler
        return token

    async def unsubscribe(self, topic: str, token: str) -> None:
        async with self.handlers_lock:
            topic_handlers = self.handlers.get(topic)
            if not topic_handlers:
                return
            topic_handlers.pop(token, None)
            if not topic_handlers:
                self.handlers.pop(topic, None)

    async def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        exclude_connection_id: str | None = None,
    ) -> None:
        if not self.started:
            raise RealtimeUnavailableError("Realtime broker has not started.")
        envelope = RealtimeEnvelope(
            event_id=str(uuid4()),
            origin_instance_id=self.instance_id,
            topic=topic,
            payload=payload,
            exclude_connection_id=exclude_connection_id,
        )
        if not self.redis_url:
            await self.memory_bus.publish(envelope)
            return
        if not self.redis:
            raise RealtimeUnavailableError("Redis publisher is unavailable.")
        try:
            await self.redis.publish(
                self._channel(topic),
                json.dumps(asdict(envelope), separators=(",", ":")),
            )
        except (OSError, RedisError) as error:
            raise RealtimeUnavailableError("Redis could not publish a realtime event.") from error

    async def deliver(self, envelope: RealtimeEnvelope) -> None:
        async with self.handlers_lock:
            handlers = list(self.handlers.get(envelope.topic, {}).values())
        if not handlers:
            return
        results = await asyncio.gather(
            *(handler(envelope.payload, envelope) for handler in handlers),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.error(
                    "Realtime event handler failed",
                    exc_info=(type(result), result, result.__traceback__),
                )

    async def upsert_presence(
        self,
        room_id: str,
        connection_id: str,
        presence: dict[str, Any],
    ) -> None:
        if not self.redis_url:
            await self.memory_bus.upsert_presence(
                room_id,
                connection_id,
                presence,
                self.presence_ttl_seconds,
            )
            return
        redis = self._required_redis()
        set_key, connection_prefix = self._presence_keys(room_id)
        connection_key = f"{connection_prefix}{connection_id}"
        try:
            async with redis.pipeline(transaction=False) as pipeline:
                pipeline.set(
                    connection_key,
                    json.dumps(presence, separators=(",", ":")),
                    ex=self.presence_ttl_seconds,
                )
                pipeline.sadd(set_key, connection_id)
                pipeline.expire(set_key, self.presence_ttl_seconds * 3)
                await pipeline.execute()
        except (OSError, RedisError) as error:
            raise RealtimeUnavailableError("Redis presence storage is unavailable.") from error

    async def remove_presence(self, room_id: str, connection_id: str) -> None:
        if not self.redis_url:
            await self.memory_bus.remove_presence(room_id, connection_id)
            return
        redis = self._required_redis()
        set_key, connection_prefix = self._presence_keys(room_id)
        try:
            await redis.eval(
                self._PRESENCE_REMOVE_SCRIPT,
                2,
                set_key,
                f"{connection_prefix}{connection_id}",
                connection_id,
            )
        except (OSError, RedisError) as error:
            raise RealtimeUnavailableError("Redis presence storage is unavailable.") from error

    async def list_presence(
        self,
        room_id: str,
    ) -> tuple[list[dict[str, Any]], bool]:
        if not self.redis_url:
            return await self.memory_bus.list_presence(room_id)
        redis = self._required_redis()
        set_key, connection_prefix = self._presence_keys(room_id)
        try:
            values = await redis.eval(
                self._PRESENCE_LIST_SCRIPT,
                1,
                set_key,
                connection_prefix,
            )
        except (OSError, RedisError) as error:
            raise RealtimeUnavailableError("Redis presence storage is unavailable.") from error
        stale_count = int(values[0]) if values else 0
        records = []
        for raw_value in values[1:]:
            try:
                record = json.loads(raw_value)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(record, dict):
                records.append(record)
        return unique_presence(records), stale_count > 0

    def _required_redis(self) -> Redis:
        if not self.started or not self.redis:
            raise RealtimeUnavailableError("Redis realtime services are unavailable.")
        return self.redis

    def _channel(self, topic: str) -> str:
        return f"{self.channel_prefix}:events:{topic}"

    def _presence_keys(self, room_id: str) -> tuple[str, str]:
        room_hash = hashlib.sha256(room_id.encode()).hexdigest()
        slot = f"{{{room_hash}}}"
        base = f"{self.channel_prefix}:presence:{slot}"
        return f"{base}:connections", f"{base}:connection:"

    async def _open_pubsub(self) -> None:
        if not self.redis:
            raise RealtimeUnavailableError("Redis subscriber is unavailable.")
        pubsub = self.redis.pubsub()
        try:
            await pubsub.psubscribe(f"{self.channel_prefix}:events:*")
        except Exception:
            await pubsub.aclose()
            raise
        self.pubsub = pubsub
        self.subscriber_ready = True

    async def _listen_forever(self) -> None:
        retry_delay = 0.25
        while not self.stopping:
            if not self.pubsub:
                try:
                    await self._open_pubsub()
                    retry_delay = 0.25
                except (OSError, RedisError, RealtimeUnavailableError):
                    self.subscriber_ready = False
                    logger.exception("Redis realtime subscription could not reconnect")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(5.0, retry_delay * 2)
                    continue
            try:
                async for message in self.pubsub.listen():
                    if message.get("type") != "pmessage":
                        continue
                    await self._handle_message(message.get("data"))
                if not self.stopping:
                    raise RealtimeUnavailableError("Redis subscription ended unexpectedly.")
            except asyncio.CancelledError:
                raise
            except (OSError, RedisError, RealtimeUnavailableError):
                self.subscriber_ready = False
                logger.exception("Redis realtime subscription disconnected")
            finally:
                if self.pubsub:
                    await self.pubsub.aclose()
                    self.pubsub = None
            if self.stopping:
                return
            await asyncio.sleep(retry_delay)
            retry_delay = min(5.0, retry_delay * 2)

    async def _handle_message(self, raw_message: Any) -> None:
        try:
            data = json.loads(raw_message)
            envelope = RealtimeEnvelope(
                event_id=str(data["event_id"]),
                origin_instance_id=str(data["origin_instance_id"]),
                topic=str(data["topic"]),
                payload=data["payload"],
                exclude_connection_id=data.get("exclude_connection_id"),
            )
            if not isinstance(envelope.payload, dict):
                raise ValueError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("Ignored malformed Redis realtime event")
            return
        await self.deliver(envelope)


_settings = get_settings()
realtime_broker = RealtimeBroker(
    _settings.redis_url,
    channel_prefix=_settings.realtime_channel_prefix,
    presence_ttl_seconds=_settings.presence_ttl_seconds,
)
