from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

SIGNS = ("1", "X", "2")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _valid_probability_vector(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != set(SIGNS):
        return False
    probabilities: list[float] = []
    for sign in SIGNS:
        raw = value[sign]
        if isinstance(raw, bool):
            return False
        try:
            probability = float(raw)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            return False
        probabilities.append(probability)
    return math.isclose(sum(probabilities), 1.0, rel_tol=0.0, abs_tol=1e-6)


def _iso_date(value: Any, field: str, row_index: int) -> date:
    if not isinstance(value, str):
        raise TypeError(f"forecast row {row_index}: {field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"forecast row {row_index}: {field} must be an ISO date"
        ) from exc


def _validate_manifest(manifest: dict[str, Any], row_count: int) -> None:
    if manifest.get("schema_version") != 1:
        raise ValueError("prediction ledger manifest schema_version must be 1")
    dataset_hash = manifest.get("dataset_sha256")
    if not isinstance(dataset_hash, str) or not _SHA256_RE.fullmatch(dataset_hash):
        raise ValueError("prediction ledger manifest requires a SHA-256 dataset hash")
    revision = manifest.get("code_revision")
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError("prediction ledger manifest requires a code revision")
    generated_at = manifest.get("generated_at_utc")
    if not isinstance(generated_at, str):
        raise TypeError("prediction ledger manifest requires generated_at_utc")
    try:
        generated = datetime.fromisoformat(generated_at)
    except ValueError as exc:
        raise ValueError("prediction ledger generated_at_utc is invalid") from exc
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise ValueError("prediction ledger generated_at_utc must be timezone-aware")
    forecast_count = manifest.get("forecast_count")
    if (
        isinstance(forecast_count, bool)
        or not isinstance(forecast_count, int)
        or forecast_count != row_count
    ):
        raise ValueError("prediction ledger manifest forecast_count disagrees with rows")
    model_modes = manifest.get("model_modes")
    if not isinstance(model_modes, list) or not model_modes or any(
        not isinstance(mode, str) or not mode.strip() for mode in model_modes
    ):
        raise ValueError("prediction ledger manifest model_modes must be a non-empty list")


def _validate_forecast_row(row: dict[str, Any], row_index: int) -> None:
    fixture_id = row.get("fixture_id")
    if not isinstance(fixture_id, str) or not _SHA256_RE.fullmatch(fixture_id):
        raise ValueError(f"forecast row {row_index}: fixture_id must be a SHA-256 key")
    forecast_date = _iso_date(
        row.get("forecast_as_of_date"), "forecast_as_of_date", row_index
    )
    for field in ("training_cutoff_date", "model_fit_cutoff_date"):
        cutoff = _iso_date(row.get(field), field, row_index)
        if cutoff >= forecast_date:
            raise ValueError(
                f"forecast row {row_index}: {field} must precede forecast_as_of_date"
            )
    for field in ("training_match_count", "model_fit_match_count", "forecast_index"):
        value = row.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"forecast row {row_index}: {field} must be a positive integer")
    if row["model_fit_match_count"] > row["training_match_count"]:
        raise ValueError(
            f"forecast row {row_index}: model fit sample exceeds available training history"
        )
    if row.get("actual_result") not in SIGNS:
        raise ValueError(f"forecast row {row_index}: invalid actual_result")
    for field in ("home", "away"):
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"forecast row {row_index}: {field} is required")

    model_probabilities = row.get("model_probabilities")
    if not isinstance(model_probabilities, dict) or not model_probabilities:
        raise ValueError(f"forecast row {row_index}: model_probabilities are required")
    for mode, probabilities in model_probabilities.items():
        if not isinstance(mode, str) or not _valid_probability_vector(probabilities):
            raise ValueError(
                f"forecast row {row_index}: invalid probability vector for model {mode!r}"
            )

    for eligibility_field, probability_field in (
        ("market_eligible", "market_probabilities"),
        ("lae_eligible", "lae_probabilities"),
    ):
        eligible = row.get(eligibility_field)
        probabilities = row.get(probability_field)
        if not isinstance(eligible, bool):
            raise TypeError(
                f"forecast row {row_index}: {eligibility_field} must be boolean"
            )
        if eligible and not _valid_probability_vector(probabilities):
            raise ValueError(
                f"forecast row {row_index}: eligible {probability_field} are invalid"
            )
        if not eligible and probabilities is not None:
            raise ValueError(
                f"forecast row {row_index}: ineligible {probability_field} must be null"
            )

    bet365 = row.get("bet365_probabilities")
    if bet365 is not None and not _valid_probability_vector(bet365):
        raise ValueError(f"forecast row {row_index}: invalid Bet365 probability vector")


def write_prediction_ledger(
    path: str | Path,
    manifest: dict[str, Any],
    forecast_rows: list[dict[str, Any]],
) -> int:
    """Write one immutable JSONL run ledger; existing files are never overwritten."""
    if not isinstance(manifest, dict):
        raise TypeError("prediction ledger manifest must be a dictionary")
    if not isinstance(forecast_rows, list) or not forecast_rows:
        raise ValueError("prediction ledger must contain at least one forecast row")

    _validate_manifest(manifest, len(forecast_rows))
    seen_fixture_ids: set[str] = set()
    for index, row in enumerate(forecast_rows, start=1):
        if not isinstance(row, dict):
            raise TypeError(f"forecast row {index} must be a dictionary")
        _validate_forecast_row(row, index)
        fixture_id = row["fixture_id"]
        if fixture_id in seen_fixture_ids:
            raise ValueError(f"duplicate fixture_id in prediction ledger: {fixture_id}")
        seen_fixture_ids.add(fixture_id)
        model_modes = set(manifest["model_modes"])
        if not model_modes.issubset(row["model_probabilities"]):
            missing = sorted(model_modes - set(row["model_probabilities"]))
            raise ValueError(
                f"forecast row {index} is missing model probability vectors: {missing}"
            )

    records = [
        {"record_type": "run_manifest", **manifest},
        *({"record_type": "forecast", **row} for row in forecast_rows),
    ]
    serialized = [
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        for record in records
    ]

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(serialized))
        stream.write("\n")
    return len(forecast_rows)
