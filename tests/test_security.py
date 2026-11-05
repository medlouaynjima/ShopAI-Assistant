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


def test_cors_configuration_uses_explicit_origins():
    from src.config import settings

    assert settings.cors_allowed_origins
    assert "*" not in settings.cors_allowed_origins
