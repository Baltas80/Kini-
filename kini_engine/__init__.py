"""Kini engine: Spanish Quiniela modelling and ticket optimisation."""

from .core import KiniEngine, Match, Prediction
from .backtest import walk_forward

__all__ = ["KiniEngine", "Match", "Prediction", "walk_forward"]
