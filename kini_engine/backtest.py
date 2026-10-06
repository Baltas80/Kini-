from __future__ import annotations

from dataclasses import asdict
from typing import Any

import numpy as np

from .core import SIGNS, KiniEngine, Match, _norm


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
    data = sorted(matches, key=lambda m: KiniEngine.dc._date_num(m.date))
    scored: list[tuple[dict[str, float], str]] = []
    engine = KiniEngine()
    for i in range(min_train, len(data)):
        if (i == min_train) or ((i - min_train) % refit_every == 0):
            engine.dc.decay = decay
            engine.fit(data[:i])
        m = data[i]
        pred = engine.predict(m)
        scored.append((pred.probabilities, m.outcome()))
    return {
        "metrics": multiclass_metrics(scored),
        "rows": [{"actual": y, "probabilities": p} for p, y in scored],
    }
