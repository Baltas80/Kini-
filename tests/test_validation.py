import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kini_engine.validation import (
    ValidationReport,
    canonical_payload_hash,
    load_expected_rounds,
    validate_dataset,
)


RELEASE = Path("data/historical/releases/demo-v1")
AS_OF = datetime(2025, 1, 12, 23, 59, tzinfo=timezone.utc)
KNOWN_TEAMS = {"team:A", "team:B", "team:C", "team:D"}
EXPECTED_ROUNDS = {
    ("demo_competition", "2024-25", 1): 2,
    ("demo_competition", "2024-25", 2): 2,
    ("demo_competition", "2024-25", 3): 2,
    ("demo_competition", "2024-25", 4): 2,
    ("demo_competition", "2024-25", 5): 2,
    ("demo_competition", "2024-25", 6): 2,
}


def validate(matches=RELEASE / "matches.csv", observations=RELEASE / "observations.jsonl", **overrides):
    return validate_dataset(
        matches,
        observations,
        as_of=AS_OF,
        known_team_ids=KNOWN_TEAMS,
        expected_rounds=EXPECTED_ROUNDS,
        **overrides,
    )


def test_demo_dataset_passes_all_validation_controls():
    report = validate()
    assert isinstance(report, ValidationReport)
    assert report.valid
    assert all(status == "pass" for status in report.checks.values())
    assert report.counts == {"matches": 12, "observations": 12, "errors": 0}


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("match_id", "demo_001", "duplicate_match_id"),
        ("home_team_id", "team:UNKNOWN", "unknown_team"),
        ("home_team_id", "team:A", "impossible_match"),
        ("result_1x2", "2", "result_mismatch"),
        ("kickoff_at", "2025-12-01T00:00:00Z", "future_match"),
        ("round_number", "0", "invalid_round"),
    ],
)
def test_match_validation_detects_corrupt_records(tmp_path, field, value, code):
    rows = (RELEASE / "matches.csv").read_text(encoding="utf-8").splitlines()
    header = rows[0].split(",")
    first = rows[1].split(",")
    if field == "match_id":
        second = rows[2].split(",")
        second[header.index(field)] = value
        rows[2] = ",".join(second)
    else:
        first[header.index(field)] = value
        if field == "home_team_id" and value == "team:A":
            first[header.index("away_team_id")] = "team:A"
        if field == "result_1x2":
            first[header.index("home_goals")] = "2"
            first[header.index("away_goals")] = "0"
        rows[1] = ",".join(first)
    path = tmp_path / "matches.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    report = validate(matches=path, observations=None)
    assert not report.valid
    assert code in {issue.code for issue in report.issues}


def test_round_date_order_is_detected(tmp_path):
    rows = (RELEASE / "matches.csv").read_text(encoding="utf-8").splitlines()
    header = rows[0].split(",")
    round_two = rows[3].split(",")
    round_two[header.index("kickoff_at")] = "2024-12-01T00:00:00Z"
    rows[3] = ",".join(round_two)
    path = tmp_path / "matches.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    report = validate(matches=path, observations=None)
    assert not report.valid
    assert "round_date_order" in {issue.code for issue in report.issues}


def test_incomplete_round_is_detected(tmp_path):
    rows = (RELEASE / "matches.csv").read_text(encoding="utf-8").splitlines()
    path = tmp_path / "matches.csv"
    path.write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")
    report = validate(matches=path, observations=None)
    assert not report.valid
    assert "incomplete_round" in {issue.code for issue in report.issues}


def test_future_observation_is_detected(tmp_path):
    observations = [
        json.loads(line)
        for line in (RELEASE / "observations.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    observations[0]["captured_at"] = "2025-01-13T00:00:00Z"
    path = tmp_path / "observations.jsonl"
    path.write_text(
        "\n".join(json.dumps(obs, ensure_ascii=False, separators=(",", ":")) for obs in observations) + "\n",
        encoding="utf-8",
    )
    report = validate(observations=path)
    assert not report.valid
    assert "future_observation" in {issue.code for issue in report.issues}


def test_expected_rounds_loader():
    path = Path("/tmp/kini-expected-rounds.json")
    path.write_text(
        json.dumps({"competitions": {"demo_competition": {"2024-25": {"1": 2}}}}),
        encoding="utf-8",
    )
    try:
        assert load_expected_rounds(path) == {("demo_competition", "2024-25", 1): 2}
    finally:
        path.unlink(missing_ok=True)
