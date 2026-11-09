"""Redis integration check for limits shared across middleware instances."""
from hashlib import sha256
from uuid import uuid4

import pytest

from src.config import settings
from src.security import RateLimitMiddleware


def test_rate_limit_is_shared_by_independent_middleware_instances():
    if not settings.redis_url:
        pytest.skip("Set REDIS_URL to run the shared Redis rate-limit integration check.")

    from redis import Redis
    from redis.exceptions import RedisError

    client_ip = f"integration-{uuid4().hex}"
    path = "/api/v1/auth/login"
    identity = sha256(f"{client_ip}|{path}".encode()).hexdigest()
    key = f"shopassist:rate-limit:{identity}"
    client = Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
    try:
        client.ping()
    except RedisError as exc:
        client.close()
        pytest.skip(f"Configured Redis is not reachable in this environment: {exc}")
    client.delete(key)
    first = RateLimitMiddleware(lambda scope, receive, send: None)
    second = RateLimitMiddleware(lambda scope, receive, send: None)

    try:
        for attempt in range(8):
            limiter = first if attempt % 2 == 0 else second
            assert limiter._check_redis(client_ip, path) is None
        assert second._check_redis(client_ip, path) >= 1
    finally:
        client.delete(key)
        client.close()
