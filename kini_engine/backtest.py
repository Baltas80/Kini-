from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np

from .core import DixonColes, SIGNS, KiniEngine, Match, _norm
from .temporal import parse_information_at


def multiclass_metrics(rows: list[tuple[dict[str, float], str]]) -> dict[str, float]:
    if not rows:
        return {"n": 0, "accuracy": 0.0, "brier": 0.0, "logloss": 0.0}
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
            causal_history = [
                historical_match
                for historical_match in data[:i]
                if parse_information_at(historical_match.date, "historical match timestamp") < information_at
            ]
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
