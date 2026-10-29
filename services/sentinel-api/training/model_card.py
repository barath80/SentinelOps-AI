"""Render models/MODEL_CARD.md from models/root_cause_v2.json (so the card always matches the run).

Usage: python -m training.model_card
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def main() -> None:
    m = json.loads((ROOT / "models" / "root_cause_v2.json").read_text())
    tr = m["test_results"]
    rows = []
    for test in ("A: in-distribution", "B: shifted"):
        for system in ("learned model", "rule engine"):
            r = tr[f"{test} | {system}"]
            rows.append(f"| {test} | {system} | {r['n']} | {pct(r['exact_accuracy'])} | {r['macro_f1']:.3f} | {pct(r['decision_accuracy'])} | "
                        f"{pct(r['incorrect_intervention_rate'])} | {pct(r['missed_actionable_rate'])} |")
    cv = "\n".join(f"| {c['model']} | {c['cv_macro_f1']:.3f} ± {c['cv_std']:.3f} |" for c in m["cv"])
    cal = "\n".join(f"| {c['probabilities']} | {c['log_loss']:.4f} | {c['brier']:.4f} |" for c in m["calibration_comparison"])
    d = m["data"]
    text = f"""# Model card: {m['version']}

**What it does.** Given an incident raised by the SentinelOps detector, predicts the cause: {", ".join(f"`{c}`" for c in m['classes'])}.
It names a cause only when its calibrated probability is at least **τ = {m['tau']}** (chosen for {pct(m['target_precision'])} precision on validation); otherwise it answers `unknown` and no recovery action is recommended.

**Status.** Research artifact trained on simulated incidents. A compact logistic-regression version (`app/models/root_cause_serving_v2.json`) runs in the API in **shadow mode**: its prediction is recorded next to the rule engine's and never changes a ranking, a recommendation or an action. Version 2 replaces v1 (log features only, which could not tell pool exhaustion, a dead cache or CPU saturation from a slow query); v1's files are kept for reproducibility.

## Training

- **Algorithm:** {m['algorithm']} {m['best_params']}, selected by stratified 5-fold cross-validated macro-F1; probabilities calibrated with {m['calibration']}.
- **Data:** `{d['generator']}` (parametric simulator: random traffic, noise, cold starts, missing logs, partial faults, decoy deployments, partial or absent request tracing). Train seeds {d['train_seeds']}, {d['train_rows']} detected incidents. Test A seeds {d['testA_seeds']} ({d['testA_rows']} incidents, same settings). Test B seeds {d['testB_seeds']} ({d['testB_rows']} incidents, shifted: sparser, noisier, more decoys and missing logs).
- **Features ({len(m['features'])}):** {", ".join(f"`{f}`" for f in m['features'])}. All computed from telemetry by the production detector; labels never enter the features (tested).
- **Environment:** Python {m['environment']['python']}, scikit-learn {m['environment']['sklearn']}, NumPy {m['environment']['numpy']}.

| Model | CV macro-F1 |
| --- | --- |
{cv}

| Probabilities | Validation log loss | Brier |
| --- | --- | --- |
{cal}

## Results on held-out data

`decision accuracy` counts declining to name an actionable cause as correct when the truth is `unknown` or `no_fault`. `incorrect intervention` = named an actionable cause that is wrong (it would trigger the wrong recovery action). `missed actionable` = a fixable cause was not named.

| Test set | System | n | Exact accuracy | Macro-F1 | Decision accuracy | Incorrect intervention | Missed actionable |
| --- | --- | --- | --- | --- | --- | --- | --- |
{chr(10).join(rows)}

The rule engine here runs without its falsification step and cannot output `no_fault`, which partly explains its lower exact accuracy.

## Real incidents

See `docs/real-incidents.md` for this model scored on labelled incidents recorded from the real application (`python -m campaign.evaluate --recompute-from <database url>`), which it never saw in training.

## Limits

- **Simulated data only.** The simulator and the features were written by the same author, so the model partly learns the simulator's design. Test B measures robustness to one kind of shift, not real-world performance.
- **Abstention trades coverage for safety.** The strict threshold keeps wrong interventions low but raises missed actionable incidents, most visibly on the shifted set.
- **Traces decide the new causes.** Without traces the trace features are 0, and pool exhaustion, cache outages and CPU saturation fall back to looking like a slow dependency; the model should then abstain or answer from log signals only.
- **Weak class:** `no_fault` has few training rows (detector false alarms on healthy traffic) and is the least accurate class.
- **No evidence trail of its own.** A prediction is not an explanation. Intended use is alongside the evidence ledger and falsification tests, not instead of them.

## Reproduce

```
cd services/sentinel-api
python notebooks/build_notebook.py
python -m jupyter nbconvert --to notebook --execute --inplace notebooks/root_cause_model.ipynb
# or, without nbconvert:  python -c "import nbformat; from nbclient import NotebookClient as C; p='notebooks/root_cause_model.ipynb'; nb=nbformat.read(p, 4); C(nb, timeout=7200, resources={{'metadata': {{'path': 'notebooks'}}}}).execute(); nbformat.write(nb, p)"
python -m training.model_card
```
The notebook regenerates the data from fixed seeds and writes `models/root_cause_v2.joblib` (git-ignored, ~170 MB) and `models/root_cause_v2.json`.
"""
    (ROOT / "models" / "MODEL_CARD.md").write_text(text, encoding="utf-8")
    print("wrote", ROOT / "models" / "MODEL_CARD.md")


if __name__ == "__main__":
    main()
