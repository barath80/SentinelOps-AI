import json

import httpx

from benchmark.metrics import aggregate, score_run, wilson
from benchmark.report import render
from benchmark.runner import run_benchmark
from benchmark.scenarios import BY_ID, SCENARIOS, make_events, make_post_action_events, truly_recovered
from benchmark.systems import SystemResult, llm_only, summarize_for_llm


def test_systems_never_see_ground_truth():
    """Telemetry must not name the scenario, the fault, or the answer."""
    forbidden = ["scenario", "fault", "decoy", "probe", "ground", "truth"]
    for s in SCENARIOS:
        for seed in (0, 1):
            text = json.dumps(make_events(s, seed) + make_post_action_events(s, seed, "rollback_release")).lower()
            for word in forbidden + [s.name.lower(), s.id.lower() + "-", f"'{s.id.lower()}'", f'"{s.id.lower()}"']:
                assert word not in text, f"{s.id} leaks {word!r}"
            summary = summarize_for_llm(make_events(s, seed)).lower()
            assert not any(w in summary for w in forbidden)


def test_generators_are_deterministic_and_seeds_differ():
    s = BY_ID["S05"]
    assert make_events(s, 3) == make_events(s, 3)
    assert make_events(s, 3) != make_events(s, 4)


def test_world_model_recovery():
    assert truly_recovered(BY_ID["S01"], "rollback_release")
    assert not truly_recovered(BY_ID["S01"], "restore_payment_simulator")  # executed but wrong
    assert not truly_recovered(BY_ID["S01"], None)
    assert not truly_recovered(BY_ID["S10"], "rollback_release")  # only half of two faults fixed
    assert truly_recovered(BY_ID["S10"], "apply_query_fix") is False
    assert not truly_recovered(BY_ID["P1"], "rollback_release")  # decoy: nothing catalogued fixes it


def test_wilson_interval():
    lo, hi = wilson(5, 10)
    assert 0.23 < lo < 0.24 and 0.76 < hi < 0.77
    assert wilson(0, 0) == (0.0, 0.0)
    assert wilson(10, 10)[1] == 1.0 and wilson(10, 10)[0] > 0.6


def test_scoring_rules():
    decoy = score_run("x", BY_ID["S09"], 0, SystemResult(detected=True, cause="release_regression",
                                                         action="rollback_release", claims_success=True))
    assert decoy["false_diagnosis"] and decoy["incorrect_intervention"] and decoy["false_success"]
    assert not decoy["top1_correct"] and not decoy["verified_recovery"]

    good = score_run("x", BY_ID["S01"], 0, SystemResult(detected=True, cause="release_regression",
                                                        action="rollback_release", claims_success=True))
    assert good["top1_correct"] and good["verified_recovery"] and not good["false_success"]

    abstain = score_run("x", BY_ID["S08"], 0, SystemResult(detected=True, cause=None))
    assert abstain["correct_abstention"] and not abstain["false_diagnosis"]
    assert score_run("x", BY_ID["S01"], 0, SystemResult(detected=True, cause=None))["wrongful_abstention"]

    miss = score_run("x", BY_ID["S01"], 0, SystemResult(detected=False))
    assert miss["missed_detection"]
    alarm = score_run("x", BY_ID["S00"], 0, SystemResult(detected=True))
    assert alarm["false_alarm"]

    partial = score_run("x", BY_ID["S10"], 0, SystemResult(detected=True, cause="release_regression",
                                                           action="rollback_release", claims_success=True))
    assert partial["top1_correct"] and not partial["complete_diagnosis"] and partial["false_success"]


def test_aggregate_counts():
    rows = [score_run("x", BY_ID["S01"], i, SystemResult(detected=True, cause="release_regression",
                                                         action="rollback_release", claims_success=True)) for i in range(4)]
    agg = aggregate(rows)["x"]["rates"]
    assert agg["top1_accuracy"]["k"] == 4 and agg["top1_accuracy"]["n"] == 4
    assert agg["false_alarm_rate"]["n"] == 0 and agg["false_alarm_rate"]["rate"] is None


def test_llm_baseline_is_skipped_without_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm_only(make_events(BY_ID["S01"], 0), None) is None


def test_llm_baseline_parses_a_response_and_counts_tokens():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "S01" not in body["messages"][0]["content"] and "fault" not in body["messages"][0]["content"].lower()
        return httpx.Response(200, json={"content": [{"type": "text", "text": 'Sure. {"cause": "release_regression", "incident": true}'}],
                                         "usage": {"input_tokens": 300, "output_tokens": 12}})

    r = llm_only(make_events(BY_ID["S01"], 0), None, transport=httpx.MockTransport(handler))
    assert r.cause == "release_regression" and r.llm_tokens == 312 and r.action == "rollback_release"
    assert r.claims_success is True  # no verification step: the baseline treats execution as success


def test_llm_baseline_tolerates_garbage_and_unknown_causes():
    garbage = httpx.MockTransport(lambda req: httpx.Response(200, json={"content": [{"type": "text", "text": "I think it is the network"}], "usage": {}}))
    r = llm_only(make_events(BY_ID["S01"], 0), None, transport=garbage)
    assert r.cause is None and r.action is None
    invented = httpx.MockTransport(lambda req: httpx.Response(200, json={"content": [{"type": "text", "text": '{"cause": "dns_outage", "incident": true}'}], "usage": {}}))
    assert llm_only(make_events(BY_ID["S01"], 0), None, transport=invented).cause is None  # not on the allowed list


def test_end_to_end_small_run_and_report():
    result = run_benchmark(seeds=1, systems=["alert_correlator", "sentinel", "sentinel_falsify"], scenarios=["S01", "S09", "P1"])
    by = {(r["scenario"], r["system"]): r for r in result["runs"]}
    assert by[("S09", "alert_correlator")]["cause"] == "release_regression"   # fooled by the decoy deployment
    assert by[("S09", "sentinel")]["cause"] == "payment_provider_timeout"
    assert by[("P1", "sentinel")]["incorrect_intervention"] is True           # leader not tested: wrong rollback
    assert by[("P1", "sentinel_falsify")]["cause"] is None                    # falsification stops it
    assert by[("P1", "sentinel_falsify")]["incorrect_intervention"] is False
    assert by[("S01", "sentinel_falsify")]["verification"] == "pass"
    assert by[("S01", "alert_correlator")]["claims_success"] is True and by[("S01", "alert_correlator")]["verification"] is None
    text = render(result)
    assert "Read this first" in text and "written by the same author" in text and "ANTHROPIC_API_KEY" in text
