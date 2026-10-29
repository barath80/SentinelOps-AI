"""The client's address, for rate limits and the sign-in lockout.

Behind a reverse proxy the socket address is the proxy's. The proxy appends the address it saw to
X-Forwarded-For, so with N trusted proxy hops the client's address is the Nth entry from the RIGHT;
anything further left was sent by the client and can be forged. SENTINEL_TRUSTED_PROXY_HOPS=0 (the
default) ignores the header and uses the socket address. On Render set it to 1.
"""
from fastapi import Request


def client_address(request: Request, trusted_hops: int) -> str:
    if trusted_hops > 0:
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if len(hops) >= trusted_hops:
            return hops[-trusted_hops]
    return request.client.host if request.client else "-"
