"""Kini engine: Spanish Quiniela modelling and ticket optimisation."""

from .backtest import walk_forward
from .core import KiniEngine, Match, Prediction
from .snapshots import SnapshotObservation, TemporalSnapshot, build_snapshot, load_observations_jsonl
from .temporal import PredictionContext

__all__ = ["KiniEngine", "Match", "Prediction", "PredictionContext", "SnapshotObservation", "TemporalSnapshot", "build_snapshot", "load_observations_jsonl", "walk_forward"]
