"""Render models/MODEL_CARD.md from models/root_cause_v1.json (so the card always matches the run).

Usage: python -m training.model_card
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def main() -> None:
    m = json.loads((ROOT / "models" / "root_cause_v1.json").read_text())
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

**Status.** Research artifact trained on simulated incidents. Not wired into the API. Do not let it trigger recovery actions until it has been evaluated on labelled real incidents.

## Training

- **Algorithm:** {m['algorithm']} {m['best_params']}, selected by stratified 5-fold cross-validated macro-F1; probabilities calibrated with {m['calibration']}.
- **Data:** `{d['generator']}` (parametric simulator: random traffic, noise, cold starts, missing logs, partial faults, decoy deployments). Train seeds {d['train_seeds']}, {d['train_rows']} detected incidents. Test A seeds {d['testA_seeds']} ({d['testA_rows']} incidents, same settings). Test B seeds {d['testB_seeds']} ({d['testB_rows']} incidents, shifted: sparser, noisier, more decoys and missing logs).
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

## Limits

- **Simulated data only.** The simulator and the features were written by the same author, so the model partly learns the simulator's design. Test B measures robustness to one kind of shift, not real-world performance.
- **Abstention trades coverage for safety.** The strict threshold keeps wrong interventions low but raises missed actionable incidents, most visibly on the shifted set.
- **Weak class:** `no_fault` has few training rows (detector false alarms on healthy traffic) and is the least accurate class.
- **No evidence trail of its own.** A prediction is not an explanation. Intended use is alongside the evidence ledger and falsification tests, not instead of them.

## Reproduce

```
cd services/sentinel-api
python notebooks/build_notebook.py
python -m nbconvert --to notebook --execute --inplace notebooks/root_cause_model.ipynb
python -m training.model_card
```
The notebook regenerates the data from fixed seeds and writes `models/root_cause_v1.joblib` (git-ignored, ~29 MB) and `models/root_cause_v1.json`.
"""
    (ROOT / "models" / "MODEL_CARD.md").write_text(text, encoding="utf-8")
    print("wrote", ROOT / "models" / "MODEL_CARD.md")


if __name__ == "__main__":
    main()
