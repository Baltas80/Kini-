from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd
import pytest
import requests

from scripts.build_history import build_history, fetch_csv


VALID_CSV = (
    "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
    "SP1,02/01/2022,B,C,1,0,H\n"
    "SP1,01/01/2022,A,B,0,0,D\n"
    "SP1,02/01/2022,B,C,1,0,H\n"
    "SP1,05/01/2022,D,E,,,\n"
).encode("utf-8")


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, *, content: bytes | None = None, error: Exception | None = None) -> None:
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

    df = fetch_csv("https://example.test/source.csv", cache, session=session, cache_ttl_hours=24)

    assert len(df) == 4
    assert session.calls == 0


def test_fetch_csv_falls_back_to_valid_stale_cache(tmp_path: Path) -> None:
    cache = tmp_path / "2122_SP1.csv"
    cache.write_bytes(VALID_CSV)
    old = time.time() - 48 * 3600
    os.utime(cache, (old, old))
    session = FakeSession(error=requests.Timeout("provider timed out"))

    df = fetch_csv("https://example.test/source.csv", cache, session=session, cache_ttl_hours=24)

    assert len(df) == 4
    assert session.calls == 1


def test_fetch_csv_rejects_non_csv_provider_response(tmp_path: Path) -> None:
    session = FakeSession(content=b"<html><body>service unavailable</body></html>")

    with pytest.raises(RuntimeError, match="CSV inv"):
        fetch_csv("https://example.test/source.csv", tmp_path / "source.csv", session=session)


def test_build_history_sorts_deduplicates_and_drops_unplayed(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "2122_SP1.csv").write_bytes(VALID_CSV)
    output = tmp_path / "data" / "historical.csv"
    session = FakeSession(error=requests.ConnectionError("fresh cache expected"))

    result = build_history(
        seasons=("2122",),
        leagues=("la-liga",),
        output=output,
        cache_dir=cache_dir,
        cache_ttl_hours=24,
        session=session,
    )

    saved = pd.read_csv(output)
    assert len(result) == 2
    assert len(saved) == 2
    assert saved["HomeTeam"].tolist() == ["A", "B"]
    assert saved["Date"].tolist() == ["01/01/2022", "02/01/2022"]
    assert saved["FTHG"].tolist() == [0, 1]
    assert saved["Season"].astype(str).tolist() == ["2122", "2122"]
    assert session.calls == 0


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
