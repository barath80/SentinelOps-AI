import json
import math

import pytest

from training.features import FEATURES, extract
from training.generator import CLASSES, SHIFTED, STANDARD, generate


def test_generator_is_deterministic_and_seeds_differ():
    a, b = generate("slow_dependency", 7), generate("slow_dependency", 7)
    assert a.events == b.events and a.params == b.params
    assert generate("slow_dependency", 8).events != a.events
    assert generate("slow_dependency", 7, SHIFTED).events != a.events


@pytest.mark.parametrize("label", CLASSES + ["none"])
def test_telemetry_never_contains_the_label(label):
    text = json.dumps(generate(label, 3).events).lower()
    for word in ("release_regression", "payment_provider_timeout", "slow_dependency", "traffic_surge", "db_pool_exhaustion",
                 "cache_unavailable", "resource_saturation", "retry_storm", "label", "decoy", "fault"):
        assert word not in text


def test_features_are_complete_finite_and_label_free():
    for label in CLASSES:
        feats, rule = next((r for r in (extract(generate(label, s, STANDARD).events) for s in range(11, 40)) if r[0]), (None, None))
        assert feats is not None and list(feats) == FEATURES
        assert all(isinstance(v, float) and math.isfinite(v) for v in feats.values())
        assert rule in CLASSES  # the rule engine answers a cause or "unknown"


def first_detected(label):
    for seed in range(50):
        feats, _ = extract(generate(label, seed).events)
        if feats is not None:
            return feats
    raise AssertionError(f"no {label} incident detected in 50 seeds")


def test_features_carry_the_expected_signals():
    rel, pay, slow = (first_detected(l) for l in ("release_regression", "payment_provider_timeout", "slow_dependency"))
    assert rel["version_changed"] == 1.0 and rel["fast_fail_ratio"] > 0.5
    assert pay["share_504"] > 0.5
    assert slow["latency_only"] == 1.0 and slow["log_p95_ratio"] > 0.5


def test_healthy_traffic_is_usually_not_an_incident():
    raised = sum(extract(generate("none", s).events)[0] is not None for s in range(40))
    assert raised <= 15  # the detector may false-alarm on noise, but not most of the time


def test_most_slow_incidents_are_still_detected_with_closed_loop_clients():
    detected = sum(extract(generate("slow_dependency", s).events)[0] is not None for s in range(60))
    assert detected >= 50


def first_traced(label):
    for seed in range(80):
        feats, _ = extract(generate(label, seed).events)
        if feats is not None and feats["trace_coverage"] > 0.5:
            return feats
    raise AssertionError(f"no traced {label} incident in 80 seeds")


def test_trace_features_separate_causes_that_look_alike_in_logs():
    """Pool exhaustion, a dead cache, CPU saturation and a slow query are all just "slow" in logs."""
    pool, cache, cpu, query = (first_traced(l) for l in ("db_pool_exhaustion", "cache_unavailable", "resource_saturation", "slow_dependency"))
    assert pool["pool_wait_share"] > 0.4 and pool["query_share"] < 0.2
    assert query["query_share"] > 0.4 and query["pool_wait_share"] < 0.1
    assert cache["cache_fail_share"] > 0.5
    assert cpu["cpu_share"] > 0.6 and pool["cpu_share"] < 0.3
    retry = first_traced("retry_storm")
    assert retry["payment_calls_per_request"] >= 2 and retry["payment_hang_share"] == 0.0
    assert first_traced("payment_provider_timeout")["payment_hang_share"] > 0.5


def test_untraced_incidents_get_zero_trace_features():
    from training.generator import Dist
    no_traces = Dist(**{**STANDARD.__dict__, "untraced_p": 1.0})
    feats, _ = extract(generate("db_pool_exhaustion", 1, no_traces).events)
    assert feats is not None and feats["trace_coverage"] == 0.0 and feats["pool_wait_share"] == 0.0


def test_v2_features_extend_v1_without_reordering():
    from app.analysis.ml_features import LOG_FEATURES, TRACE_FEATURES
    assert FEATURES[:len(LOG_FEATURES)] == LOG_FEATURES and FEATURES[len(LOG_FEATURES):] == TRACE_FEATURES
    assert len(LOG_FEATURES) == 17  # model v1 was trained on exactly these
