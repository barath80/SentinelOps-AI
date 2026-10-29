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
  python -m campaign.evaluate --recompute-from sqlite:///path/to/sentinel.db

--recompute-from reads a SentinelOps database directly and rebuilds each labelled incident's features
from its stored events with the CURRENT feature code, then scores the current models. Use it to test
a newly trained model on real incidents recorded before it existed (their stored features and
shadow predictions are those of the model that was serving at the time).
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
ACTIONABLE = {"release_regression", "payment_provider_timeout", "slow_dependency", "db_pool_exhaustion",
              "cache_unavailable", "resource_saturation", "retry_storm"}
# Where each cause's failure starts in the propagation graph (same mapping as the benchmark).
ORIGIN = {"release_regression": "service-code", "slow_dependency": "postgres", "db_pool_exhaustion": "postgres-pool",
          "cache_unavailable": "cache", "payment_provider_timeout": "payment-provider", "retry_storm": "payment-provider",
          "resource_saturation": "compute"}
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


def recompute(db_url: str) -> tuple[list[dict], list[str]]:
    """Labelled incidents from a SentinelOps database, rebuilt from stored events with the current code.
    Returns (rows, ids of incidents that could not be rebuilt)."""
    from datetime import timezone

    from sqlalchemy import select

    from app.analysis import learned
    from app.analysis.diagnostics import investigated_answer, load_context
    from app.analysis.ml_features import features_for_candidate
    from app.db import IncidentLabelRow, IncidentRow, make_session_factory

    aware = lambda dt: dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    model = learned.load()
    out, skipped = [], []
    with make_session_factory(db_url, create_schema=False)() as s:
        for lab, inc in s.execute(select(IncidentLabelRow, IncidentRow).join(IncidentRow, IncidentRow.id == IncidentLabelRow.incident_id)):
            lookback = None
            if not (inc.summary or {}).get("analysis_window_seconds"):
                # Recorded before the window was stored: do not reach back past the previous incident,
                # whose fault traffic would otherwise count as this one's baseline. A heuristic: an
                # incident detected just after a sibling of the same fault may still not rebuild.
                prev = s.scalar(select(IncidentRow.detected_at).where(IncidentRow.tenant_id == inc.tenant_id,
                                                                      IncidentRow.detected_at < inc.detected_at)
                                .order_by(IncidentRow.detected_at.desc()))
                if prev is not None:
                    lookback = min(900.0, (aware(inc.detected_at) - aware(prev)).total_seconds())
            ctx = load_context(s, inc, lookback_seconds=lookback)
            if ctx is None:
                skipped.append(inc.id)
                continue
            feats = features_for_candidate(ctx.candidate, ctx.samples, ctx.features, ctx.timeouts, ctx.spans)
            summary = inc.summary or {}
            out.append({"incident_id": inc.id, "label": lab.label, "features": feats, "rule_answer": summary.get("rule_answer"),
                        "investigated_answer": investigated_answer(s, inc),
                        "containment": ((summary.get("propagation") or {}).get("earliest_containment") or {}).get("node"),
                        "shadow_prediction": model.predict(feats)["prediction"] if model else None,
                        "shadow_version": model.version if model else None})
    return out, skipped


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
    path = ROOT / "models" / "root_cause_v2.joblib"
    if not path.exists():
        return None
    import joblib
    import numpy as np

    art = joblib.load(path)  # our own artifact, produced by notebooks/root_cause_model.ipynb
    if not rows or any(f not in r["features"] for r in rows for f in art["features"]):
        return None  # nothing to score, or rows recorded with an older feature set
    X = np.array([[r["features"][f] for f in art["features"]] for r in rows])
    proba = art["model"].predict_proba(X)
    classes = list(art["model"].classes_)
    return [classes[i] if p[i] >= art["tau"] else "unknown" for p, i in zip(proba, proba.argmax(axis=1))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sentinel")
    ap.add_argument("--file")
    ap.add_argument("--recompute-from", help="SentinelOps database URL: recompute features with the current code")
    ap.add_argument("--out", default="campaign/results")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    skipped: list[str] = []
    if args.recompute_from:
        rows, skipped = recompute(args.recompute_from)
    elif args.file:
        rows = json.loads(Path(args.file).read_text(encoding="utf-8"))
    else:
        rows = fetch(args.sentinel, os.environ["SENTINEL_TOKEN"])
        (out / "real_labelled.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")

    usable = [r for r in rows if r.get("features")]
    truth = [r["label"] for r in usable]
    systems = {"rule engine": [r.get("rule_answer") or "unknown" for r in usable]}
    investigated = [r for r in usable if r.get("investigated_answer")]
    if len(investigated) == len(usable):
        systems["rules + investigation"] = [r["investigated_answer"] for r in usable]
    systems["shadow model (served)"] = [r.get("shadow_prediction") or "unknown" for r in usable]
    full = full_model_predictions(usable)
    if full is not None:
        systems["full model (local)"] = full

    lines = ["# Evaluation on real labelled incidents", "",
             f"{len(rows)} labelled incidents, {len(usable)} with stored features"
             + (f"; {len(skipped)} could not be rebuilt from stored events and are not scored ({', '.join(skipped)})" if skipped else "")
             + ". Labels by distribution: "
             + ", ".join(f"{k} {v}" for k, v in Counter(truth).most_common()) + ".", "",
             "| System | n | Exact accuracy | Decision accuracy | Incorrect intervention | Missed actionable |",
             "| --- | --- | --- | --- | --- | --- |"]
    for name, pred in systems.items():
        s = scores(truth, pred)
        if s["n"]:
            lines.append(f"| {name} | {s['n']} | {s['exact_accuracy']:.1%} | {s['decision_accuracy']:.1%} | "
                         f"{s['incorrect_intervention_rate']:.1%} | {s['missed_actionable_rate']:.1%} |")
    scored = [r for r in usable if r["label"] in ORIGIN and r.get("containment")]
    if scored:
        ok = sum(r["containment"] == ORIGIN[r["label"]] for r in scored)
        lines += ["", f"Earliest containment point equals the true origin in {ok}/{len(scored)} actionable incidents."]
    lines += ["", "## Per incident", "", "| Truth | Rules | Investigated | Contain at | Shadow | " + ("Full model |" if full is not None else ""),
              "| --- | --- | --- | --- | --- | " + ("--- |" if full is not None else "")]
    for i, r in enumerate(usable):
        lines.append(f"| {r['label']} | {systems['rule engine'][i]} | {r.get('investigated_answer') or '-'} | {r.get('containment') or '-'} | "
                     f"{systems['shadow model (served)'][i]} | " + (f"{full[i]} |" if full is not None else ""))
    lines += ["", "Small samples give wide uncertainty: treat these numbers as a first look, not a result."]
    report = "\n".join(lines)
    (out / "real_evaluation.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
