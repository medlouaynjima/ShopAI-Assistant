"""Small, process-local limits for sensitive and expensive API endpoints."""
from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from starlette.responses import JSONResponse


class RateLimitMiddleware:
    """Apply per-IP sliding-window limits without trusting proxy headers."""

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
        retry_after = self.check(client_ip, path)
        if retry_after is None:
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {"detail": "Too many requests. Please wait before trying again."},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
        await response(scope, receive, send)
