"""Shadow model: a compact learned classifier served from a small JSON file.

Pure-Python inference (standardize -> linear scores -> softmax), so the API needs neither
scikit-learn nor pickle loading. The model only OBSERVES: its prediction is recorded next to the
rule engine's answer and never changes rankings, recommendations or recovery actions.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "models" / "root_cause_serving_v1.json"


class ServingModel:
    def __init__(self, spec: dict):
        self.version: str = spec["version"]
        self.features: list[str] = spec["features"]
        self.classes: list[str] = spec["classes"]
        self.mean: list[float] = spec["scaler_mean"]
        self.scale: list[float] = spec["scaler_scale"]
        self.coef: list[list[float]] = spec["coef"]
        self.intercept: list[float] = spec["intercept"]
        self.tau: float = spec["tau"]
        if not (len(self.mean) == len(self.scale) == len(self.features) and len(self.coef) == len(self.classes)):
            raise ValueError("inconsistent serving model file")

    def predict_proba(self, feats: dict) -> dict[str, float]:
        x = [(float(feats[f]) - m) / s for f, m, s in zip(self.features, self.mean, self.scale)]
        scores = [b + sum(w * xi for w, xi in zip(row, x)) for row, b in zip(self.coef, self.intercept)]
        top = max(scores)
        exps = [math.exp(z - top) for z in scores]
        total = sum(exps)
        return {c: e / total for c, e in zip(self.classes, exps)}

    def predict(self, feats: dict) -> dict:
        proba = self.predict_proba(feats)
        best = max(proba, key=proba.get)
        named = proba[best] >= self.tau
        return {"version": self.version, "prediction": best if named else "unknown", "top_class": best,
                "confidence": round(proba[best], 4), "abstained": not named, "tau": self.tau,
                "probabilities": {k: round(v, 4) for k, v in sorted(proba.items(), key=lambda kv: -kv[1])}}


@lru_cache(maxsize=4)
def load(path: str | None = None) -> ServingModel | None:
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return None
    return ServingModel(json.loads(p.read_text(encoding="utf-8")))
