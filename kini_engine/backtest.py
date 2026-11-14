from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np

from .core import SIGNS, KiniEngine, Match, _date_num


def _classwise_calibration(
    probability_matrix: np.ndarray,
    target_indices: np.ndarray,
    calibration_bins: int,
) -> dict[str, dict[str, Any]]:
    """Return one-vs-rest reliability diagnostics for each 1/X/2 class."""
    n = int(len(target_indices))
    edges = np.linspace(0.0, 1.0, calibration_bins + 1)
    diagnostics: dict[str, dict[str, Any]] = {}

    for class_index, sign in enumerate(SIGNS):
        predicted = probability_matrix[:, class_index]
        observed = (target_indices == class_index).astype(float)
        clipped = np.clip(predicted, 1e-12, 1.0 - 1e-12)
        bins: list[dict[str, float | int]] = []
        ece = 0.0

        for bin_index, (lower, upper) in enumerate(zip(edges[:-1], edges[1:])):
            if bin_index == calibration_bins - 1:
                mask = (predicted >= lower) & (predicted <= upper)
            else:
                mask = (predicted >= lower) & (predicted < upper)
            count = int(mask.sum())
            if not count:
                continue
            mean_probability = float(predicted[mask].mean())
            observed_frequency = float(observed[mask].mean())
            ece += count / n * abs(mean_probability - observed_frequency)
            bins.append({
                "lower": float(lower),
                "upper": float(upper),
                "count": count,
                "mean_probability": mean_probability,
                "observed_frequency": observed_frequency,
            })

        if n:
            binary_brier = float(np.mean((predicted - observed) ** 2))
            binary_logloss = float(-np.mean(
                observed * np.log(clipped)
                + (1.0 - observed) * np.log1p(-clipped)
            ))
            prevalence: float | None = float(observed.mean())
            mean_probability: float | None = float(predicted.mean())
            ece_value: float | None = float(ece)
        else:
            binary_brier = 0.0
            binary_logloss = 0.0
            prevalence = None
            mean_probability = None
            ece_value = None

        diagnostics[sign] = {
            "n": n,
            "prevalence": prevalence,
            "mean_probability": mean_probability,
            "brier": binary_brier,
            "logloss": binary_logloss,
            "ece": ece_value,
            "bins": bins,
        }

    return diagnostics


def multiclass_metrics(
    rows: list[tuple[dict[str, float], str]],
    calibration_bins: int = 10,
) -> dict[str, Any]:
    """Evaluate 1/X/2 forecasts, including one-vs-rest class calibration.

    Class-wise diagnostics are computed only from the supplied out-of-sample
    forecasts. They describe reliability; they do not fit or apply a calibrator.
    """
    if isinstance(calibration_bins, bool) or not isinstance(calibration_bins, int) or calibration_bins < 1:
        raise ValueError("calibration_bins must be a positive integer")

    if not rows:
        return {
            "n": 0,
            "accuracy": 0.0,
            "brier": 0.0,
            "logloss": 0.0,
            "rps": 0.0,
            "ece": 0.0,
            "classwise_calibration": _classwise_calibration(
                np.empty((0, 3), dtype=float),
                np.empty((0,), dtype=int),
                calibration_bins,
            ),
        }

    idx = {s: i for i, s in enumerate(SIGNS)}
    probability_vectors: list[np.ndarray] = []
    target_indices: list[int] = []
    for probabilities, outcome in rows:
        if outcome not in idx:
            raise ValueError(f"unknown 1/X/2 outcome: {outcome!r}")
        try:
            vector = np.asarray([probabilities[sign] for sign in SIGNS], dtype=float)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("forecast must contain finite 1/X/2 probabilities") from exc
        if not np.isfinite(vector).all() or np.any(vector < 0.0) or vector.sum() <= 0.0:
            raise ValueError("forecast probabilities must be finite, non-negative and have positive sum")
        probability_vectors.append(vector / vector.sum())
        target_indices.append(idx[outcome])

    probability_matrix = np.vstack(probability_vectors)
    targets = np.asarray(target_indices, dtype=int)
    acc = brier = ll = rps = 0.0
    confidences: list[float] = []
    correct: list[float] = []

    for vector, target_index in zip(probability_matrix, targets):
        acc += float(int(SIGNS[int(np.argmax(vector))] == SIGNS[target_index]))
        brier += float(np.sum((vector - np.eye(3)[target_index]) ** 2))
        ll -= float(np.log(np.clip(vector[target_index], 1e-12, 1.0)))

        pred_cdf = np.cumsum(vector)[:2]
        obs_cdf = np.cumsum(np.eye(3)[target_index])[:2]
        rps += float(np.mean((pred_cdf - obs_cdf) ** 2))

        confidences.append(float(vector.max()))
        correct.append(float(int(np.argmax(vector) == target_index)))

    n = len(rows)
    ece = 0.0
    edges = np.linspace(0.0, 1.0, calibration_bins + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = [
            i for i, confidence in enumerate(confidences)
            if (confidence >= lo and confidence < hi)
            or (hi == 1.0 and confidence == hi)
        ]
        if mask:
            ece += len(mask) / n * abs(
                float(np.mean([correct[i] for i in mask]))
                - float(np.mean([confidences[i] for i in mask]))
            )

    return {
        "n": n,
        "accuracy": acc / n,
        "brier": brier / n,
        "logloss": ll / n,
        "rps": rps / n,
        "ece": ece,
        "classwise_calibration": _classwise_calibration(
            probability_matrix, targets, calibration_bins
        ),
    }

DEFAULT_DC_ML_WEIGHT = 0.58 / (0.58 + 0.17)


def _probability_vector(probabilities: dict[str, float]) -> np.ndarray:
    values = np.asarray([probabilities[s] for s in SIGNS], dtype=float)
    if not np.isfinite(values).all() or np.any(values < 0.0) or values.sum() <= 0.0:
        raise ValueError("DC/ML ensemble received invalid probabilities")
    return values / values.sum()


def _blend_dc_ml(
    dc_probabilities: dict[str, float],
    ml_probabilities: dict[str, float],
    dc_weight: float,
) -> dict[str, float]:
    if not np.isfinite(dc_weight) or not 0.0 <= dc_weight <= 1.0:
        raise ValueError("Dixon-Coles weight must be finite and in [0, 1]")
    blended = (
        dc_weight * _probability_vector(dc_probabilities)
        + (1.0 - dc_weight) * _probability_vector(ml_probabilities)
    )
    blended /= blended.sum()
    return dict(zip(SIGNS, map(float, blended)))


def select_dc_ml_weight(
    history: list[tuple[dict[str, float], dict[str, float], str]],
    default_weight: float = DEFAULT_DC_ML_WEIGHT,
    min_history: int = 300,
    window: int = 1000,
    regularization: float = 0.02,
) -> float:
    """Choose a DC/ML convex weight using only prior out-of-sample forecasts.

    The rolling grid minimizes multiclass log loss on the latest available
    prequential predictions. A quadratic penalty shrinks the estimate toward
    the established DC/ML prior and reduces noisy weight changes.
    """
    if not np.isfinite(default_weight) or not 0.0 <= default_weight <= 1.0:
        raise ValueError("default_weight must be finite and in [0, 1]")
    if isinstance(min_history, bool) or not isinstance(min_history, int) or min_history < 1:
        raise ValueError("min_history must be a positive integer")
    if isinstance(window, bool) or not isinstance(window, int) or window < min_history:
        raise ValueError("window must be an integer greater than or equal to min_history")
    if not np.isfinite(regularization) or regularization < 0.0:
        raise ValueError("regularization must be finite and non-negative")
    if len(history) < min_history:
        return float(default_weight)

    recent = history[-window:]
    dc_matrix = np.vstack([_probability_vector(row[0]) for row in recent])
    ml_matrix = np.vstack([_probability_vector(row[1]) for row in recent])
    outcome_index = {sign: index for index, sign in enumerate(SIGNS)}
    try:
        targets = np.asarray([outcome_index[row[2]] for row in recent], dtype=int)
    except KeyError as exc:
        raise ValueError(f"unknown outcome in adaptive ensemble history: {exc.args[0]}") from exc

    candidates = sorted(set(np.linspace(0.0, 1.0, 41).tolist() + [float(default_weight)]))
    row_index = np.arange(len(recent))
    scored: list[tuple[float, float, float]] = []
    for weight in candidates:
        blended = weight * dc_matrix + (1.0 - weight) * ml_matrix
        losses = -np.log(np.clip(blended[row_index, targets], 1e-12, 1.0))
        objective = float(losses.mean()) + regularization * (weight - default_weight) ** 2
        scored.append((objective, abs(weight - default_weight), -weight))
    return float(candidates[min(range(len(candidates)), key=lambda index: scored[index])])


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


def _temporal_classwise_calibration(
    dated_rows: list[tuple[str, dict[str, float], str]],
    calibration_bins: int = 10,
) -> dict[str, dict[str, Any]]:
    """Summarize OOF one-vs-rest reliability by football season (July-June)."""
    grouped: dict[str, list[tuple[dict[str, float], str]]] = {}
    for date_value, probabilities, outcome in dated_rows:
        day = _calendar_day(date_value)
        year = int(day[:4])
        month = int(day[5:7])
        season_start = year if month >= 7 else year - 1
        season = f"{season_start}/{(season_start + 1) % 100:02d}"
        grouped.setdefault(season, []).append((probabilities, outcome))

    return {
        season: {
            "n": len(season_rows),
            "classes": multiclass_metrics(
                season_rows, calibration_bins=calibration_bins
            )["classwise_calibration"],
        }
        for season, season_rows in sorted(grouped.items())
    }


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
    adaptive_min_history: int = 300,
    adaptive_window: int = 1000,
    adaptive_regularization: float = 0.02,
) -> dict[str, Any]:
    """Compare models on date-grouped splits and report a market common sample."""
    if min_train < 12:
        raise ValueError("min_train must be at least 12")
    if refit_every < 1:
        raise ValueError("refit_every must be positive")

    groups = _date_groups(matches)
    train: list[Match] = []
    modes = ("dc", "ml", "ensemble", "ensemble_dc_ml")
    adaptive_mode = "ensemble_dc_ml_adaptive"
    all_modes = modes + (adaptive_mode,)
    rows = {mode: [] for mode in all_modes}
    dated_rows = {mode: [] for mode in all_modes}
    common_rows = {mode: [] for mode in all_modes}
    common_market_rows = {mode: [] for mode in all_modes}
    dated_common_rows = {mode: [] for mode in all_modes}
    dated_common_market_rows = {mode: [] for mode in all_modes}
    market_rows: list[tuple[dict[str, float], str]] = []
    dated_market_rows: list[tuple[str, dict[str, float], str]] = []
    prediction_errors = {mode: {"count": 0, "first_error": None} for mode in all_modes}
    adaptive_history: list[tuple[dict[str, float], dict[str, float], str]] = []
    adaptive_weight_trace: list[dict[str, Any]] = []
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

        # Select once per calendar date. Outcomes from fixtures in this group
        # are appended only after every fixture for the date has been forecast.
        dc_weight = select_dc_ml_weight(
            adaptive_history,
            min_history=adaptive_min_history,
            window=adaptive_window,
            regularization=adaptive_regularization,
        )
        pending_adaptive_history: list[
            tuple[dict[str, float], dict[str, float], str]
        ] = []

        for match in group:
            actual = match.outcome()
            forecast_date = _calendar_day(match.date)
            predictions: dict[str, dict[str, float]] = {}
            for mode in modes:
                try:
                    pred = engine.predict(match, mode=mode, history=train)
                except ValueError as exc:
                    diagnostic = prediction_errors[mode]
                    diagnostic["count"] += 1
                    if diagnostic["first_error"] is None:
                        diagnostic["first_error"] = str(exc)
                    continue
                predictions[mode] = pred.probabilities
                rows[mode].append((pred.probabilities, actual))
                dated_rows[mode].append((forecast_date, pred.probabilities, actual))

            if "dc" in predictions and "ml" in predictions:
                adaptive_probabilities = _blend_dc_ml(
                    predictions["dc"], predictions["ml"], dc_weight
                )
                predictions[adaptive_mode] = adaptive_probabilities
                rows[adaptive_mode].append((adaptive_probabilities, actual))
                dated_rows[adaptive_mode].append((forecast_date, adaptive_probabilities, actual))
                pending_adaptive_history.append(
                    (predictions["dc"], predictions["ml"], actual)
                )
            else:
                diagnostic = prediction_errors[adaptive_mode]
                diagnostic["count"] += 1
                if diagnostic["first_error"] is None:
                    diagnostic["first_error"] = (
                        "adaptive DC/ML ensemble requires valid predictions from both models"
                    )

            if match.market:
                market_rows.append((match.market, actual))
                dated_market_rows.append((forecast_date, match.market, actual))
                for mode, probabilities in predictions.items():
                    common_rows[mode].append((probabilities, actual))
                    common_market_rows[mode].append((match.market, actual))
                    dated_common_rows[mode].append((forecast_date, probabilities, actual))
                    dated_common_market_rows[mode].append((forecast_date, match.market, actual))
            n_total += 1
            test_dates.append(_calendar_day(match.date))

        adaptive_history.extend(pending_adaptive_history)
        adaptive_weight_trace.append({
            "date": _calendar_day(group[0].date),
            "dc_weight": dc_weight,
            "prior_oof_predictions": len(adaptive_history) - len(pending_adaptive_history),
        })
        train.extend(group)
        forecast_day += 1

    empty = {"n": 0, "accuracy": 0.0, "brier": 0.0, "logloss": 0.0, "rps": 0.0, "ece": 0.0}
    result: dict[str, Any] = {
        mode: multiclass_metrics(values) for mode, values in rows.items()
    }
    result["market"] = multiclass_metrics(market_rows) if market_rows else empty
    result["common_sample"] = {
        mode: {
            "model": multiclass_metrics(common_rows[mode]),
            "market": multiclass_metrics(common_market_rows[mode]) if common_market_rows[mode] else empty,
        }
        for mode in all_modes
    }
    weights = [float(row["dc_weight"]) for row in adaptive_weight_trace]
    result["adaptive_ensemble"] = {
        "method": "rolling prequential multiclass log-loss grid search",
        "prior_dc_weight": DEFAULT_DC_ML_WEIGHT,
        "min_history": adaptive_min_history,
        "window": adaptive_window,
        "regularization": adaptive_regularization,
        "n_oof_predictions": len(adaptive_history),
        "n_weight_updates": sum(
            int(row["prior_oof_predictions"]) >= adaptive_min_history
            for row in adaptive_weight_trace
        ),
        "mean_dc_weight": float(np.mean(weights)) if weights else DEFAULT_DC_ML_WEIGHT,
        "median_dc_weight": float(np.median(weights)) if weights else DEFAULT_DC_ML_WEIGHT,
        "min_dc_weight": float(np.min(weights)) if weights else DEFAULT_DC_ML_WEIGHT,
        "max_dc_weight": float(np.max(weights)) if weights else DEFAULT_DC_ML_WEIGHT,
        "last_dc_weight": weights[-1] if weights else DEFAULT_DC_ML_WEIGHT,
        "weight_trace": adaptive_weight_trace,
    }
    result["temporal_classwise_calibration"] = {
        mode: _temporal_classwise_calibration(values)
        for mode, values in dated_rows.items()
    }
    result["temporal_classwise_calibration"]["market"] = (
        _temporal_classwise_calibration(dated_market_rows)
    )
    result["temporal_common_sample_calibration"] = {
        mode: {
            "model": _temporal_classwise_calibration(dated_common_rows[mode]),
            "market": _temporal_classwise_calibration(dated_common_market_rows[mode]),
        }
        for mode in all_modes
    }
    result["prediction_errors"] = prediction_errors
    result["n_total"] = n_total
    result["n_train_initial"] = initial_train_size or len(train)
    result["test_start_date"] = min(test_dates) if test_dates else None
    result["test_end_date"] = max(test_dates) if test_dates else None
    return result
