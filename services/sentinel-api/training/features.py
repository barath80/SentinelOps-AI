"""Training-side wrapper: the feature code itself lives in app/analysis/ml_features.py so that
training and the API's shadow model compute identical features."""
from app.analysis.ml_features import FEATURES, extract as _extract

from .generator import NOW

__all__ = ["FEATURES", "extract"]


def extract(events, cfg=None):
    return _extract(events, NOW) if cfg is None else _extract(events, NOW, cfg)
