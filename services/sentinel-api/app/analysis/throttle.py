"""Throttling signal: are requests being rejected with 429 Too Many Requests?

A 429 is a client error, so the 5xx detector ignores it by design, yet a burst of them means users
are being turned away (an upstream quota, the shop's own rate limiter, or a client retrying too
fast). This reports it per route so the team is told, with the counts as evidence.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .detect import Sample

MIN_THROTTLED = 5
MIN_SHARE = 0.2
WINDOW_S = 120


def assess(samples: list[Sample], as_of: datetime) -> dict:
    start = as_of - timedelta(seconds=WINDOW_S)
    routes: dict[str, list[Sample]] = {}
    for s in samples:
        if start <= s.time <= as_of and not s.route.startswith("/api/admin"):
            routes.setdefault(s.route, []).append(s)
    flagged = []
    for route, xs in sorted(routes.items()):
        hits = [s for s in xs if s.status == 429]
        share = len(hits) / len(xs)
        if len(hits) >= MIN_THROTTLED and share >= MIN_SHARE:
            flagged.append({"route": route, "throttled": len(hits), "requests": len(xs), "share": round(share, 3),
                            "evidence": [s.event_id for s in hits[:5]],
                            "message": f"{len(hits)} of {len(xs)} requests to {route} ({share:.0%}) were rejected with 429 "
                                       f"in the last {WINDOW_S} s"})
    return {"status": "throttled" if flagged else "ok", "window_seconds": WINDOW_S, "routes": flagged}
