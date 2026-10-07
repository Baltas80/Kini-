from __future__ import annotations

from typing import Any

import numpy as np

from .core import SIGNS, KiniEngine, Match


def multiclass_metrics(rows: list[tuple[dict[str, float], str]], calibration_bins: int = 10) -> dict[str, float]:
    """Evaluate probabilistic 1/X/2 forecasts.

    Brier is the multiclass squared-error score. RPS is the ordinal Ranked
    Probability Score using the natural order 1 < X < 2 only as a stable
    reporting convention; it should be compared consistently across runs.
    ECE measures calibration of the maximum predicted probability.
    """
    if not rows:
        return {
            "n": 0,
            "accuracy": 0.0,
            "brier": 0.0,
            "logloss": 0.0,
            "rps": 0.0,
            "ece": 0.0,
        }

    idx = {s: i for i, s in enumerate(SIGNS)}
    acc = brier = ll = rps = 0.0
    confidences: list[float] = []
    correct: list[float] = []

    for p, y in rows:
        v = np.asarray([p[s] for s in SIGNS], dtype=float)
        v = np.clip(v, 1e-12, None)
        v /= v.sum()
        yi = idx[y]
        acc += float(int(SIGNS[int(np.argmax(v))] == y))
        brier += float(np.sum((v - np.eye(3)[yi]) ** 2))
        ll -= float(np.log(v[yi]))

        pred_cdf = np.cumsum(v)[:2]
        obs_cdf = np.cumsum(np.eye(3)[yi])[:2]
        rps += float(np.mean((pred_cdf - obs_cdf) ** 2))

        confidences.append(float(v.max()))
        correct.append(float(int(np.argmax(v) == yi)))

    n = len(rows)
    ece = 0.0
    edges = np.linspace(0.0, 1.0, calibration_bins + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = [
            i for i, conf in enumerate(confidences)
            if (conf >= lo and conf < hi) or (hi == 1.0 and conf == hi)
        ]
        if mask:
            ece += len(mask) / n * abs(
                float(np.mean([correct[i] for i in mask])) -
                float(np.mean([confidences[i] for i in mask]))
            )

    return {
        "n": n,
        "accuracy": acc / n,
        "brier": brier / n,
        "logloss": ll / n,
        "rps": rps / n,
        "ece": ece,
    }


def baseline_probabilities(
    matches: list[Match],
    source: str = "uniform",
) -> list[tuple[dict[str, float], str]]:
    """Build leakage-free simple baselines from each match's available fields."""
    out = []
    for m in matches:
        if source == "lae" and m.lae:
            p = {s: float(m.lae.get(s, 0.0)) for s in SIGNS}
        elif source == "market" and m.market:
            p = {s: float(m.market.get(s, 0.0)) for s in SIGNS}
        else:
            p = {s: 1 / 3 for s in SIGNS}
        total = sum(max(0.0, p[s]) for s in SIGNS) or 1.0
        p = {s: max(0.0, p[s]) / total for s in SIGNS}
        out.append((p, m.outcome()))
    return out


def walk_forward(
    matches: list[Match],
    min_train: int = 80,
    refit_every: int = 1,
    decay: float = 0.995,
) -> dict[str, Any]:
    """Strict chronological evaluation: every forecast sees only prior matches."""
    data = sorted(matches, key=lambda m: KiniEngine.dc._date_num(m.date))
    if min_train < 12:
        raise ValueError("min_train must be at least 12")
    if refit_every < 1:
        raise ValueError("refit_every must be positive")

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


def compare_walk_forward(
    matches: list[Match],
    min_train: int = 80,
    refit_every: int = 1,
    decay: float = 0.995,
) -> dict[str, Any]:
    """Compare isolated baselines and the ensemble using identical time splits."""
    data = sorted(matches, key=lambda m: KiniEngine.dc._date_num(m.date))
    modes = ("dc", "ml", "ensemble")
    rows = {mode: [] for mode in modes}
    market_rows: list[tuple[dict[str, float], str]] = []

    engine = KiniEngine(enable_ml=True)
    for i in range(min_train, len(data)):
        if (i == min_train) or ((i - min_train) % refit_every == 0):
            engine.dc.decay = decay
            engine.fit(data[:i])

        m = data[i]
        for mode in modes:
            try:
                pred = engine.predict(m, mode=mode)
            except ValueError:
                continue
            rows[mode].append((pred.probabilities, m.outcome()))

        if m.market:
            market_rows.append((m.market, m.outcome()))

    result = {
        mode: multiclass_metrics(values)
        for mode, values in rows.items()
    }
    result["market"] = multiclass_metrics(market_rows) if market_rows else {
        "n": 0, "accuracy": 0.0, "brier": 0.0, "logloss": 0.0, "rps": 0.0, "ece": 0.0
    }
    result["n_total"] = len(data) - min_train
    return result
