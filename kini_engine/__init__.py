"""Kini engine: Spanish Quiniela modelling and ticket optimisation."""

from .core import EloModel, KiniEngine, Match, Prediction, TicketOptimizer
from .backtest import benchmark, multiclass_metrics, walk_forward, walk_forward_baseline

__all__ = [
    "EloModel",
    "KiniEngine",
    "Match",
    "Prediction",
    "TicketOptimizer",
    "benchmark",
    "multiclass_metrics",
    "walk_forward",
    "walk_forward_baseline",
]
