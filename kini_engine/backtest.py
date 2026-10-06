from __future__ import annotations

from typing import Any, Callable

import numpy as np

from .core import SIGNS, KiniEngine, Match, _norm


def multiclass_metrics(rows: list[tuple[dict[str, float], str]]) -> dict[str, float]:
    """Return proper scoring metrics for ordered 1/X/2 probabilities."""
    if not rows:
        return {"n": 0, "accuracy": 0.0, "brier": 0.0, "logloss": 0.0, "rps": 0.0, "ece": 0.0}
    acc = brier = ll = rps = 0.0
    idx = {s: i for i, s in enumerate(SIGNS)}
    for p, y in rows:
        v = _norm([p[s] for s in SIGNS])
        yi = idx[y]
        target = np.eye(3)[yi]
        acc += int(SIGNS[int(np.argmax(v))] == y)
        brier += float(np.sum((v - target) ** 2))
        ll -= np.log(max(v[yi], 1e-12))
        rps += float(np.sum((np.cumsum(v) - np.cumsum(target))[:-1] ** 2) / 2.0)
    ece = expected_calibration_error(rows)
    n = len(rows)
    return {
        "n": n,
        "accuracy": acc / n,
        "brier": brier / n,
        "logloss": ll / n,
        "rps": rps / n,
        "ece": ece,
    }


def expected_calibration_error(
    rows: list[tuple[dict[str, float], str]], bins: int = 10
) -> float:
    """ECE on the maximum predicted class probability."""
    if not rows:
        return 0.0
    conf = []
    hit = []
    for p, y in rows:
        v = _norm([p[s] for s in SIGNS])
        i = int(np.argmax(v))
        conf.append(float(v[i]))
        hit.append(float(SIGNS[i] == y))
    conf = np.asarray(conf)
    hit = np.asarray(hit)
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (conf >= lo) & (conf < hi if hi < 1.0 else conf <= hi)
        if np.any(mask):
            total += float(mask.mean() * abs(hit[mask].mean() - conf[mask].mean()))
    return total


def _historical_frequency(history: list[Match]) -> dict[str, float]:
    counts = {s: 0.0 for s in SIGNS}
    for m in history:
        if m.home_goals is not None and m.away_goals is not None:
            counts[m.outcome()] += 1.0
    return _norm([counts[s] for s in SIGNS]) if sum(counts.values()) else _norm([1, 1, 1])


def _home_advantage_baseline(history: list[Match]) -> dict[str, float]:
    counts = {s: 0.0 for s in SIGNS}
    for m in history:
        if m.home_goals is not None and m.away_goals is not None:
            counts[m.outcome()] += 1.0
    if not counts:
        return _norm([1, 1, 1])
    return _norm([counts["1"], counts["X"], counts["2"]])


def walk_forward(
    matches: list[Match],
    min_train: int = 80,
    refit_every: int = 1,
    decay: float = 0.995,
) -> dict[str, Any]:
    """Strict chronological evaluation; each prediction sees only prior matches."""
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


def walk_forward_baseline(
    matches: list[Match],
    min_train: int = 80,
    predictor: Callable[[list[Match], Match], dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Causal baseline evaluator, useful for proving model uplift."""
    data = sorted(matches, key=lambda m: KiniEngine.dc._date_num(m.date))
    rows: list[tuple[dict[str, float], str]] = []
    for i in range(min_train, len(data)):
        history = data[:i]
        m = data[i]
        p = predictor(history, m) if predictor else _historical_frequency(history)
        rows.append((p, m.outcome()))
    return {"metrics": multiclass_metrics(rows), "rows": [{"actual": y, "probabilities": p} for p, y in rows]}


def benchmark(
    matches: list[Match],
    min_train: int = 80,
    decay: float = 0.995,
) -> dict[str, Any]:
    """Compare the engine with causal historical-frequency baselines."""
    model = walk_forward(matches, min_train=min_train, decay=decay)
    baseline = walk_forward_baseline(matches, min_train=min_train)
    return {
        "model": model["metrics"],
        "historical_frequency": baseline["metrics"],
        "delta_logloss": baseline["metrics"]["logloss"] - model["metrics"]["logloss"],
        "delta_brier": baseline["metrics"]["brier"] - model["metrics"]["brier"],
        "delta_rps": baseline["metrics"]["rps"] - model["metrics"]["rps"],
        "delta_ece": baseline["metrics"]["ece"] - model["metrics"]["ece"],
    }
