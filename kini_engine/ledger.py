from __future__ import annotations

import hashlib
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
        raise ValueError(
            "prediction ledger manifest forecast_count disagrees with rows"
        )
    model_modes = manifest.get("model_modes")
    if (
        not isinstance(model_modes, list)
        or not model_modes
        or any(not isinstance(mode, str) or not mode.strip() for mode in model_modes)
    ):
        raise ValueError(
            "prediction ledger manifest model_modes must be a non-empty list"
        )


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
            raise ValueError(
                f"forecast row {row_index}: {field} must be a positive integer"
            )
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


def read_prediction_ledger(
    path: str | Path,
    expected_sha256: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read and fully validate an immutable JSONL prediction-ledger artifact."""
    target = Path(path)
    try:
        payload = target.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read prediction ledger: {target}") from exc

    if expected_sha256 is not None:
        if not isinstance(expected_sha256, str) or not _SHA256_RE.fullmatch(
            expected_sha256
        ):
            raise ValueError("expected_sha256 must be a lowercase SHA-256 digest")
        actual_sha256 = hashlib.sha256(payload).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(
                "prediction ledger SHA-256 does not match the backtest manifest"
            )

    try:
        content = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("prediction ledger must be UTF-8") from exc

    lines = content.splitlines()
    if not lines:
        raise ValueError("prediction ledger is empty")
    if any(not line.strip() for line in lines):
        raise ValueError("prediction ledger contains a blank JSONL record")

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"prediction ledger line {line_number} is not valid JSON"
            ) from exc
        if not isinstance(record, dict):
            raise ValueError(
                f"prediction ledger line {line_number} must contain a JSON object"
            )
        records.append(record)

    first = records[0]
    if first.get("record_type") != "run_manifest":
        raise ValueError("prediction ledger must start with a run_manifest")
    manifest = {key: value for key, value in first.items() if key != "record_type"}

    forecast_rows: list[dict[str, Any]] = []
    seen_fixture_ids: set[str] = set()
    model_modes = set(manifest.get("model_modes", []))
    if not model_modes:
        raise ValueError("prediction ledger manifest has no model modes")

    for row_index, record in enumerate(records[1:], start=1):
        if record.get("record_type") != "forecast":
            raise ValueError(
                f"prediction ledger line {row_index + 1} is not a forecast"
            )
        row = {key: value for key, value in record.items() if key != "record_type"}
        _validate_forecast_row(row, row_index)

        fixture_id = row["fixture_id"]
        if fixture_id in seen_fixture_ids:
            raise ValueError(f"duplicate fixture_id in prediction ledger: {fixture_id}")
        seen_fixture_ids.add(fixture_id)

        missing_modes = model_modes - set(row["model_probabilities"])
        if missing_modes:
            raise ValueError(
                f"forecast row {row_index} is missing model probability vectors: "
                f"{sorted(missing_modes)}"
            )

        model_signs = row.get("model_signs")
        if not isinstance(model_signs, dict):
            raise ValueError(f"forecast row {row_index} has no model_signs mapping")
        for mode in model_modes:
            if model_signs.get(mode) not in SIGNS:
                raise ValueError(
                    f"forecast row {row_index} has an invalid sign for model {mode!r}"
                )

        forecast_rows.append(row)

    _validate_manifest(manifest, len(forecast_rows))
    return manifest, forecast_rows
