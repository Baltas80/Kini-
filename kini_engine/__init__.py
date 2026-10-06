"""Kini engine: Spanish Quiniela modelling and ticket optimisation."""

from .backtest import walk_forward
from .causality import CausalityViolation, assert_available_at, assert_causal_history, assert_causal_match
from .core import KiniEngine, Match, Prediction
from .snapshots import SnapshotObservation, TemporalSnapshot, build_snapshot, load_observations_jsonl
from .temporal import PredictionContext

__all__ = ["KiniEngine", "Match", "Prediction", "PredictionContext", "SnapshotObservation", "TemporalSnapshot", "build_snapshot", "load_observations_jsonl", "CausalityViolation", "assert_available_at", "assert_causal_match", "assert_causal_history", "walk_forward"]
