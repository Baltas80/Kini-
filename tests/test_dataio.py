from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from kini_engine.core import Match
from kini_engine.dataio import (
    build_dataset_profile,
    load_matches_csv,
    validate_matches,
)


def test_load_h_d_a_csv(tmp_path: Path):
    p = tmp_path / "matches.csv"
    p.write_text(
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        "2025-01-01,A,B,2,0,H\n"
        "2025-01-02,C,D,1,1,D\n"
        "2025-01-03,B,C,0,2,A\n",
        encoding="utf-8",
    )
    matches = load_matches_csv(p)
    validate_matches(matches)
    assert [m.result for m in matches] == ["1", "X", "2"]


def test_validate_rejects_incomplete_score():
    with pytest.raises(ValueError, match="incomplete score"):
        validate_matches([Match("2025-01-01", "A", "B", 1, None)])


def test_validate_rejects_invalid_date():
    with pytest.raises(ValueError, match="invalid date"):
        validate_matches([Match("not-a-date", "A", "B", 1, 0, "1")])


def test_validate_rejects_duplicate_fixture():
    matches = [
        Match("01/01/2025", "A", "B", 1, 0, "1", detail={"Div": "SP1"}),
        Match("2025-01-01", " a ", "b", 2, 0, "1", detail={"Div": "SP1"}),
    ]
    with pytest.raises(ValueError, match="duplicate fixture"):
        validate_matches(matches)


def test_validate_rejects_result_score_mismatch():
    with pytest.raises(ValueError, match="conflicts with score"):
        validate_matches([Match("2025-01-01", "A", "B", 2, 0, "2")])


def test_validate_rejects_missing_final_score():
    with pytest.raises(ValueError, match="missing final score"):
        validate_matches([Match("2025-01-01", "A", "B", None, None, "1")])


def test_load_rejects_unknown_result_and_fractional_goals(tmp_path: Path):
    p = tmp_path / "bad.csv"
    p.write_text(
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        "2025-01-01,A,B,1.5,0,H\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="non-negative integer"):
        load_matches_csv(p)

    p.write_text(
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        "2025-01-01,A,B,1,0,HOME\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown FTR"):
        load_matches_csv(p)


def test_market_probabilities_remove_overround(tmp_path: Path):
    p = tmp_path / "odds.csv"
    p.write_text(
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A\n"
        "2025-01-01,A,B,1,0,H,2.0,3.5,4.0\n",
        encoding="utf-8",
    )
    matches = load_matches_csv(p)
    assert matches[0].market is not None
    assert abs(sum(matches[0].market.values()) - 1.0) < 1e-12


def test_dataset_profile_records_coverage_quality_and_sources():
    raw = pd.DataFrame([
        {"Date": "01/01/25", "HomeTeam": "A", "AwayTeam": "B", "FTHG": 1, "FTAG": 0, "FTR": "H", "Div": "SP1", "League": "la-liga", "Season": "2425"},
        {"Date": "01/01/25", "HomeTeam": "A", "AwayTeam": "B", "FTHG": 1, "FTAG": 0, "FTR": "H", "Div": "SP1", "League": "la-liga", "Season": "2425"},
        {"Date": "bad-date", "HomeTeam": "C", "AwayTeam": "D", "FTHG": 0, "FTAG": 2, "FTR": "H", "Div": "SP2", "League": "segunda", "Season": "2425"},
    ])
    final = raw.iloc[:1].copy()
    profile = build_dataset_profile(
        raw,
        final,
        ["https://example.test/SP1.csv"],
        retrieved_at=datetime(2026, 11, 14, tzinfo=timezone.utc),
    )
    assert profile["rows_before_filter"] == 3
    assert profile["rows_after_filter"] == 1
    assert profile["duplicate_fixtures"] == 1
    assert profile["date_coverage"]["invalid_or_missing"] == 1
    assert profile["score_result_mismatches"] == 1
    assert profile["source_urls"] == ["https://example.test/SP1.csv"]
