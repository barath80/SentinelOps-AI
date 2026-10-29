import pytest


@pytest.fixture(autouse=True)
def _test_settings(monkeypatch, request):
    """Most tests exercise the engine with the legacy single-token mode (identity from X-Actor).
    tests/test_auth.py covers operator authentication, which is the default in deployment.
    Request-rate limits are lifted except where tests/test_product.py checks them."""
    if "test_auth" not in request.node.nodeid:
        monkeypatch.setenv("SENTINEL_AUTH_MODE", "shared_token")
        monkeypatch.setenv("SENTINEL_ALLOW_INSECURE_SHARED_TOKEN", "true")
    if "rate_limit" not in request.node.name:
        monkeypatch.setenv("SENTINEL_RATE_LIMIT_PER_MINUTE", "100000")
        monkeypatch.setenv("SENTINEL_INGEST_RATE_LIMIT_PER_MINUTE", "100000")
        monkeypatch.setenv("SENTINEL_LOGIN_RATE_LIMIT_PER_MINUTE", "100000")
