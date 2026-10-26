"""Anomaly detection and incident grouping over request events.

Deterministic on purpose: robust statistics (median/MAD, percentiles) and fixed thresholds,
no learned model. Every threshold is a named parameter in `DetectionConfig`.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

REQUEST_MESSAGES = {"request", "unhandled_exception"}


@dataclass(frozen=True)
class Sample:
    """One handled request, derived from a stored event."""

    event_id: str
    time: datetime
    route: str
    status: int
    duration_ms: float
    version: str | None
    message: str
    error: str | None = None
    request_id: str | None = None

    @property
    def is_error(self) -> bool:
        return self.status >= 500


@dataclass(frozen=True)
class DetectionConfig:
    recent_seconds: int = 120
    min_recent: int = 5
    min_baseline: int = 20
    error_rate_floor: float = 0.10  # recent error rate must exceed this ...
    error_rate_delta: float = 0.10  # ... and baseline error rate by this much
    latency_ratio: float = 2.0  # recent p95 must be this multiple of baseline p95 ...
    latency_min_delta_ms: float = 200.0  # ... and exceed it by at least this much
    mad_k: float = 5.0
    group_seconds: int = 120


@dataclass
class Anomaly:
    route: str
    kind: str  # "errors" | "latency"
    onset: datetime
    recent_n: int
    baseline_n: int
    recent_error_rate: float
    baseline_error_rate: float
    recent_p95_ms: float
    baseline_p95_ms: float | None
    bad_event_ids: list[str] = field(default_factory=list)


@dataclass
class IncidentCandidate:
    anomalies: list[Anomaly]
    onset: datetime
    recent_start: datetime
    as_of: datetime

    @property
    def routes(self) -> list[str]:
        return sorted({a.route for a in self.anomalies})


def percentile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("percentile of empty list")
    ordered = sorted(values)
    # nearest-rank: simple, deterministic, no interpolation surprises on small samples
    rank = max(1, -(-len(ordered) * q // 100))
    return ordered[int(rank) - 1]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def samples_from_rows(rows) -> list[Sample]:
    """Build request samples from EventRow-like objects; non-request events are skipped."""
    out: list[Sample] = []
    for r in rows:
        a = r.attributes or {}
        if a.get("message") not in REQUEST_MESSAGES or "route" not in a:
            continue
        status, duration = a.get("status"), a.get("duration_ms")
        if not isinstance(status, int) or not isinstance(duration, (int, float)):
            continue
        out.append(
            Sample(
                event_id=r.event_id,
                time=_aware(r.event_time),
                route=str(a["route"]),
                status=status,
                duration_ms=float(duration),
                version=a.get("version"),
                message=a["message"],
                error=a.get("error"),
                request_id=r.request_id,
            )
        )
    return sorted(out, key=lambda s: s.time)


def detect(samples: list[Sample], as_of: datetime, cfg: DetectionConfig = DetectionConfig()) -> list[Anomaly]:
    as_of = _aware(as_of)
    recent_start = as_of - timedelta(seconds=cfg.recent_seconds)
    by_route: dict[str, list[Sample]] = {}
    for s in samples:
        if s.time <= as_of:
            by_route.setdefault(s.route, []).append(s)

    anomalies: list[Anomaly] = []
    for route, items in by_route.items():
        if route.startswith("/api/admin"):
            continue
        base = [s for s in items if s.time < recent_start]
        recent = [s for s in items if s.time >= recent_start]
        if len(recent) < cfg.min_recent:
            continue
        have_baseline = len(base) >= cfg.min_baseline
        base_err = sum(s.is_error for s in base) / len(base) if base else 0.0
        rec_err = sum(s.is_error for s in recent) / len(recent)
        rec_p95 = percentile([s.duration_ms for s in recent], 95)
        base_p95 = percentile([s.duration_ms for s in base], 95) if have_baseline else None

        if rec_err >= max(cfg.error_rate_floor, base_err + cfg.error_rate_delta):
            bad = [s for s in recent if s.is_error]
            anomalies.append(_anomaly(route, "errors", bad, recent, base, rec_err, base_err, rec_p95, base_p95))
            continue

        if have_baseline and base_p95 is not None:
            durations = [s.duration_ms for s in base]
            med = statistics.median(durations)
            mad = statistics.median(abs(d - med) for d in durations) * 1.4826
            threshold = max(base_p95 * cfg.latency_ratio, base_p95 + cfg.mad_k * mad)
            if rec_p95 >= threshold and rec_p95 - base_p95 >= cfg.latency_min_delta_ms:
                bad = [s for s in recent if s.duration_ms >= threshold]
                anomalies.append(_anomaly(route, "latency", bad, recent, base, rec_err, base_err, rec_p95, base_p95))
    return anomalies


def _anomaly(route, kind, bad, recent, base, rec_err, base_err, rec_p95, base_p95) -> Anomaly:
    onset = min(s.time for s in bad) if bad else min(s.time for s in recent)
    return Anomaly(
        route=route, kind=kind, onset=onset, recent_n=len(recent), baseline_n=len(base),
        recent_error_rate=rec_err, baseline_error_rate=base_err,
        recent_p95_ms=rec_p95, baseline_p95_ms=base_p95,
        bad_event_ids=[s.event_id for s in bad[:20]],
    )


def group(anomalies: list[Anomaly], as_of: datetime, cfg: DetectionConfig = DetectionConfig()) -> list[IncidentCandidate]:
    """Anomalies whose onsets are within `group_seconds` of each other form one incident."""
    as_of = _aware(as_of)
    recent_start = as_of - timedelta(seconds=cfg.recent_seconds)
    groups: list[list[Anomaly]] = []
    for a in sorted(anomalies, key=lambda x: x.onset):
        if groups and a.onset - groups[-1][0].onset <= timedelta(seconds=cfg.group_seconds):
            groups[-1].append(a)
        else:
            groups.append([a])
    return [IncidentCandidate(g, min(a.onset for a in g), recent_start, as_of) for g in groups]
