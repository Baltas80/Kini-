"""Kini engine: Spanish Quiniela modelling and ticket optimisation."""

from .core import KiniEngine, Match, Prediction
from .backtest import walk_forward
from .team_identity import TeamIdentity, TeamIdentityRegistry

__all__ = [
    "KiniEngine",
    "Match",
    "Prediction",
    "TeamIdentity",
    "TeamIdentityRegistry",
    "walk_forward",
]
