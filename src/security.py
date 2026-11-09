"""Shared Redis request limits with process-local fallback for sensitive endpoints."""
from collections import defaultdict, deque
from hashlib import sha256
from threading import Lock
from time import monotonic
from uuid import uuid4

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from src.config import settings


class RateLimitMiddleware:
    """Apply shared Redis sliding-window limits with a process-local fallback."""

    _REDIS_SCRIPT = """
    local now = redis.call('TIME')
    local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
    local window_ms = tonumber(ARGV[1])
    local limit = tonumber(ARGV[2])
    redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms - window_ms)
    local count = redis.call('ZCARD', KEYS[1])
    if count >= limit then
      local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
      local retry_ms = tonumber(oldest[2]) + window_ms - now_ms
      return {0, math.max(1, math.ceil(retry_ms / 1000))}
    end
    redis.call('ZADD', KEYS[1], now_ms, ARGV[3])
    redis.call('PEXPIRE', KEYS[1], window_ms)
    return {1, 0}
    """

    RULES = {
        "/api/v1/auth/login": (8, 300),
        "/api/v1/auth/register": (5, 3600),
        "/api/v1/auth/verify-email": (10, 900),
        "/api/v1/chat": (25, 60),
        "/api/v1/chat/guest": (15, 60),
        "/api/v1/orders/checkout": (12, 60),
    }
    MAX_KEYS = 10_000

    def __init__(self, app):
        self.app = app
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = Lock()
        self._redis = None
        self._redis_url = ""

    @classmethod
    def rule_for(cls, path: str):
        return cls.RULES.get(path)

    def check(self, client_ip: str, path: str, now: float | None = None):
        """Return retry-after seconds when blocked; exposed for deterministic tests."""
        rule = self.rule_for(path)
        if rule is None:
            return None
        limit, window = rule
        current = monotonic() if now is None else now
        key = (client_ip, path)
        with self._lock:
            events = self._events[key]
            cutoff = current - window
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return max(1, int(events[0] + window - current + 0.999))
            events.append(current)
            if len(self._events) > self.MAX_KEYS:
                self._events = defaultdict(
                    deque,
                    {k: q for k, q in self._events.items() if q and q[-1] > current - 3600},
                )
        return None

    def _get_redis(self):
        if not settings.redis_url:
            return None
        if self._redis is None or self._redis_url != settings.redis_url:
            from redis import Redis

            self._redis = Redis.from_url(
                settings.redis_url, socket_connect_timeout=0.5,
                socket_timeout=0.5, decode_responses=True,
            )
            self._redis_url = settings.redis_url
        return self._redis

    def _check_redis(self, client_ip: str, path: str):
        rule = self.rule_for(path)
        client = self._get_redis()
        if rule is None or client is None:
            return None
        limit, window = rule
        # Hash identifiers so Redis keys do not store raw client IP addresses.
        identity = sha256(f"{client_ip}|{path}".encode()).hexdigest()
        allowed, retry_after = client.eval(
            self._REDIS_SCRIPT, 1, f"shopassist:rate-limit:{identity}",
            window * 1000, limit, f"{monotonic()}:{uuid4().hex}",
        )
        return None if int(allowed) else int(retry_after)

    def _check_with_fallback(self, client_ip: str, path: str):
        try:
            retry_after = self._check_redis(client_ip, path)
            if settings.redis_url:
                return retry_after
        except Exception:
            # Keep authentication and checkout available during a cache outage;
            # degraded readiness exposes that shared limiting is unavailable.
            pass
        return self.check(client_ip, path)

    async def _check(self, client_ip: str, path: str):
        if not settings.redis_url:
            return self.check(client_ip, path)
        return await run_in_threadpool(self._check_with_fallback, client_ip, path)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if self.rule_for(path) is None:
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
        retry_after = await self._check(client_ip, path)
        if retry_after is None:
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {"detail": "Too many requests. Please wait before trying again."},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
        await response(scope, receive, send)
