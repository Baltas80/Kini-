from __future__ import annotations

from typing import Callable

from .backtest import walk_forward
from .core import Match


def tune_decay(
    matches: list[Match],
    objective: Callable[[dict], float] | None = None,
    candidates: tuple[float, ...] = (0.98, 0.99, 0.995, 0.999),
    min_train: int = 80,
) -> dict[str, float]:
    objective = objective or (lambda x: x["metrics"]["logloss"])
    results = {}
    for decay in candidates:
        # The public v0.2 engine keeps decay configurable at model level.
        # Evaluation is deliberately walk-forward; no future result enters a fold.
        engine_result = walk_forward(matches, min_train=min_train, decay=decay)
        results[str(decay)] = float(objective(engine_result))
    best = min(results, key=results.get)
    return {"best_decay": float(best), "best_score": results[best]}
