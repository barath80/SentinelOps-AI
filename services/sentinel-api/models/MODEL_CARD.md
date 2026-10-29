# Model card: root-cause-v2

**What it does.** Given an incident raised by the SentinelOps detector, predicts the cause: `cache_unavailable`, `db_pool_exhaustion`, `no_fault`, `payment_provider_timeout`, `release_regression`, `resource_saturation`, `retry_storm`, `slow_dependency`, `traffic_surge`, `unknown`.
It names a cause only when its calibrated probability is at least **τ = 0.87** (chosen for 99.0% precision on validation); otherwise it answers `unknown` and no recovery action is recommended.

**Status.** Research artifact trained on simulated incidents. A compact logistic-regression version (`app/models/root_cause_serving_v2.json`) runs in the API in **shadow mode**: its prediction is recorded next to the rule engine's and never changes a ranking, a recommendation or an action. Version 2 replaces v1 (log features only, which could not tell pool exhaustion, a dead cache or CPU saturation from a slow query); v1's files are kept for reproducibility.

## Training

- **Algorithm:** random_forest {'max_depth': None, 'min_samples_leaf': 1}, selected by stratified 5-fold cross-validated macro-F1; probabilities calibrated with sigmoid, 5-fold.
- **Data:** `training/generator.py` (parametric simulator: random traffic, noise, cold starts, missing logs, partial faults, decoy deployments, partial or absent request tracing). Train seeds [0, 1500], 12711 detected incidents. Test A seeds [100000, 100400] (3405 incidents, same settings). Test B seeds [200000, 200400] (3074 incidents, shifted: sparser, noisier, more decoys and missing logs).
- **Features (25):** `err_recent`, `err_baseline`, `err_delta`, `log_p95_ratio`, `latency_only`, `version_changed`, `exception_ratio`, `fast_fail_ratio`, `timeout_match_share`, `timeouts_per_bad`, `share_504`, `log_volume_ratio`, `n_routes_affected`, `frac_routes_affected`, `n_unaffected`, `log_bad_median_ms`, `other_routes_log_p95_ratio`, `trace_coverage`, `pool_wait_share`, `query_share`, `cache_fail_share`, `cpu_share`, `payment_calls_per_request`, `payment_hang_share`, `retry_log_share`. All computed from telemetry by the production detector; labels never enter the features (tested).
- **Environment:** Python 3.12.10, scikit-learn 1.9.0, NumPy 2.2.6.

| Model | CV macro-F1 |
| --- | --- |
| random_forest | 0.939 ± 0.009 |
| gradient_boosting | 0.938 ± 0.005 |
| logistic_regression | 0.895 ± 0.008 |

| Probabilities | Validation log loss | Brier |
| --- | --- | --- |
| uncalibrated | 0.1327 | 0.0658 |
| isotonic | 0.1569 | 0.0625 |
| sigmoid | 0.1512 | 0.0670 |

## Results on held-out data

`decision accuracy` counts declining to name an actionable cause as correct when the truth is `unknown` or `no_fault`. `incorrect intervention` = named an actionable cause that is wrong (it would trigger the wrong recovery action). `missed actionable` = a fixable cause was not named.

| Test set | System | n | Exact accuracy | Macro-F1 | Decision accuracy | Incorrect intervention | Missed actionable |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A: in-distribution | learned model | 3405 | 91.4% | 0.910 | 92.1% | 0.6% | 7.2% |
| A: in-distribution | rule engine | 3405 | 47.0% | 0.391 | 48.0% | 21.3% | 27.5% |
| B: shifted | learned model | 3074 | 71.2% | 0.709 | 74.6% | 1.1% | 23.8% |
| B: shifted | rule engine | 3074 | 35.6% | 0.291 | 38.4% | 26.4% | 28.7% |

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
# or, without nbconvert:  python -c "import nbformat; from nbclient import NotebookClient as C; p='notebooks/root_cause_model.ipynb'; nb=nbformat.read(p, 4); C(nb, timeout=7200, resources={'metadata': {'path': 'notebooks'}}).execute(); nbformat.write(nb, p)"
python -m training.model_card
```
The notebook regenerates the data from fixed seeds and writes `models/root_cause_v2.joblib` (git-ignored, ~170 MB) and `models/root_cause_v2.json`.
