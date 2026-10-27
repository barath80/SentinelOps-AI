import pytest
from fastapi.testclient import TestClient

from app.analysis.learned import ServingModel, load
from app.analysis.ml_features import FEATURES
from app.config import Settings
from app.main import create_app
from tests.test_incidents import AUTH, NOW, baseline, recent, run

ALICE = {**AUTH, "X-Actor": "alice"}


def make(tmp_path, **kw):
    tmp_path.mkdir(parents=True, exist_ok=True)
    s = Settings(database_url=f"sqlite:///{tmp_path / 't.db'}", ingest_token="test-token", max_batch_events=2000, **kw)
    return TestClient(create_app(s))


def s01(client):
    [inc] = run(client, baseline() + recent(500, 1, version="v2", message="unhandled_exception"))
    return inc


def test_serving_model_ships_with_the_api():
    m = load()
    assert m is not None and m.features == FEATURES and "no_fault" in m.classes and 0 < m.tau < 1


def test_every_incident_gets_a_shadow_prediction_and_its_features(tmp_path):
    inc = s01(make(tmp_path))
    sh = inc["summary"]["shadow_model"]
    assert sh["mode"].startswith("shadow") and sh["rule_answer"] == "release_regression"
    assert sh["prediction"] in load().classes + ["unknown"] and abs(sum(sh["probabilities"].values()) - 1) < 1e-3
    assert sh["agrees_with_rules"] == (sh["prediction"] == "release_regression")
    assert list(inc["summary"]["model_features"]) == FEATURES


def test_shadow_mode_never_changes_the_engine_output(tmp_path):
    on = s01(make(tmp_path / "on"))
    off = s01(make(tmp_path / "off", shadow_model=False))
    strip = lambda inc: [(h["cause_key"], h["score"], h["status"]) for h in inc["hypotheses"]]
    assert strip(on) == strip(off) and on["assessment"] == off["assessment"]
    assert off["summary"]["shadow_model"] is None and list(off["summary"]["model_features"]) == FEATURES


def test_labelling_flow_export_and_report(tmp_path):
    client = make(tmp_path)
    inc = s01(client)
    url = f"/api/v1/incidents/{inc['id']}/label"
    assert client.post(url, json={"label": "release_regression"}, headers=AUTH).status_code == 400  # who labelled it?
    assert client.post(url, json={"label": "made_up_cause"}, headers=ALICE).status_code == 422
    assert client.post(url, json={"label": "release_regression"}).status_code == 401
    got = client.post(url, json={"label": "slow_dependency", "note": "first guess"}, headers=ALICE).json()
    assert got["label"]["label"] == "slow_dependency" and got["label"]["labeled_by"] == "alice"
    got = client.post(url, json={"label": "release_regression", "note": "confirmed by rollback"}, headers=ALICE).json()
    assert got["label"]["label"] == "release_regression"  # relabelling replaces the old label

    [row] = client.get("/api/v1/training/labelled", headers=AUTH).json()
    assert row["label"] == "release_regression" and row["rule_answer"] == "release_regression"
    assert list(row["features"]) == FEATURES and row["shadow_version"] == load().version

    rep = client.get("/api/v1/shadow/report", headers=AUTH).json()
    assert rep["with_shadow_prediction"] == 1 and rep["labelled"] == 1 and rep["rules_accuracy"] == 1.0
    assert rep["model_correct"] in (0, 1)


def test_predictor_abstains_below_its_threshold():
    spec = {"version": "t", "features": ["a"], "classes": ["x", "y"], "scaler_mean": [0.0], "scaler_scale": [1.0],
            "coef": [[1.0], [-1.0]], "intercept": [0.0, 0.0], "tau": 0.9}
    m = ServingModel(spec)
    assert m.predict({"a": 0.0})["prediction"] == "unknown" and m.predict({"a": 0.0})["abstained"]  # 50/50
    assert m.predict({"a": 5.0})["prediction"] == "x"
    with pytest.raises(ValueError):
        ServingModel({**spec, "coef": [[1.0]]})
