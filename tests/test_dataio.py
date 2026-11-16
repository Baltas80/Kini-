from datetime import UTC, datetime
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
        retrieved_at=datetime(2026, 11, 14, tzinfo=UTC),
    )
    assert profile["rows_before_filter"] == 3
    assert profile["rows_after_filter"] == 1
    assert profile["duplicate_fixtures"] == 1
    assert profile["date_coverage"]["invalid_or_missing"] == 1
    assert profile["score_result_mismatches"] == 1
    assert profile["source_urls"] == ["https://example.test/SP1.csv"]

def test_market_averages_preclosing_bookmakers_and_ignores_closing_columns(tmp_path: Path):
    p = tmp_path / "preclosing.csv"
    p.write_text(
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,"
        "B365H,B365D,B365A,WHH,WHD,WHA,B365CH,B365CD,B365CA\n"
        "2025-01-01,A,B,1,0,H,2.0,3.5,4.0,3.0,3.0,3.0,1.2,8.0,15.0\n",
        encoding="utf-8",
    )
    match = load_matches_csv(p)[0]
    b365 = [1 / 2.0, 1 / 3.5, 1 / 4.0]
    b365 = [value / sum(b365) for value in b365]
    william_hill = [1 / 3.0, 1 / 3.0, 1 / 3.0]
    expected = [
        (b365[index] + william_hill[index]) / 2
        for index in range(3)
    ]
    assert match.market is not None
    assert list(match.market.values()) == pytest.approx(expected)


def test_market_is_unavailable_when_only_closing_odds_exist(tmp_path: Path):
    p = tmp_path / "closing_only.csv"
    p.write_text(
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365CH,B365CD,B365CA\n"
        "2025-01-01,A,B,1,0,H,1.5,4.0,8.0\n",
        encoding="utf-8",
    )
    assert load_matches_csv(p)[0].market is None

def test_market_excludes_pinnacle_from_2025_07_23(tmp_path: Path):
    p = tmp_path / "pinnacle_cutoff.csv"
    p.write_text(
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A,PSH,PSD,PSA\n"
        "2025-07-22,A,B,1,0,H,2.0,3.5,4.0,2.2,3.2,3.6\n"
        "2025-07-23,C,D,0,1,A,2.0,3.5,4.0,2.2,3.2,3.6\n",
        encoding="utf-8",
    )
    before, after = load_matches_csv(p)
    b365 = [1 / 2.0, 1 / 3.5, 1 / 4.0]
    b365 = [value / sum(b365) for value in b365]
    pinnacle = [1 / 2.2, 1 / 3.2, 1 / 3.6]
    pinnacle = [value / sum(pinnacle) for value in pinnacle]
    expected_before = [
        (b365[index] + pinnacle[index]) / 2
        for index in range(3)
    ]
    assert list(before.market.values()) == pytest.approx(expected_before)
    assert list(after.market.values()) == pytest.approx(b365)



def test_market_timing_fails_closed_on_snapshot_collection_weekdays(tmp_path: Path):
    p = tmp_path / "market_timing.csv"
    p.write_text(
        "Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A\n"
        "2025-01-03,16:30,A,B,1,0,H,2.0,3.5,4.0\n"
        "2025-01-03,19:30,C,D,0,1,A,2.0,3.5,4.0\n"
        "2025-01-07,12:45,E,F,1,1,D,2.0,3.5,4.0\n"
        "2025-01-07,20:15,G,H,2,0,H,2.0,3.5,4.0\n"
        "2025-01-04,15:00,I,J,1,0,H,2.0,3.5,4.0\n"
        "2025-01-08,20:00,K,L,0,1,A,2.0,3.5,4.0\n",
        encoding="utf-8",
    )

    matches = load_matches_csv(p)

    assert matches[0].detail["kickoff_time"] == "16:30"
    assert matches[0].detail["kickoff_time_timezone"] == "unspecified"
    for match in matches[:4]:
        assert match.detail["market_temporal_status"] == "ambiguous"
        assert match.detail["market_pre_match_eligible"] is False
    for match in matches[4:]:
        assert match.detail["market_temporal_status"] == "schedule_compatible"
        assert match.detail["market_pre_match_eligible"] is True


def test_market_with_missing_or_unparseable_kickoff_is_not_eligible(tmp_path: Path):
    p = tmp_path / "unknown_kickoff.csv"
    p.write_text(
        "Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A\n"
        "2025-01-03,,A,B,1,0,H,2.0,3.5,4.0\n"
        "2025-01-04,TBA,C,D,0,1,A,2.0,3.5,4.0\n",
        encoding="utf-8",
    )

    matches = load_matches_csv(p)

    assert all(match.detail["market_temporal_status"] == "unknown" for match in matches)
    assert all(match.detail["market_pre_match_eligible"] is False for match in matches)



def test_loader_preserves_individual_no_vig_bookmaker_vectors(tmp_path: Path):
    path = tmp_path / "bookmaker_vectors.csv"
    path.write_text(
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,"
        "B365H,B365D,B365A,WHH,WHD,WHA,PSH,PSD,PSA\n"
        "2025-01-01,A,B,1,0,H,2.0,3.5,4.0,3.0,3.0,3.0,2.2,3.2,3.6\n",
        encoding="utf-8",
    )

    match = load_matches_csv(path)[0]
    bookmaker_vectors = match.detail["market_bookmaker_probabilities"]

    assert set(bookmaker_vectors) == {"bet365", "william_hill", "pinnacle"}
    raw_bet365 = [1 / 2.0, 1 / 3.5, 1 / 4.0]
    expected_bet365 = [value / sum(raw_bet365) for value in raw_bet365]
    assert list(bookmaker_vectors["bet365"].values()) == pytest.approx(expected_bet365)
    assert sum(bookmaker_vectors["bet365"].values()) == pytest.approx(1.0)
    assert list(bookmaker_vectors["william_hill"].values()) == pytest.approx(
        [1 / 3, 1 / 3, 1 / 3]
    )
    assert match.market is not None
    assert list(match.market.values()) == pytest.approx(
        [
            (
                bookmaker_vectors["bet365"][sign]
                + bookmaker_vectors["william_hill"][sign]
                + bookmaker_vectors["pinnacle"][sign]
            ) / 3
            for sign in ("1", "X", "2")
        ]
    )


def test_bookmaker_vectors_exclude_stale_pinnacle_and_invalid_triplets(tmp_path: Path):
    path = tmp_path / "bookmaker_cutoff.csv"
    path.write_text(
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A,PSH,PSD,PSA\n"
        "2025-07-22,A,B,1,0,H,2.0,3.5,4.0,2.2,3.2,3.6\n"
        "2025-07-23,C,D,0,1,A,2.0,3.5,4.0,2.2,3.2,3.6\n"
        "2025-07-24,E,F,1,1,D,0,3.5,4.0,2.2,3.2,3.6\n",
        encoding="utf-8",
    )

    before, after, invalid_bet365 = load_matches_csv(path)
    assert "pinnacle" in before.detail["market_bookmaker_probabilities"]
    assert "pinnacle" not in after.detail["market_bookmaker_probabilities"]
    assert "bet365" in after.detail["market_bookmaker_probabilities"]
    assert "bet365" not in invalid_bet365.detail["market_bookmaker_probabilities"]
    assert invalid_bet365.market is None


@pytest.mark.parametrize(
    ("home_goals", "away_goals", "invalid_column"),
    [
        ("True", "False", "FTHG"),
        ("1", "False", "FTAG"),
    ],
)
def test_load_rejects_boolean_goal_values(
    tmp_path: Path, home_goals: str, away_goals: str, invalid_column: str
):
    path = tmp_path / "boolean_goals.csv"
    path.write_text(
        "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        f"2025-01-01,A,B,{home_goals},{away_goals},H\n",
        encoding="utf-8",
    )

    with pytest.raises(
        TypeError, match=f"{invalid_column} must be a non-negative integer"
    ):
        load_matches_csv(path)
