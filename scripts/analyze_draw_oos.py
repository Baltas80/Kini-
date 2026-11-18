#!/usr/bin/env python3
"""Reproducible OOS draw diagnostics for snapshot-aligned prediction ledgers."""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from kini_engine.ledger import read_prediction_ledger

SIGNS = ("1", "X", "2")


def validate_snapshot_alignment(
    manifest: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Reject ordinary daily ledgers and enforce the snapshot training contract."""
    required_modes = set(manifest["model_modes"])
    if not rows:
        raise ValueError("snapshot-aligned ledger contains no forecast rows")
    seen_snapshots: dict[str, str] = {}
    seen_fixtures: set[str] = set()
    months: set[str] = set()
    for index, row in enumerate(rows, start=1):
        fixture_id = row["fixture_id"]
        if fixture_id in seen_fixtures:
            raise ValueError(f"duplicate fixture_id at forecast row {index}")
        seen_fixtures.add(fixture_id)
        snapshot_raw = row.get("market_snapshot_date")
        fixture_raw = row.get("fixture_date")
        if not isinstance(snapshot_raw, str) or not isinstance(fixture_raw, str):
            raise ValueError(
                f"forecast row {index} is not snapshot-aligned: "
                "market_snapshot_date and fixture_date are required"
            )
        snapshot = date.fromisoformat(snapshot_raw)
        fixture = date.fromisoformat(fixture_raw)
        forecast_as_of = date.fromisoformat(row["forecast_as_of_date"])
        training_cutoff = date.fromisoformat(row["training_cutoff_date"])
        fit_cutoff = date.fromisoformat(row["model_fit_cutoff_date"])
        if not (snapshot == forecast_as_of < fixture):
            raise ValueError(
                f"forecast row {index} violates forecast/snapshot/fixture date order"
            )
        if training_cutoff >= snapshot or fit_cutoff >= snapshot:
            raise ValueError(
                f"forecast row {index} includes same-day or future training data"
            )
        if row.get("market_eligible") is not True:
            raise ValueError(
                f"forecast row {index} is not market-eligible in snapshot sample"
            )
        if not isinstance(row.get("market_probabilities"), dict):
            raise ValueError(f"forecast row {index} has no market probability vector")
        if not required_modes.issubset(row["model_probabilities"]):
            raise ValueError(f"forecast row {index} is missing a manifest model mode")
        if row.get("model_fit_count_for_snapshot") != 1:
            raise ValueError(f"forecast row {index} does not reference one snapshot fit")
        if row.get("training_history_sha256") is None:
            raise ValueError(f"forecast row {index} has no training-history fingerprint")
        fingerprint = str(row["training_history_sha256"])
        previous = seen_snapshots.setdefault(snapshot_raw, fingerprint)
        if previous != fingerprint:
            raise ValueError(
                f"snapshot {snapshot_raw} contains inconsistent training fingerprints"
            )
        months.add(snapshot_raw[:7])
    return {
        "n": len(rows),
        "snapshot_dates": len(seen_snapshots),
        "months": sorted(months),
        "fixture_ids": seen_fixtures,
    }


def wilson(successes: int, trials: int, z: float = 1.959963984540054) -> list[float] | None:
    if trials == 0:
        return None
    p = successes / trials
    denominator = 1.0 + z * z / trials
    center = (p + z * z / (2.0 * trials)) / denominator
    radius = z * math.sqrt(
        p * (1.0 - p) / trials + z * z / (4.0 * trials * trials)
    ) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def _ranked_signs(probabilities: dict[str, float]) -> list[str]:
    # Stable tie-break is explicit and shared by models and market.
    return sorted(SIGNS, key=lambda sign: (-probabilities[sign], SIGNS.index(sign)))


def _binary_scores(probabilities: np.ndarray, outcomes: np.ndarray) -> tuple[float, float]:
    clipped = np.clip(probabilities, 1e-15, 1.0 - 1e-15)
    brier = float(np.mean((clipped - outcomes) ** 2))
    logloss = float(
        -np.mean(
            outcomes * np.log(clipped)
            + (1.0 - outcomes) * np.log1p(-clipped)
        )
    )
    return brier, logloss


def _selection_metrics(
    vectors: list[dict[str, float]], outcomes: np.ndarray, top_k: int
) -> dict[str, Any]:
    selected = np.asarray(
        ["X" in _ranked_signs(vector)[:top_k] for vector in vectors], dtype=bool
    )
    actual_draws = outcomes.astype(bool)
    hits = int(np.sum(selected & actual_draws))
    n_selected = int(selected.sum())
    n_draws = int(actual_draws.sum())
    return {
        "selected": n_selected,
        "hits": hits,
        "precision": hits / n_selected if n_selected else None,
        "precision_wilson95": wilson(hits, n_selected),
        "recall": hits / n_draws if n_draws else None,
        "recall_wilson95": wilson(hits, n_draws),
    }


def _calibration_bins(
    probabilities: np.ndarray, outcomes: np.ndarray, bins: int
) -> list[dict[str, Any]]:
    edges = np.linspace(0.0, 1.0, bins + 1)
    result = []
    for index, (lower, upper) in enumerate(zip(edges[:-1], edges[1:])):
        mask = (probabilities >= lower) & (
            (probabilities < upper) | ((index == bins - 1) & (probabilities <= upper))
        )
        count = int(mask.sum())
        if count:
            result.append(
                {
                    "lower": float(lower),
                    "upper": float(upper),
                    "n": count,
                    "mean_p_x": float(probabilities[mask].mean()),
                    "observed_x": float(outcomes[mask].mean()),
                }
            )
    return result


def _metrics(
    vectors: list[dict[str, float]], outcomes: np.ndarray, bins: int
) -> dict[str, Any]:
    px = np.asarray([vector["X"] for vector in vectors], dtype=float)
    brier, logloss = _binary_scores(px, outcomes)
    return {
        "n": len(outcomes),
        "draw_rate": float(outcomes.mean()),
        "mean_p_x": float(px.mean()),
        "brier_x": brier,
        "logloss_x": logloss,
        "top1": _selection_metrics(vectors, outcomes, 1),
        "top2": _selection_metrics(vectors, outcomes, 2),
        "calibration_bins": _calibration_bins(px, outcomes, bins),
    }


def paired_block_bootstrap(
    model_probabilities: np.ndarray,
    market_probabilities: np.ndarray,
    outcomes: np.ndarray,
    month_labels: np.ndarray,
    samples: int = 5000,
    seed: int = 20261118,
) -> dict[str, Any]:
    """Paired bootstrap of complete calendar-month blocks."""
    if samples < 100:
        raise ValueError("bootstrap samples must be at least 100")
    months = np.unique(month_labels)
    if len(months) < 2:
        raise ValueError("at least two calendar-month blocks are required")
    blocks = {month: np.flatnonzero(month_labels == month) for month in months}
    rng = np.random.default_rng(seed)
    brier_deltas = np.empty(samples, dtype=float)
    logloss_deltas = np.empty(samples, dtype=float)
    for iteration in range(samples):
        chosen_months = rng.choice(months, size=len(months), replace=True)
        indices = np.concatenate([blocks[month] for month in chosen_months])
        model_brier, model_logloss = _binary_scores(
            model_probabilities[indices], outcomes[indices]
        )
        market_brier, market_logloss = _binary_scores(
            market_probabilities[indices], outcomes[indices]
        )
        brier_deltas[iteration] = model_brier - market_brier
        logloss_deltas[iteration] = model_logloss - market_logloss
    return {
        "unit": "calendar_month",
        "blocks": int(len(months)),
        "replicates": samples,
        "seed": seed,
        "delta_brier_model_minus_market_ci95": [
            float(value) for value in np.quantile(brier_deltas, [0.025, 0.975])
        ],
        "delta_logloss_model_minus_market_ci95": [
            float(value) for value in np.quantile(logloss_deltas, [0.025, 0.975])
        ],
    }


def analyze(
    manifest: dict[str, Any],
    rows: list[dict[str, Any]],
    bins: int = 10,
    bootstrap_samples: int = 5000,
    seed: int = 20261118,
) -> dict[str, Any]:
    alignment = validate_snapshot_alignment(manifest, rows)
    ordered = sorted(
        rows,
        key=lambda row: (
            row["market_snapshot_date"],
            row["fixture_date"],
            row["fixture_id"],
        ),
    )
    outcomes = np.asarray(
        [int(row["actual_result"] == "X") for row in ordered], dtype=float
    )
    market_vectors = [row["market_probabilities"] for row in ordered]
    market = _metrics(market_vectors, outcomes, bins)
    month_labels = np.asarray(
        [row["market_snapshot_date"][:7] for row in ordered], dtype=str
    )
    modes = sorted(manifest["model_modes"])
    diagnostics: dict[str, Any] = {}
    for mode in modes:
        vectors = [row["model_probabilities"][mode] for row in ordered]
        metrics = _metrics(vectors, outcomes, bins)
        model_px = np.asarray([vector["X"] for vector in vectors], dtype=float)
        market_px = np.asarray([vector["X"] for vector in market_vectors], dtype=float)
        bootstrap = paired_block_bootstrap(
            model_px, market_px, outcomes, month_labels, bootstrap_samples, seed
        )
        metrics["paired_market"] = {
            "n": len(ordered),
            "delta_brier_model_minus_market": metrics["brier_x"] - market["brier_x"],
            "delta_logloss_model_minus_market": (
                metrics["logloss_x"] - market["logloss_x"]
            ),
            "bootstrap": bootstrap,
        }
        diagnostics[mode] = metrics

    segmentations: dict[str, Any] = {}
    for field in ("competition", "season_label"):
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in ordered:
            value = row.get(field)
            if value is not None:
                grouped[str(value)].append(row)
        segmentations[field] = {}
        for label, group in sorted(grouped.items()):
            if len(group) < 30:
                continue
            group_outcomes = np.asarray(
                [int(row["actual_result"] == "X") for row in group], dtype=float
            )
            segmentations[field][label] = {
                "n": len(group),
                "draw_rate": float(group_outcomes.mean()),
                "market": _metrics(
                    [row["market_probabilities"] for row in group],
                    group_outcomes,
                    bins,
                ),
                "models": {
                    mode: _metrics(
                        [row["model_probabilities"][mode] for row in group],
                        group_outcomes,
                        bins,
                    )
                    for mode in modes
                },
            }

    return {
        "schema_version": 2,
        "source": {
            "ledger_type": "snapshot_aligned",
            "code_revision": manifest.get("code_revision"),
            "dataset_sha256": manifest.get("dataset_sha256"),
            "forecast_start_date": manifest.get("forecast_start_date"),
            "forecast_end_date": manifest.get("forecast_end_date"),
            "forecast_count": manifest.get("forecast_count"),
        },
        "sample": {
            "n": len(ordered),
            "draws": int(outcomes.sum()),
            "draw_rate": float(outcomes.mean()),
            "snapshot_dates": alignment["snapshot_dates"],
            "calendar_month_blocks": len(alignment["months"]),
        },
        "market": market,
        "models": diagnostics,
        "segments": segmentations,
        "method": {
            "market_comparison": "identical snapshot-aligned fixture IDs",
            "training_cutoff": "strictly before market snapshot date",
            "bootstrap": "paired calendar-month block bootstrap",
            "tie_break": "1, then X, then 2",
        },
        "limitations": [
            "Snapshot alignment is by documented calendar date, not exact intraday odds-capture timestamp.",
            "xG, strength and DC/ML disagreement are not inferred when absent from ledger rows.",
            "No payout, ROI or ticket-optimization claim is made.",
            "Bootstrap intervals are conditional on this sample and block definition.",
        ],
    }


def write_report(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "draw_diagnostic.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# OOS draw (X) diagnostic",
        "",
        f"- Fixtures: {report['sample']['n']}",
        f"- Draws: {report['sample']['draws']} ({report['sample']['draw_rate']:.2%})",
        f"- Snapshot dates: {report['sample']['snapshot_dates']}",
        f"- Calendar-month bootstrap blocks: {report['sample']['calendar_month_blocks']}",
        "",
        "## P(X) metrics",
        "",
        "| Mode | Brier X | Log loss X | Mean P(X) | Top-1 precision | Top-1 recall | Top-2 recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Market | {report['market']['brier_x']:.5f} | {report['market']['logloss_x']:.5f} | {report['market']['mean_p_x']:.2%} | {report['market']['top1']['precision']!s} | {report['market']['top1']['recall']!s} | {report['market']['top2']['recall']!s} |",
    ]
    for mode, metrics in report["models"].items():
        lines.append(
            f"| {mode} | {metrics['brier_x']:.5f} | {metrics['logloss_x']:.5f} | "
            f"{metrics['mean_p_x']:.2%} | {metrics['top1']['precision']!s} | "
            f"{metrics['top1']['recall']!s} | {metrics['top2']['recall']!s} |"
        )
    lines += ["", "## Paired model-versus-market block bootstrap", ""]
    lines += [
        "| Mode | Δ Brier | IC95% | Δ Log loss | IC95% |",
        "|---|---:|---:|---:|---:|",
    ]
    for mode, metrics in report["models"].items():
        paired = metrics["paired_market"]
        boot = paired["bootstrap"]
        lines.append(
            f"| {mode} | {paired['delta_brier_model_minus_market']:+.5f} | "
            f"[{boot['delta_brier_model_minus_market_ci95'][0]:+.5f}, "
            f"{boot['delta_brier_model_minus_market_ci95'][1]:+.5f}] | "
            f"{paired['delta_logloss_model_minus_market']:+.5f} | "
            f"[{boot['delta_logloss_model_minus_market_ci95'][0]:+.5f}, "
            f"{boot['delta_logloss_model_minus_market_ci95'][1]:+.5f}] |"
        )
    lines += ["", "## Limitations", ""]
    lines.extend(f"- {item}" for item in report["limitations"])
    (output_dir / "draw_diagnostic.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def run(
    ledger_path: Path,
    output_dir: Path,
    bins: int = 10,
    bootstrap_samples: int = 5000,
    seed: int = 20261118,
) -> dict[str, Any]:
    manifest, rows = read_prediction_ledger(ledger_path)
    report = analyze(manifest, rows, bins, bootstrap_samples, seed)
    report["source"]["ledger_path"] = str(ledger_path)
    write_report(report, output_dir)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path, help="snapshot-aligned immutable JSONL ledger")
    parser.add_argument("--output-dir", type=Path, default=Path("draw-diagnostic"))
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument("--bootstrap-samples", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20261118)
    args = parser.parse_args()
    if not 2 <= args.bins <= 50:
        parser.error("--bins must be between 2 and 50")
    if args.bootstrap_samples < 100:
        parser.error("--bootstrap-samples must be at least 100")
    try:
        report = run(
            args.ledger,
            args.output_dir,
            args.bins,
            args.bootstrap_samples,
            args.seed,
        )
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "rows": report["sample"]["n"],
                "models": list(report["models"]),
                "snapshot_dates": report["sample"]["snapshot_dates"],
                "outputs": [
                    str(args.output_dir / "draw_diagnostic.md"),
                    str(args.output_dir / "draw_diagnostic.json"),
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
