from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import date
from typing import Any

import numpy as np

SIGNS = ("1", "X", "2")


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _probability_vector(row: dict[str, Any], mode: str) -> dict[str, float]:
    value = (
        row["market_probabilities"]
        if mode == "market"
        else row["model_probabilities"][mode]
    )
    return {sign: float(value[sign]) for sign in SIGNS}


def _predicted_sign(row: dict[str, Any], mode: str) -> str:
    if mode == "market":
        probabilities = _probability_vector(row, mode)
        return max(SIGNS, key=probabilities.__getitem__)
    return row["model_signs"][mode]


def _metrics(
    rows: list[dict[str, Any]],
    mode: str,
    *,
    include_bins: bool = True,
) -> dict[str, Any]:
    n = len(rows)
    confusion = {actual: {predicted: 0 for predicted in SIGNS} for actual in SIGNS}
    probability_sums = {sign: 0.0 for sign in SIGNS}
    binary_brier_sums = {sign: 0.0 for sign in SIGNS}
    binary_logloss_sums = {sign: 0.0 for sign in SIGNS}
    bin_rows: dict[str, list[list[float]]] = {
        sign: [[] for _ in range(10)] for sign in SIGNS
    }
    multiclass_brier = 0.0
    multiclass_logloss = 0.0
    correct = 0
    top_two_covered = 0
    draw_count = 0
    draw_top_two_covered = 0
    top_two_probability_mass = 0.0

    for row in rows:
        actual = row["actual_result"]
        predicted = _predicted_sign(row, mode)
        probabilities = _probability_vector(row, mode)
        ranked_signs = sorted(
            SIGNS,
            key=probabilities.__getitem__,
            reverse=True,
        )
        top_two = set(ranked_signs[:2])
        top_two_covered += actual in top_two
        top_two_probability_mass += sum(probabilities[sign] for sign in top_two)
        if actual == "X":
            draw_count += 1
            draw_top_two_covered += "X" in top_two
        confusion[actual][predicted] += 1
        correct += predicted == actual
        multiclass_brier += sum(
            (probabilities[sign] - float(sign == actual)) ** 2 for sign in SIGNS
        )
        multiclass_logloss -= math.log(max(probabilities[actual], 1e-15))

        for sign in SIGNS:
            probability = probabilities[sign]
            observed = float(actual == sign)
            probability_sums[sign] += probability
            binary_brier_sums[sign] += (probability - observed) ** 2
            clipped = min(max(probability, 1e-15), 1.0 - 1e-15)
            binary_logloss_sums[sign] -= observed * math.log(clipped) + (
                1.0 - observed
            ) * math.log1p(-clipped)
            if include_bins:
                bin_index = min(int(probability * 10), 9)
                bin_rows[sign][bin_index].append((probability, observed))

    classwise: dict[str, Any] = {}
    for sign in SIGNS:
        actual_count = sum(confusion[sign][predicted] for predicted in SIGNS)
        predicted_count = sum(confusion[actual][sign] for actual in SIGNS)
        true_positive = confusion[sign][sign]
        false_positive = predicted_count - true_positive
        false_negative = actual_count - true_positive
        precision = _ratio(true_positive, predicted_count)
        recall = _ratio(true_positive, actual_count)
        f1 = (
            2.0 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall
            else None
        )
        prevalence = _ratio(actual_count, n)
        mean_probability = _ratio_float(probability_sums[sign], n)
        reliability_bins: list[dict[str, float | int]] = []
        ece = 0.0
        if include_bins and n:
            for index, values in enumerate(bin_rows[sign]):
                if not values:
                    continue
                mean_p = sum(value[0] for value in values) / len(values)
                observed_rate = sum(value[1] for value in values) / len(values)
                ece += len(values) / n * abs(mean_p - observed_rate)
                reliability_bins.append(
                    {
                        "lower": index / 10,
                        "upper": (index + 1) / 10,
                        "n": len(values),
                        "mean_probability": mean_p,
                        "observed_frequency": observed_rate,
                    }
                )
        classwise[sign] = {
            "actual_count": actual_count,
            "predicted_count": predicted_count,
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "prevalence": prevalence,
            "mean_probability": mean_probability,
            "probability_bias": (
                mean_probability - prevalence
                if mean_probability is not None and prevalence is not None
                else None
            ),
            "binary_brier": _ratio_float(binary_brier_sums[sign], n),
            "binary_logloss": _ratio_float(binary_logloss_sums[sign], n),
            "ece": ece if include_bins and n else None,
            "reliability_bins": reliability_bins,
        }

    return {
        "n": n,
        "accuracy": _ratio(correct, n),
        "brier": _ratio_float(multiclass_brier, n),
        "logloss": _ratio_float(multiclass_logloss, n),
        "top_two_candidate_coverage": {
            "empirical_coverage": _ratio(top_two_covered, n),
            "draw_coverage": _ratio(draw_top_two_covered, draw_count),
            "draw_count": draw_count,
            "mean_probability_mass": _ratio_float(top_two_probability_mass, n),
        },
        "confusion_matrix": confusion,
        "classwise": classwise,
    }


def _ratio_float(numerator: float, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _pairwise_comparison(
    rows: list[dict[str, Any]],
    left: str,
    right: str,
) -> dict[str, Any]:
    both_correct = left_only = right_only = both_wrong = disagreements = 0
    for row in rows:
        left_prediction = _predicted_sign(row, left)
        right_prediction = _predicted_sign(row, right)
        actual = row["actual_result"]
        disagreements += left_prediction != right_prediction
        left_correct = left_prediction == actual
        right_correct = right_prediction == actual
        if left_correct and right_correct:
            both_correct += 1
        elif left_correct:
            left_only += 1
        elif right_correct:
            right_only += 1
        else:
            both_wrong += 1
    return {
        "left": left,
        "right": right,
        "n": len(rows),
        "sign_disagreements": disagreements,
        "disagreement_rate": _ratio(disagreements, len(rows)),
        "both_correct": both_correct,
        "left_only_correct": left_only,
        "right_only_correct": right_only,
        "both_wrong": both_wrong,
    }



def _paired_cluster_bootstrap(
    rows: list[dict[str, Any]],
    mode: str,
    *,
    bootstrap_samples: int,
    seed_material: str,
    minimum_clusters: int = 8,
) -> dict[str, Any]:
    """Estimate paired model-minus-market uncertainty by ISO-week cluster bootstrap."""
    cluster_totals: dict[str, list[float]] = {}
    for row in rows:
        forecast_date = date.fromisoformat(row["forecast_as_of_date"])
        iso = forecast_date.isocalendar()
        cluster = f"{iso.year}-W{iso.week:02d}"
        totals = cluster_totals.setdefault(cluster, [0.0, 0.0, 0.0, 0.0])

        actual = row["actual_result"]
        model_probabilities = _probability_vector(row, mode)
        market_probabilities = _probability_vector(row, "market")
        model_brier = sum(
            (model_probabilities[sign] - float(sign == actual)) ** 2 for sign in SIGNS
        )
        market_brier = sum(
            (market_probabilities[sign] - float(sign == actual)) ** 2 for sign in SIGNS
        )
        model_logloss = -math.log(max(model_probabilities[actual], 1e-15))
        market_logloss = -math.log(max(market_probabilities[actual], 1e-15))
        model_correct = float(_predicted_sign(row, mode) == actual)
        market_correct = float(_predicted_sign(row, "market") == actual)

        totals[0] += model_brier - market_brier
        totals[1] += model_logloss - market_logloss
        totals[2] += model_correct - market_correct
        totals[3] += 1.0

    clusters = sorted(cluster_totals)
    cluster_count = len(clusters)
    if cluster_count < minimum_clusters:
        return {
            "status": "insufficient_clusters",
            "cluster_unit": "iso_calendar_week",
            "cluster_count": cluster_count,
            "minimum_clusters": minimum_clusters,
            "bootstrap_samples": bootstrap_samples,
            "confidence_interval_95": None,
        }

    totals_matrix = np.asarray(
        [cluster_totals[cluster] for cluster in clusters],
        dtype=np.float64,
    )
    observed_sums = totals_matrix.sum(axis=0)
    observed = observed_sums[:3] / observed_sums[3]

    seed = int.from_bytes(
        hashlib.sha256(seed_material.encode("utf-8")).digest()[:8],
        byteorder="big",
    )
    rng = np.random.default_rng(seed)
    bootstrap_means = np.empty((bootstrap_samples, 3), dtype=np.float64)
    batch_size = 1_000
    for start in range(0, bootstrap_samples, batch_size):
        stop = min(start + batch_size, bootstrap_samples)
        indices = rng.integers(
            0,
            cluster_count,
            size=(stop - start, cluster_count),
            dtype=np.int32,
        )
        sampled_sums = totals_matrix[indices].sum(axis=1)
        bootstrap_means[start:stop] = sampled_sums[:, :3] / sampled_sums[:, 3, None]

    lower, upper = np.quantile(bootstrap_means, [0.025, 0.975], axis=0)
    return {
        "status": "ok",
        "cluster_unit": "iso_calendar_week",
        "cluster_count": cluster_count,
        "bootstrap_samples": bootstrap_samples,
        "seed": seed,
        "delta_vs_market": {
            "brier": float(observed[0]),
            "logloss": float(observed[1]),
            "accuracy": float(observed[2]),
        },
        "confidence_interval_95": {
            metric: {
                "lower": float(lower[index]),
                "upper": float(upper[index]),
            }
            for index, metric in enumerate(("brier", "logloss", "accuracy"))
        },
        "method": (
            "Paired percentile cluster bootstrap: ISO calendar weeks are sampled "
            "with replacement and all eligible fixtures in each sampled week are "
            "retained. Intervals are exploratory and are not adjusted for multiple "
            "comparisons."
        ),
    }

def _market_common_comparison(
    rows: list[dict[str, Any]],
    model_modes: list[str],
    *,
    min_n: int = 1,
    bootstrap_samples: int = 10_000,
    seed_material: str = "",
) -> dict[str, Any]:
    """Compare every model with the market on the exact same eligible fixtures."""
    market_rows = [
        row
        for row in rows
        if row.get("market_eligible") is True
        and row.get("market_probabilities") is not None
    ]
    n = len(market_rows)
    comparison: dict[str, Any] = {
        "n": n,
        "minimum_n": min_n,
        "status": "ok" if n >= min_n else "below_minimum",
        "market": None,
        "models": {},
    }
    if n < min_n:
        return comparison

    market_metrics = _metrics(market_rows, "market")
    comparison["market"] = market_metrics
    for mode in model_modes:
        model_metrics = _metrics(market_rows, mode)
        comparison["models"][mode] = {
            "metrics": model_metrics,
            "delta_vs_market": {
                "accuracy": model_metrics["accuracy"] - market_metrics["accuracy"],
                "brier": model_metrics["brier"] - market_metrics["brier"],
                "logloss": model_metrics["logloss"] - market_metrics["logloss"],
            },
            "sign_comparison": _pairwise_comparison(market_rows, mode, "market"),
            "paired_uncertainty": _paired_cluster_bootstrap(
                market_rows,
                mode,
                bootstrap_samples=bootstrap_samples,
                seed_material=f"{seed_material}|{mode}",
            ),
        }
    return comparison


def analyze_prediction_rows(
    manifest: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    min_segment_n: int = 100,
    bootstrap_samples: int = 10_000,
) -> dict[str, Any]:
    """Build descriptive error diagnostics from archived OOS fixture forecasts."""
    if (
        isinstance(min_segment_n, bool)
        or not isinstance(min_segment_n, int)
        or min_segment_n < 1
    ):
        raise ValueError("min_segment_n must be a positive integer")
    if (
        isinstance(bootstrap_samples, bool)
        or not isinstance(bootstrap_samples, int)
        or bootstrap_samples < 100
    ):
        raise ValueError("bootstrap_samples must be an integer of at least 100")
    if not rows:
        raise ValueError("prediction diagnostics require at least one forecast row")

    model_modes = manifest.get("model_modes")
    if not isinstance(model_modes, list) or not model_modes:
        raise ValueError("manifest must define model_modes")

    models = {mode: _metrics(rows, mode) for mode in model_modes}

    pairwise = [
        _pairwise_comparison(rows, left, right)
        for index, left in enumerate(model_modes)
        for right in model_modes[index + 1 :]
    ]

    segments: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        competition = str(row.get("competition") or row.get("division") or "unknown")
        season = str(row.get("season_label") or row.get("season_code") or "unknown")
        segments[(competition, season)].append(row)

    segment_reports: list[dict[str, Any]] = []
    for (competition, season), segment_rows in sorted(segments.items()):
        if len(segment_rows) < min_segment_n:
            continue
        segment_reports.append(
            {
                "competition": competition,
                "season": season,
                "n": len(segment_rows),
                "models": {
                    mode: _metrics(segment_rows, mode, include_bins=False)
                    for mode in model_modes
                },
                "market_common_sample": _market_common_comparison(
                    segment_rows,
                    model_modes,
                    min_n=min_segment_n,
                    bootstrap_samples=bootstrap_samples,
                    seed_material=(
                        f"{manifest.get('run_id')}|{competition}|{season}"
                    ),
                ),
            }
        )

    market_comparison = _market_common_comparison(
        rows,
        model_modes,
        bootstrap_samples=bootstrap_samples,
        seed_material=f"{manifest.get('run_id')}|overall",
    )

    return {
        "schema_version": 1,
        "source": {
            "run_id": manifest.get("run_id"),
            "code_revision": manifest.get("code_revision"),
            "dataset_sha256": manifest.get("dataset_sha256"),
            "forecast_count": len(rows),
            "forecast_start_date": manifest.get("forecast_start_date"),
            "forecast_end_date": manifest.get("forecast_end_date"),
            "generated_at_utc": manifest.get("generated_at_utc"),
            "model_modes": model_modes,
        },
        "overall": models,
        "model_pairwise": pairwise,
        "market_common_sample": market_comparison,
        "segments": {
            "minimum_n": min_segment_n,
            "groups": segment_reports,
        },
        "interpretation": {
            "scope": "descriptive out-of-sample diagnostics; no causal claims or significance tests",
            "draw_sign": "X precision and recall refer to the single most-probable sign, not double coverage",
            "market": "market comparisons use only rows marked market_eligible by the existing temporal screen",
            "uncertainty": (
                "paired 95% percentile cluster-bootstrap intervals resample ISO weeks; "
                "they are exploratory and are not adjusted for multiple comparisons"
            ),
        },
    }
