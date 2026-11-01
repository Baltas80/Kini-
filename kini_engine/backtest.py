from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np

from .core import SIGNS, KiniEngine, Match, _date_num


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


def _calendar_day(value: datetime | str) -> str:
    """Return the calendar date represented by the input, without timezone conversion."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    raw = str(value).strip()
    normalized = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date().isoformat()
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return datetime.fromtimestamp(_date_num(value)).date().isoformat()


def _date_groups(matches: list[Match]) -> list[list[Match]]:
    """Sort matches and group fixtures from the same calendar day."""
    data = sorted(matches, key=lambda m: (_calendar_day(m.date), _date_num(m.date)))
    groups: list[list[Match]] = []
    current_day: str | None = None
    for match in data:
        day = _calendar_day(match.date)
        if day != current_day:
            groups.append([])
            current_day = day
        groups[-1].append(match)
    return groups


def walk_forward(
    matches: list[Match],
    min_train: int = 80,
    refit_every: int = 1,
    decay: float = 0.995,
) -> dict[str, Any]:
    """Evaluate chronologically without training on fixtures from the forecast date.

    min_train counts matches. refit_every counts forecast dates, not fixtures.
    All fixtures on one date use the same prior-date training history.
    """
    if min_train < 12:
        raise ValueError("min_train must be at least 12")
    if refit_every < 1:
        raise ValueError("refit_every must be positive")

    groups = _date_groups(matches)
    train: list[Match] = []
    scored: list[tuple[dict[str, float], str]] = []
    engine = KiniEngine()
    forecast_day = 0
    test_dates: list[str] = []
    initial_train_size: int | None = None

    for group in groups:
        if len(train) < min_train:
            train.extend(group)
            continue
        if initial_train_size is None:
            initial_train_size = len(train)
        if forecast_day % refit_every == 0:
            engine.dc.decay = decay
            engine.fit(train)
        for match in group:
            pred = engine.predict(match)
            scored.append((pred.probabilities, match.outcome()))
            test_dates.append(_calendar_day(match.date))
        train.extend(group)
        forecast_day += 1

    return {
        "metrics": multiclass_metrics(scored),
        "rows": [{"actual": y, "probabilities": p} for p, y in scored],
        "n_train_initial": initial_train_size or len(train),
        "n_test": len(scored),
        "test_start_date": min(test_dates) if test_dates else None,
        "test_end_date": max(test_dates) if test_dates else None,
    }


def compare_walk_forward(
    matches: list[Match],
    min_train: int = 80,
    refit_every: int = 1,
    decay: float = 0.995,
) -> dict[str, Any]:
    """Compare models on date-grouped splits and report a market common sample."""
    if min_train < 12:
        raise ValueError("min_train must be at least 12")
    if refit_every < 1:
        raise ValueError("refit_every must be positive")

    groups = _date_groups(matches)
    train: list[Match] = []
    modes = ("dc", "ml", "ensemble")
    rows = {mode: [] for mode in modes}
    common_rows = {mode: [] for mode in modes}
    market_rows: list[tuple[dict[str, float], str]] = []
    engine = KiniEngine(enable_ml=True)
    forecast_day = 0
    n_total = 0
    test_dates: list[str] = []
    initial_train_size: int | None = None

    for group in groups:
        if len(train) < min_train:
            train.extend(group)
            continue
        if initial_train_size is None:
            initial_train_size = len(train)
        if forecast_day % refit_every == 0:
            engine.dc.decay = decay
            engine.fit(train)

        for match in group:
            actual = match.outcome()
            predictions: dict[str, dict[str, float]] = {}
            for mode in modes:
                try:
                    pred = engine.predict(match, mode=mode)
                except ValueError:
                    continue
                predictions[mode] = pred.probabilities
                rows[mode].append((pred.probabilities, actual))

            if match.market:
                market_rows.append((match.market, actual))
                for mode, probabilities in predictions.items():
                    common_rows[mode].append((probabilities, actual))
            n_total += 1
            test_dates.append(_calendar_day(match.date))

        train.extend(group)
        forecast_day += 1

    empty = {"n": 0, "accuracy": 0.0, "brier": 0.0, "logloss": 0.0, "rps": 0.0, "ece": 0.0}
    result: dict[str, Any] = {
        mode: multiclass_metrics(values) for mode, values in rows.items()
    }
    result["market"] = multiclass_metrics(market_rows) if market_rows else empty
    result["common_sample"] = {
        **{mode: multiclass_metrics(values) for mode, values in common_rows.items()},
        "market": multiclass_metrics(market_rows) if market_rows else empty,
    }
    result["n_total"] = n_total
    result["n_train_initial"] = initial_train_size or len(train)
    result["test_start_date"] = min(test_dates) if test_dates else None
    result["test_end_date"] = max(test_dates) if test_dates else None
    return result
