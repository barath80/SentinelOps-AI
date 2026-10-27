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
    for word in ("release_regression", "payment_provider_timeout", "slow_dependency", "traffic_surge", "label", "decoy", "fault"):
        assert word not in text


def test_features_are_complete_finite_and_label_free():
    for label in CLASSES:
        feats, rule = extract(generate(label, 11, STANDARD).events)
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
