from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd
import pytest
import requests

from scripts.build_history import build_dataset_profile, build_history, fetch_csv

VALID_CSV = (
    b"Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
    b"SP1,02/01/2022,B,C,1,0,H\n"
    b"SP1,01/01/2022,A,B,0,0,D\n"
    b"SP1,02/01/2022,B,C,1,0,H\n"
    b"SP1,05/01/2022,D,E,,,\n"
)


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(
        self, *, content: bytes | None = None, error: Exception | None = None
    ) -> None:
        self.content = content
        self.error = error
        self.calls = 0

    def get(self, url: str, timeout: tuple[int, int]) -> FakeResponse:
        self.calls += 1
        if self.error:
            raise self.error
        assert self.content is not None
        return FakeResponse(self.content)


def test_fetch_csv_reuses_fresh_valid_cache(tmp_path: Path) -> None:
    cache = tmp_path / "2122_SP1.csv"
    cache.write_bytes(VALID_CSV)
    session = FakeSession(error=requests.ConnectionError("should not be called"))

    df = fetch_csv(
        "https://example.test/source.csv", cache, session=session, cache_ttl_hours=24
    )

    assert len(df) == 4
    assert session.calls == 0


def test_fetch_csv_falls_back_to_valid_stale_cache(tmp_path: Path) -> None:
    cache = tmp_path / "2122_SP1.csv"
    cache.write_bytes(VALID_CSV)
    old = time.time() - 48 * 3600
    os.utime(cache, (old, old))
    session = FakeSession(error=requests.Timeout("provider timed out"))

    df = fetch_csv(
        "https://example.test/source.csv", cache, session=session, cache_ttl_hours=24
    )

    assert len(df) == 4
    assert session.calls == 1



def test_fetch_csv_offline_uses_stale_valid_cache_without_network(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "2122_SP1.csv"
    cache.write_bytes(VALID_CSV)
    old = time.time() - 48 * 3600
    os.utime(cache, (old, old))
    session = FakeSession(
        error=requests.ConnectionError("offline must not call network")
    )

    df = fetch_csv(
        "https://example.test/source.csv",
        cache,
        session=session,
        cache_ttl_hours=24,
        offline=True,
    )

    assert len(df) == 4
    assert session.calls == 0


def test_fetch_csv_offline_fails_closed_without_valid_cache(tmp_path: Path) -> None:
    session = FakeSession(content=VALID_CSV)

    with pytest.raises(RuntimeError, match="modo offline impide descargar"):
        fetch_csv(
            "https://example.test/source.csv",
            tmp_path / "missing.csv",
            session=session,
            offline=True,
        )

    assert session.calls == 0


def test_fetch_csv_rejects_non_csv_provider_response(tmp_path: Path) -> None:
    session = FakeSession(content=b"<html><body>service unavailable</body></html>")

    with pytest.raises(RuntimeError, match="CSV inv"):
        fetch_csv(
            "https://example.test/source.csv",
            tmp_path / "source.csv",
            session=session,
        )


def test_build_history_sorts_deduplicates_and_drops_unplayed(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cache_path = cache_dir / "2122_SP1.csv"
    cache_path.write_bytes(VALID_CSV)
    old = time.time() - 48 * 3600
    os.utime(cache_path, (old, old))
    output = tmp_path / "data" / "historical.csv"
    session = FakeSession(error=requests.ConnectionError("fresh cache expected"))

    result = build_history(
        seasons=("2122",),
        leagues=("la-liga",),
        output=output,
        cache_dir=cache_dir,
        cache_ttl_hours=24,
        offline=True,
        session=session,
    )

    saved = pd.read_csv(output)
    assert len(result) == 2
    assert len(saved) == 2
    assert saved["HomeTeam"].tolist() == ["A", "B"]
    assert saved["Date"].tolist() == ["01/01/2022", "02/01/2022"]
    assert saved["FTHG"].tolist() == [0, 1]
    assert saved["Season"].astype(str).tolist() == ["2122", "2122"]
    assert saved["League"].tolist() == ["la-liga", "la-liga"]
    assert saved["SourceURL"].str.contains("2122/SP1.csv").all()
    assert session.calls == 0
    profile_path = output.with_name("historical.profile.json")
    assert profile_path.is_file()
    profile = __import__("json").loads(profile_path.read_text(encoding="utf-8"))
    assert profile["duplicate_fixtures_before_deduplication"] == 1
    assert profile["rows_missing_final_scores"] == 1
    assert profile["integrity_passed"] is True


def test_dataset_profile_detects_conflicting_result_and_duplicate(
    tmp_path: Path,
) -> None:
    raw = pd.DataFrame(
        [
            {
                "Date": "01/01/2025",
                "HomeTeam": "A",
                "AwayTeam": "B",
                "FTHG": 1,
                "FTAG": 0,
                "FTR": "H",
                "Div": "SP1",
                "League": "la-liga",
                "Season": "2425",
                "SourceURL": "https://example.test/SP1.csv",
            },
            {
                "Date": "01/01/2025",
                "HomeTeam": "A",
                "AwayTeam": "B",
                "FTHG": 1,
                "FTAG": 0,
                "FTR": "H",
                "Div": "SP1",
                "League": "la-liga",
                "Season": "2425",
                "SourceURL": "https://example.test/SP1.csv",
            },
            {
                "Date": "02/01/2025",
                "HomeTeam": "C",
                "AwayTeam": "D",
                "FTHG": 0,
                "FTAG": 2,
                "FTR": "H",
                "Div": "SP1",
                "League": "la-liga",
                "Season": "2425",
                "SourceURL": "https://example.test/SP1.csv",
            },
        ]
    )
    raw["_ParsedDate"] = pd.to_datetime(raw["Date"], dayfirst=True)
    complete = raw.copy()
    final = complete.drop_duplicates(
        subset=["League", "Season", "_ParsedDate", "HomeTeam", "AwayTeam"]
    )
    profile = build_dataset_profile(
        raw,
        complete,
        final,
        ["https://example.test/SP1.csv"],
        duplicates_removed=1,
    )
    assert profile["duplicate_fixtures_before_deduplication"] == 1
    assert profile["score_result_mismatches"] == 1
    assert profile["integrity_passed"] is False


def test_fetch_csv_rejects_wrong_league_redirect(tmp_path: Path) -> None:
    wrong_division = VALID_CSV.replace(b"SP1,", b"SC2,")
    session = FakeSession(content=wrong_division)

    with pytest.raises(RuntimeError, match="divisi[oó]n esperada"):
        fetch_csv(
            "https://example.test/2627/SP2.csv",
            tmp_path / "2627_SP2.csv",
            session=session,
            expected_division="SP2",
        )


@pytest.mark.parametrize(
    ("home_goals", "away_goals", "invalid_column"),
    [
        ("True", "False", "FTHG"),
        ("1", "False", "FTAG"),
    ],
)
def test_fetch_csv_rejects_boolean_scores_before_caching(
    tmp_path: Path,
    home_goals: str,
    away_goals: str,
    invalid_column: str,
) -> None:
    content = (
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        f"SP1,02/01/2022,A,B,{home_goals},{away_goals},H\n"
    ).encode()
    cache = tmp_path / "boolean_scores.csv"

    with pytest.raises(RuntimeError, match=f"booleanos.*{invalid_column}"):
        fetch_csv(
            "https://example.test/boolean_scores.csv",
            cache,
            session=FakeSession(content=content),
            expected_division="SP1",
        )

    assert not cache.exists()
