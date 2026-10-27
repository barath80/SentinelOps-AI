# Model card: root-cause-v1

**What it does.** Given an incident raised by the SentinelOps detector, predicts the cause: `no_fault`, `payment_provider_timeout`, `release_regression`, `slow_dependency`, `traffic_surge`, `unknown`.
It names a cause only when its calibrated probability is at least **τ = 0.88** (chosen for 99.0% precision on validation); otherwise it answers `unknown` and no recovery action is recommended.

**Status.** Research artifact trained on simulated incidents. Not wired into the API. Do not let it trigger recovery actions until it has been evaluated on labelled real incidents.

## Training

- **Algorithm:** random_forest {'max_depth': 12, 'min_samples_leaf': 1}, selected by stratified 5-fold cross-validated macro-F1; probabilities calibrated with sigmoid, 5-fold.
- **Data:** `training/generator.py` (parametric simulator: random traffic, noise, cold starts, missing logs, partial faults, decoy deployments). Train seeds [0, 1500], 7178 detected incidents. Test A seeds [100000, 100400] (1925 incidents, same settings). Test B seeds [200000, 200400] (1965 incidents, shifted: sparser, noisier, more decoys and missing logs).
- **Features (17):** `err_recent`, `err_baseline`, `err_delta`, `log_p95_ratio`, `latency_only`, `version_changed`, `exception_ratio`, `fast_fail_ratio`, `timeout_match_share`, `timeouts_per_bad`, `share_504`, `log_volume_ratio`, `n_routes_affected`, `frac_routes_affected`, `n_unaffected`, `log_bad_median_ms`, `other_routes_log_p95_ratio`. All computed from telemetry by the production detector; labels never enter the features (tested).
- **Environment:** Python 3.12.10, scikit-learn 1.9.0, NumPy 2.2.6.

| Model | CV macro-F1 |
| --- | --- |
| random_forest | 0.955 ± 0.010 |
| gradient_boosting | 0.951 ± 0.006 |
| logistic_regression | 0.930 ± 0.007 |

| Probabilities | Validation log loss | Brier |
| --- | --- | --- |
| uncalibrated | 0.0612 | 0.0277 |
| isotonic | 0.1371 | 0.0249 |
| sigmoid | 0.0678 | 0.0267 |

## Results on held-out data

`decision accuracy` counts declining to name an actionable cause as correct when the truth is `unknown` or `no_fault`. `incorrect intervention` = named an actionable cause that is wrong (it would trigger the wrong recovery action). `missed actionable` = a fixable cause was not named.

| Test set | System | n | Exact accuracy | Macro-F1 | Decision accuracy | Incorrect intervention | Missed actionable |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A: in-distribution | learned model | 1925 | 97.9% | 0.958 | 98.5% | 0.3% | 1.0% |
| A: in-distribution | rule engine | 1925 | 73.7% | 0.620 | 75.6% | 8.9% | 9.0% |
| B: shifted | learned model | 1965 | 83.2% | 0.795 | 87.9% | 1.0% | 7.1% |
| B: shifted | rule engine | 1965 | 57.9% | 0.491 | 61.5% | 17.8% | 11.3% |

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
