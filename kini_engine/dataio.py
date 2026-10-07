from __future__ import annotations

from pathlib import Path

import pandas as pd

from .core import Match, SIGNS


RESULT_MAP = {"H": "1", "D": "X", "A": "2", "1": "1", "X": "X", "2": "2"}


def load_matches_csv(path: str | Path) -> list[Match]:
    """Load football-data/DataHub-style CSV into Kini's canonical Match model."""
    df = pd.read_csv(path)
    required = {"HomeTeam", "AwayTeam", "FTHG", "FTAG"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {sorted(missing)}")

    out: list[Match] = []
    for _, row in df.iterrows():
        if pd.isna(row["HomeTeam"]) or pd.isna(row["AwayTeam"]):
            continue

        raw_result = row.get("FTR")
        result = None
        if pd.notna(raw_result):
            result = RESULT_MAP.get(str(raw_result).strip().upper())

        home_goals = int(row["FTHG"]) if pd.notna(row["FTHG"]) else None
        away_goals = int(row["FTAG"]) if pd.notna(row["FTAG"]) else None

        detail = {
            str(k): row[k]
            for k in ("League", "Season", "Div")
            if k in row.index and pd.notna(row[k])
        }

        out.append(
            Match(
                date=str(row.get("Date", "")),
                home=str(row["HomeTeam"]).strip(),
                away=str(row["AwayTeam"]).strip(),
                home_goals=home_goals,
                away_goals=away_goals,
                result=result,
                detail=detail,
            )
        )
    return out


def validate_matches(matches: list[Match]) -> None:
    """Fail fast on malformed historical data before a model fit."""
    for i, m in enumerate(matches):
        if not m.home or not m.away:
            raise ValueError(f"match {i}: empty team name")
        if m.result is not None and m.result not in SIGNS:
            raise ValueError(f"match {i}: invalid result {m.result!r}")
        if (m.home_goals is None) != (m.away_goals is None):
            raise ValueError(f"match {i}: incomplete score")
        if m.home_goals is not None and m.home_goals < 0:
            raise ValueError(f"match {i}: negative home goals")
        if m.away_goals is not None and m.away_goals < 0:
            raise ValueError(f"match {i}: negative away goals")
