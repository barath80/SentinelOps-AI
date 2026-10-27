"""Evaluate the rule engine and the learned models on REAL labelled incidents.

Pulls GET /api/v1/training/labelled from a SentinelOps API (or reads a saved JSON file), then scores:
  - the rule engine's answer recorded at analysis time
  - the shadow model's prediction recorded at analysis time
  - the full calibrated model (models/root_cause_v1.joblib), if it exists locally
with the same metrics as the notebook. Writes the export and a markdown report.

Usage:
  set SENTINEL_TOKEN=...
  python -m campaign.evaluate --sentinel https://sentinel.example --out campaign/results
  python -m campaign.evaluate --file campaign/results/real_labelled.json
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
ACTIONABLE = {"release_regression", "payment_provider_timeout", "slow_dependency"}
QUIET = {"unknown", "no_fault"}


def fetch(base: str, token: str) -> list[dict]:
    last = None
    for attempt in range(5):
        try:
            r = httpx.get(base.rstrip("/") + "/api/v1/training/labelled", headers={"Authorization": f"Bearer {token}"}, timeout=60)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"could not fetch labelled incidents: {last}")


def scores(truth: list[str], pred: list[str]) -> dict:
    n = len(truth)
    if not n:
        return {"n": 0}
    exact = sum(t == p for t, p in zip(truth, pred))
    decision = sum(t == p or (t in QUIET and p in QUIET) for t, p in zip(truth, pred))
    wrong_action = sum(p in ACTIONABLE and p != t for t, p in zip(truth, pred))
    missed = sum(t in ACTIONABLE and p not in ACTIONABLE for t, p in zip(truth, pred))
    return {"n": n, "exact_accuracy": exact / n, "decision_accuracy": decision / n,
            "incorrect_intervention_rate": wrong_action / n, "missed_actionable_rate": missed / n}


def full_model_predictions(rows: list[dict]) -> list[str] | None:
    path = ROOT / "models" / "root_cause_v1.joblib"
    if not path.exists():
        return None
    import joblib
    import numpy as np

    art = joblib.load(path)  # our own artifact, produced by notebooks/root_cause_model.ipynb
    X = np.array([[r["features"][f] for f in art["features"]] for r in rows])
    proba = art["model"].predict_proba(X)
    classes = list(art["model"].classes_)
    return [classes[i] if p[i] >= art["tau"] else "unknown" for p, i in zip(proba, proba.argmax(axis=1))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sentinel")
    ap.add_argument("--file")
    ap.add_argument("--out", default="campaign/results")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.file:
        rows = json.loads(Path(args.file).read_text(encoding="utf-8"))
    else:
        rows = fetch(args.sentinel, os.environ["SENTINEL_TOKEN"])
        (out / "real_labelled.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")

    usable = [r for r in rows if r.get("features")]
    truth = [r["label"] for r in usable]
    systems = {"rule engine": [r.get("rule_answer") or "unknown" for r in usable],
               "shadow model (served)": [r.get("shadow_prediction") or "unknown" for r in usable]}
    full = full_model_predictions(usable)
    if full is not None:
        systems["full model (local)"] = full

    lines = ["# Evaluation on real labelled incidents", "",
             f"{len(rows)} labelled incidents, {len(usable)} with stored features. Labels by distribution: "
             + ", ".join(f"{k} {v}" for k, v in Counter(truth).most_common()) + ".", "",
             "| System | n | Exact accuracy | Decision accuracy | Incorrect intervention | Missed actionable |",
             "| --- | --- | --- | --- | --- | --- |"]
    for name, pred in systems.items():
        s = scores(truth, pred)
        if s["n"]:
            lines.append(f"| {name} | {s['n']} | {s['exact_accuracy']:.1%} | {s['decision_accuracy']:.1%} | "
                         f"{s['incorrect_intervention_rate']:.1%} | {s['missed_actionable_rate']:.1%} |")
    lines += ["", "## Per incident", "", "| Truth | Rules | Shadow | " + ("Full model |" if full is not None else ""),
              "| --- | --- | --- | " + ("--- |" if full is not None else "")]
    for i, r in enumerate(usable):
        lines.append(f"| {r['label']} | {systems['rule engine'][i]} | {systems['shadow model (served)'][i]} | "
                     + (f"{full[i]} |" if full is not None else ""))
    lines += ["", "Small samples give wide uncertainty: treat these numbers as a first look, not a result."]
    report = "\n".join(lines)
    (out / "real_evaluation.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
