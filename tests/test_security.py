from src.security import RateLimitMiddleware


def test_login_rate_limit_is_per_ip_and_resets_after_window():
    limiter = RateLimitMiddleware(lambda scope, receive, send: None)
    path = "/api/v1/auth/login"
    for i in range(8):
        assert limiter.check("192.0.2.1", path, now=float(i)) is None
    assert limiter.check("192.0.2.1", path, now=8.0) == 292
    assert limiter.check("192.0.2.2", path, now=8.0) is None
    assert limiter.check("192.0.2.1", path, now=300.0) is None


def test_chat_and_guest_chat_have_separate_limits():
    limiter = RateLimitMiddleware(lambda scope, receive, send: None)
    assert limiter.check("192.0.2.1", "/api/v1/chat", now=1) is None
    assert limiter.check("192.0.2.1", "/api/v1/chat/guest", now=1) is None


def test_unlisted_paths_are_not_rate_limited():
    limiter = RateLimitMiddleware(lambda scope, receive, send: None)
    assert limiter.check("192.0.2.1", "/api/v1/products", now=1) is None


def test_redis_limiter_uses_hashed_identity_and_atomic_window(monkeypatch):
    from src.config import settings

    calls = []

    class FakeRedis:
        def eval(self, script, key_count, key, window_ms, limit, member):
            calls.append((script, key_count, key, window_ms, limit, member))
            return [0, 17]

    limiter = RateLimitMiddleware(lambda scope, receive, send: None)
    limiter._redis = FakeRedis()
    limiter._redis_url = "redis://test"
    monkeypatch.setattr(settings, "redis_url", "redis://test")

    assert limiter._check_redis("192.0.2.1", "/api/v1/auth/login") == 17
    script, key_count, key, window_ms, limit, member = calls[0]
    assert "ZREMRANGEBYSCORE" in script and "redis.call('TIME')" in script
    assert key_count == 1
    assert key.startswith("shopassist:rate-limit:")
    assert "192.0.2.1" not in key
    assert (window_ms, limit) == (300_000, 8)
    assert member


def test_redis_failure_falls_back_to_local_limit(monkeypatch):
    from src.config import settings

    limiter = RateLimitMiddleware(lambda scope, receive, send: None)
    monkeypatch.setattr(settings, "redis_url", "redis://unavailable")
    monkeypatch.setattr(limiter, "_check_redis", lambda client_ip, path: (_ for _ in ()).throw(ConnectionError()))
    local_calls = []
    monkeypatch.setattr(limiter, "check", lambda ip, path: local_calls.append((ip, path)) or None)

    assert limiter._check_with_fallback("192.0.2.8", "/api/v1/auth/login") is None
    assert local_calls == [("192.0.2.8", "/api/v1/auth/login")]


def test_cors_configuration_uses_explicit_origins():
    from src.config import settings

    assert settings.cors_allowed_origins
    assert "*" not in settings.cors_allowed_origins
