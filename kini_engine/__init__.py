"""Kini engine: Spanish Quiniela modelling and ticket optimisation."""

from .backtest import walk_forward
from .core import KiniEngine, Match, Prediction
from .temporal import PredictionContext

__all__ = ["KiniEngine", "Match", "Prediction", "PredictionContext", "walk_forward"]
