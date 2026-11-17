from __future__ import annotations

import unicodedata
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path

import numpy as np
import pandas as pd

from .core import SIGNS, Match


def _parse_match_date(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value
    raw = str(value).strip()
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise ValueError(f"invalid match date: {raw!r}")


def _team_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _parse_kickoff_minutes(value: object) -> int | None:
    """Parse Football-Data's local kickoff time without inventing a timezone."""
    if value is None or pd.isna(value):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            continue
    return None


def _market_temporal_status(
    match_date: datetime | str,
    kickoff_time: object,
    market_available: bool,
) -> str:
    """Classify odds against Football-Data's published snapshot schedule.

    This is schedule compatibility, not proof of the exact odds-capture time:
    the CSV does not provide a per-fixture capture timestamp or a timezone for
    its kickoff-time field.
    """
    if not market_available:
        return "unavailable"
    kickoff_minutes = _parse_kickoff_minutes(kickoff_time)
    if kickoff_minutes is None:
        return "unknown"
    try:
        weekday = _parse_match_date(match_date).weekday()
    except (TypeError, ValueError):
        return "unknown"

    # Football-Data collects weekend odds on Friday and midweek odds on
    # Tuesday. Its CSV defines Time only as the kickoff time; it does not
    # specify the timezone. Comparing that local-looking value directly with
    # a BST cutoff would silently assume a timezone. Fail closed for fixtures
    # on either snapshot-collection weekday, regardless of the displayed time.
    if weekday in {1, 4}:
        return "ambiguous"
    return "schedule_compatible"


def _optional_goal(value: object, row_number: int, column: str) -> int | None:
    if isinstance(value, (bool, np.bool_)):
        raise TypeError(
            f"CSV row {row_number}: {column} must be a non-negative integer"
        )
    if pd.isna(value):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"CSV row {row_number}: invalid {column} value {value!r}") from exc
    if not isfinite(numeric) or numeric < 0 or not numeric.is_integer():
        raise ValueError(f"CSV row {row_number}: {column} must be a non-negative integer")
    return int(numeric)


BOOKMAKER_ODDS_COLUMNS = {
    "bet365": ("B365H", "B365D", "B365A"),
    "william_hill": ("WHH", "WHD", "WHA"),
    "vc": ("VCH", "VCD", "VCA"),
    "pinnacle": ("PSH", "PSD", "PSA"),
}


def _bookmaker_probabilities_from_row(
    row: pd.Series,
    match_date: datetime | str | None = None,
) -> dict[str, dict[str, float]]:
    """Return each bookmaker's no-vig 1/X/2 vector from pre-closing odds.

    Football-Data warns that Pinnacle's public odds feed has been stale since
    2025-07-23. Its values are excluded from that date onward.
    """
    books = dict(BOOKMAKER_ODDS_COLUMNS)
    if match_date is not None:
        try:
            odds_date = _parse_match_date(match_date).date()
        except (TypeError, ValueError):
            odds_date = None
        if odds_date is not None and odds_date >= datetime(2025, 7, 23).date():
            books.pop("pinnacle", None)

    estimates: dict[str, dict[str, float]] = {}
    for bookmaker, columns in books.items():
        if not all(column in row.index for column in columns):
            continue
        try:
            odds = [float(row[column]) for column in columns]
        except (TypeError, ValueError):
            continue
        if any(not isfinite(value) or value <= 1.0 for value in odds):
            continue

        implied = [1.0 / value for value in odds]
        overround = sum(implied)
        if overround > 0.0:
            estimates[bookmaker] = {
                sign: float(probability / overround)
                for sign, probability in zip(SIGNS, implied)
            }
    return estimates


def _market_from_bookmaker_probabilities(
    bookmaker_probabilities: dict[str, dict[str, float]],
) -> dict[str, float] | None:
    """Build the existing equal-weight consensus from available bookmaker vectors."""
    if not bookmaker_probabilities:
        return None
    return {
        sign: float(
            sum(vector[sign] for vector in bookmaker_probabilities.values())
            / len(bookmaker_probabilities)
        )
        for sign in SIGNS
    }


def _market_from_row(
    row: pd.Series,
    match_date: datetime | str | None = None,
) -> dict[str, float] | None:
    """Return the equal-weight no-vig bookmaker consensus."""
    bookmaker_probabilities = _bookmaker_probabilities_from_row(row, match_date)
    return _market_from_bookmaker_probabilities(bookmaker_probabilities)


RESULT_MAP = {"H": "1", "D": "X", "A": "2", "1": "1", "X": "X", "2": "2"}


def load_matches_csv(path: str | Path) -> list[Match]:
    """Load and validate a completed football-data/DataHub-style CSV."""
    df = pd.read_csv(path)
    required = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {sorted(missing)}")

    out: list[Match] = []
    for row_number, (_, row) in enumerate(df.iterrows(), start=2):
        home = "" if pd.isna(row["HomeTeam"]) else str(row["HomeTeam"]).strip()
        away = "" if pd.isna(row["AwayTeam"]) else str(row["AwayTeam"]).strip()

        raw_result = row.get("FTR")
        result = None
        if pd.notna(raw_result) and str(raw_result).strip():
            normalized_result = str(raw_result).strip().upper()
            if normalized_result not in RESULT_MAP:
                raise ValueError(
                    f"CSV row {row_number}: unknown FTR label {raw_result!r}"
                )
            result = RESULT_MAP[normalized_result]

        home_goals = _optional_goal(row["FTHG"], row_number, "FTHG")
        away_goals = _optional_goal(row["FTAG"], row_number, "FTAG")

        detail = {
            str(k): row[k]
            for k in ("League", "Season", "Div")
            if k in row.index and pd.notna(row[k])
        }
        raw_kickoff_time = row.get("Time")
        kickoff_time = (
            str(raw_kickoff_time).strip()
            if raw_kickoff_time is not None and pd.notna(raw_kickoff_time)
            else None
        )
        detail["kickoff_time"] = kickoff_time
        detail["kickoff_time_timezone"] = "unspecified" if kickoff_time else None

        bookmaker_probabilities = _bookmaker_probabilities_from_row(
            row, row["Date"]
        )
        market = _market_from_bookmaker_probabilities(bookmaker_probabilities)
        detail["market_bookmaker_probabilities"] = bookmaker_probabilities
        temporal_status = _market_temporal_status(
            row["Date"], kickoff_time, market_available=market is not None
        )
        detail["market_temporal_status"] = temporal_status
        detail["market_pre_match_eligible"] = temporal_status == "schedule_compatible"

        out.append(
            Match(
                date="" if pd.isna(row["Date"]) else str(row["Date"]).strip(),
                home=home,
                away=away,
                home_goals=home_goals,
                away_goals=away_goals,
                result=result,
                detail=detail,
                market=market,
            )
        )

    validate_matches(out)
    return out


def validate_matches(matches: list[Match]) -> None:
    """Fail fast on invalid or duplicated completed historical fixtures."""
    seen: dict[tuple[str, str, str, str], int] = {}
    for i, match in enumerate(matches):
        row_number = i + 1
        home = str(match.home).strip()
        away = str(match.away).strip()
        if not home or not away:
            raise ValueError(f"match {row_number}: empty team name")
        if _team_key(home) == _team_key(away):
            raise ValueError(f"match {row_number}: home and away teams are identical")

        try:
            match_day = _parse_match_date(match.date).date().isoformat()
        except (TypeError, ValueError) as exc:
            raise ValueError(f"match {row_number}: invalid date {match.date!r}") from exc

        if match.result is not None and match.result not in SIGNS:
            raise ValueError(f"match {row_number}: invalid result {match.result!r}")
        if (match.home_goals is None) != (match.away_goals is None):
            raise ValueError(f"match {row_number}: incomplete score")
        if match.home_goals is None or match.away_goals is None:
            raise ValueError(f"match {row_number}: missing final score")
        if (
            isinstance(match.home_goals, bool)
            or isinstance(match.away_goals, bool)
            or int(match.home_goals) != match.home_goals
            or int(match.away_goals) != match.away_goals
        ):
            raise ValueError(f"match {row_number}: scores must be integers")
        if match.home_goals < 0 or match.away_goals < 0:
            raise ValueError(f"match {row_number}: negative goals")

        score_result = (
            "1" if match.home_goals > match.away_goals
            else "2" if match.away_goals > match.home_goals
            else "X"
        )
        if match.result is not None and match.result != score_result:
            raise ValueError(
                f"match {row_number}: result {match.result!r} conflicts with "
                f"score {match.home_goals}-{match.away_goals}"
            )

        competition = str(
            match.detail.get("Div", match.detail.get("League", ""))
        ).strip().casefold()
        key = (match_day, competition, _team_key(home), _team_key(away))
        if key in seen:
            raise ValueError(
                f"match {row_number}: duplicate fixture of match {seen[key]} "
                f"({match_day}, {home} vs {away})"
            )
        seen[key] = row_number


def build_dataset_profile(
    raw_frame: pd.DataFrame,
    final_frame: pd.DataFrame,
    source_urls: list[str],
    retrieved_at: datetime | None = None,
) -> dict[str, object]:
    """Build a reproducible quality/coverage profile for a downloaded dataset."""
    retrieved_at = retrieved_at or datetime.now(UTC)
    date_values = (
        raw_frame["Date"].tolist() if "Date" in raw_frame else [None] * len(raw_frame)
    )
    parsed_dates: list[datetime | None] = []
    for value in date_values:
        try:
            parsed_dates.append(_parse_match_date(value) if pd.notna(value) else None)
        except (TypeError, ValueError):
            parsed_dates.append(None)

    missingness = {
        str(column): {
            "count": int(raw_frame[column].isna().sum()),
            "fraction": float(raw_frame[column].isna().mean()) if len(raw_frame) else 0.0,
        }
        for column in raw_frame.columns
    }

    duplicate_keys: list[tuple[str, str, str, str]] = []
    for position, (_, row) in enumerate(raw_frame.iterrows()):
        date_value = parsed_dates[position]
        if date_value is None or pd.isna(row.get("HomeTeam")) or pd.isna(row.get("AwayTeam")):
            continue
        league = str(row.get("Div", row.get("League", ""))).strip().casefold()
        duplicate_keys.append((
            date_value.date().isoformat(),
            league,
            _team_key(str(row["HomeTeam"])),
            _team_key(str(row["AwayTeam"])),
        ))
    duplicate_count = len(duplicate_keys) - len(set(duplicate_keys))

    invalid_result_labels = 0
    mismatched_results = 0
    incomplete_scores = 0
    for _, row in raw_frame.iterrows():
        raw_result = row.get("FTR")
        normalized_result = None
        if pd.notna(raw_result) and str(raw_result).strip():
            normalized = str(raw_result).strip().upper()
            if normalized not in RESULT_MAP:
                invalid_result_labels += 1
            else:
                normalized_result = RESULT_MAP[normalized]

        hg = _optional_goal(row.get("FTHG"), 0, "FTHG")
        ag = _optional_goal(row.get("FTAG"), 0, "FTAG")
        if (hg is None) != (ag is None):
            incomplete_scores += 1
        elif hg is not None and ag is not None and normalized_result is not None:
            expected = "1" if hg > ag else "2" if ag > hg else "X"
            if expected != normalized_result:
                mismatched_results += 1

    valid_dates = [value for value in parsed_dates if value is not None]
    counts: dict[str, int] = {}
    if {"League", "Season"}.issubset(final_frame.columns):
        grouped = final_frame.groupby(["League", "Season"], dropna=False).size()
        counts = {f"{league}/{season}": int(count) for (league, season), count in grouped.items()}

    return {
        "retrieved_at_utc": retrieved_at.astimezone(UTC).isoformat(),
        "source_urls": sorted(set(source_urls)),
        "rows_before_filter": len(raw_frame),
        "rows_after_filter": len(final_frame),
        "date_coverage": {
            "start": min(value.date().isoformat() for value in valid_dates) if valid_dates else None,
            "end": max(value.date().isoformat() for value in valid_dates) if valid_dates else None,
            "invalid_or_missing": int(len(parsed_dates) - len(valid_dates)),
        },
        "missingness": missingness,
        "duplicate_fixtures": int(duplicate_count),
        "incomplete_scores": int(incomplete_scores),
        "invalid_result_labels": int(invalid_result_labels),
        "score_result_mismatches": int(mismatched_results),
        "league_season_counts": counts,
    }
