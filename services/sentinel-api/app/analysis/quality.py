"""Telemetry quality: is the data itself trustworthy enough to diagnose from? (scenario S11)

A clock running ahead is detectable from the data alone: an event cannot legitimately be
timestamped after the moment it arrived. Such events are kept (rejecting them would hide the
problem) but they fall outside "now" and so outside detection, and any timeline built from them
is wrong. This module reports it instead of letting it silently distort an analysis.

Lag in the other direction (old timestamps) is NOT flagged: it is indistinguishable from
legitimate backfill or buffered delivery without per-source knowledge of how data is sent.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone

SKEW_TOLERANCE_S = 30.0  # normal clock drift and transport jitter stay well inside this
MIN_SKEWED_EVENTS = 5


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def assess(rows) -> dict:
    """rows: EventRow-like objects. Returns {'status': ok|clock_skew, 'services': {...}, 'warnings': [...]}."""
    by_service: dict[str, list] = {}
    for r in rows:
        by_service.setdefault(r.service_name, []).append(r)
    services, warnings = {}, []
    for svc, items in sorted(by_service.items()):
        ahead = [(_aware(r.event_time) - _aware(r.ingest_time)).total_seconds() for r in items]
        skewed = [a for a in ahead if a > SKEW_TOLERANCE_S]
        info = {"events": len(items), "ahead_of_arrival": len(skewed),
                "median_ahead_seconds": round(statistics.median(skewed), 1) if skewed else 0.0}
        services[svc] = info
        if len(skewed) >= MIN_SKEWED_EVENTS:
            warnings.append({"service": svc, "kind": "clock_ahead", "events": len(skewed),
                             "median_seconds": info["median_ahead_seconds"],
                             "message": (f"{len(skewed)} events from {svc} are timestamped a median {info['median_ahead_seconds']:.0f} s "
                                         "after they arrived: its clock is running ahead. Its recent events fall outside "
                                         "the analysis window and its timeline cannot be trusted.")})
    return {"status": "clock_skew" if warnings else "ok", "tolerance_seconds": SKEW_TOLERANCE_S,
            "services": services, "warnings": warnings,
            "not_checked": "old timestamps (indistinguishable from backfill or buffered delivery)"}
