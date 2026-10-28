import pytest


@pytest.fixture(autouse=True)
def _legacy_shared_token_mode(monkeypatch, request):
    """Most tests exercise the engine with the legacy single-token mode (identity from X-Actor).
    tests/test_auth.py covers operator authentication, which is the default in deployment."""
    if "test_auth" not in request.node.nodeid:
        monkeypatch.setenv("SENTINEL_AUTH_MODE", "shared_token")
