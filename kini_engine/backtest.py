from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np

from .baselines import baseline_suite
from .causality import assert_causal_history
from .core import DixonColes, SIGNS, KiniEngine, Match
from .temporal import parse_information_at


def multiclass_metrics(rows: list[tuple[dict[str, float], str]]) -> dict[str, float]:
    if not rows:
        raise ValueError("cannot compute metrics for an empty evaluation set")
    acc = brier = ll = 0.0
    idx = {s: i for i, s in enumerate(SIGNS)}
    for p, y in rows:
        v = np.array([p[s] for s in SIGNS], dtype=float)
        yi = idx[y]
        acc += int(SIGNS[int(np.argmax(v))] == y)
        brier += float(np.sum((v - np.eye(3)[yi]) ** 2))
        ll -= np.log(max(v[yi], 1e-12))
    n = len(rows)
    return {"n": n, "accuracy": acc / n, "brier": brier / n, "logloss": ll / n}


def walk_forward(
    matches: list[Match],
    min_train: int = 80,
    refit_every: int = 1,
    decay: float = 0.995,
) -> dict[str, Any]:
    data = sorted(matches, key=lambda m: DixonColes._date_num(m.date))
    scored: list[tuple[dict[str, float], str]] = []
    prediction_rows: list[dict[str, Any]] = []
    engine = KiniEngine()
    for i in range(min_train, len(data)):
        m = data[i]
        target_kickoff_at = parse_information_at(m.date, "target kickoff")
        information_at = target_kickoff_at - timedelta(microseconds=1)

        if (i == min_train) or ((i - min_train) % refit_every == 0):
            causal_history = data[:i]
            assert_causal_history(causal_history, information_at)
            engine.dc.decay = decay
            engine.fit(causal_history)

        pred = engine.predict(m, information_at=information_at)
        actual = m.outcome()
        scored.append((pred.probabilities, actual))
        prediction_rows.append({
            "actual": actual,
            "probabilities": pred.probabilities,
            "information_at": pred.information_at,
            "target_kickoff_at": pred.target_kickoff_at,
        })
    return {
        "metrics": multiclass_metrics(scored),
        "rows": prediction_rows,
    }


def baseline_walk_forward(
    matches: list[Match],
    min_train: int = 1,
    recent_window: int = 50,
    alpha: float = 1.0,
) -> dict[str, Any]:
    """Causal walk-forward benchmark for simple probabilistic references."""
    if min_train < 1:
        raise ValueError("min_train must be >= 1")
    if recent_window < 1:
        raise ValueError("recent_window must be >= 1")
    if alpha <= 0:
        raise ValueError("alpha must be > 0")

    data = sorted(matches, key=lambda m: DixonColes._date_num(m.date))
    if len(data) <= min_train:
        raise ValueError("evaluation requires at least one match after min_train")

    scored: dict[str, list[tuple[dict[str, float], str]]] = {
        "uniform": [],
        "expanding_prior": [],
        "recent_prior": [],
    }
    rows: list[dict[str, Any]] = []

    for i in range(min_train, len(data)):
        current = data[i]
        target_kickoff_at = parse_information_at(current.date, "target kickoff")
        information_at = target_kickoff_at - timedelta(microseconds=1)
        history = data[:i]
        assert_causal_history(history, information_at)
        predictions = baseline_suite(
            history,
            information_at=information_at,
            recent_window=recent_window,
            alpha=alpha,
        )
        actual = current.outcome()
        for name, probabilities in predictions.items():
            scored[name].append((probabilities, actual))
        rows.append({
            "actual": actual,
            "information_at": information_at.isoformat(),
            "target_kickoff_at": target_kickoff_at.isoformat(),
        })

    return {
        "protocol": {
            "min_train": min_train,
            "recent_window": recent_window,
            "alpha": alpha,
            "test_rows": len(rows),
        },
        "metrics": {
            name: multiclass_metrics(values)
            for name, values in scored.items()
        },
        "rows": rows,
    }
