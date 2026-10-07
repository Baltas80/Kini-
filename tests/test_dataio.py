from pathlib import Path

import pytest

from kini_engine.dataio import load_matches_csv, validate_matches


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
    from kini_engine.core import Match

    with pytest.raises(ValueError, match="incomplete score"):
        validate_matches([Match("", "A", "B", 1, None)])


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
