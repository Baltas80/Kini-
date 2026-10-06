from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from .causality import assert_causal_history
from .core import Match, SIGNS, _norm
from .temporal import parse_information_at


@dataclass
class UniformBaseline:
    """Reference with no learned information: 1/3 for every sign."""

    name: str = "uniform"

    def fit(self, history: Iterable[Match]) -> "UniformBaseline":
        return self

    def predict_proba(self) -> dict[str, float]:
        return dict(zip(SIGNS, (1 / 3, 1 / 3, 1 / 3)))


@dataclass
class ExpandingPriorBaseline:
    """Empirical 1X2 prior estimated only from the supplied past history."""

    alpha: float = 1.0
    name: str = "expanding_prior"
    probabilities: dict[str, float] | None = None

    def fit(self, history: Iterable[Match]) -> "ExpandingPriorBaseline":
        if self.alpha <= 0:
            raise ValueError("alpha must be > 0")
        counts = {sign: self.alpha for sign in SIGNS}
        for match in history:
            counts[match.outcome()] += 1.0
        self.probabilities = _norm([counts[sign] for sign in SIGNS])
        return self

    def predict_proba(self) -> dict[str, float]:
        if self.probabilities is None:
            raise RuntimeError("baseline must be fitted before prediction")
        return dict(self.probabilities)


@dataclass
class RecentPriorBaseline:
    """Empirical 1X2 prior over the most recent completed matches."""

    window: int = 50
    alpha: float = 1.0
    name: str = "recent_prior"
    probabilities: dict[str, float] | None = None

    def fit(self, history: Iterable[Match]) -> "RecentPriorBaseline":
        if self.window <= 0:
            raise ValueError("window must be > 0")
        if self.alpha <= 0:
            raise ValueError("alpha must be > 0")
        usable = list(history)[-self.window:]
        counts = {sign: self.alpha for sign in SIGNS}
        for match in usable:
            counts[match.outcome()] += 1.0
        self.probabilities = _norm([counts[sign] for sign in SIGNS])
        return self

    def predict_proba(self) -> dict[str, float]:
        if self.probabilities is None:
            raise RuntimeError("baseline must be fitted before prediction")
        return dict(self.probabilities)


def baseline_suite(
    history: list[Match],
    *,
    information_at: str,
    recent_window: int = 50,
    alpha: float = 1.0,
) -> dict[str, dict[str, float]]:
    """Fit all reference baselines on exactly the supplied causal history."""
    cutoff = parse_information_at(information_at)
    assert_causal_history(history, cutoff)

    models = (
        UniformBaseline(),
        ExpandingPriorBaseline(alpha=alpha),
        RecentPriorBaseline(window=recent_window, alpha=alpha),
    )
    return {
        model.name: model.fit(history).predict_proba()
        for model in models
    }
