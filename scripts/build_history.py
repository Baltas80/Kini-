from __future__ import annotations

import argparse
import io
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

FOOTBALL_DATA = "https://www.football-data.co.uk/mmz4281/{season}/{division}.csv"
SEASONS = ("2021", "2122", "2223", "2324", "2425", "2526", "2627")
LEAGUES = {"la-liga": "SP1", "segunda": "SP2"}
REQUIRED_COLUMNS = {"Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"}
DEFAULT_CACHE_DIR = Path(".cache/football-data")
DEFAULT_CACHE_TTL_HOURS = 24.0

log = logging.getLogger("kini.ingestion")


def make_session() -> requests.Session:
    """Create an HTTP session with bounded retries for transient source failures."""
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": "Kini-history-ingestion/1.0 (+https://github.com/Baltas80/Kini-)",
            "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.8",
        }
    )
    return session


def _parse_source_csv(
    content: bytes, source: str, expected_division: str | None = None
) -> pd.DataFrame:
    """Parse and validate a Football-Data CSV before it can enter the cache."""
    if not content or not content.strip():
        raise ValueError(f"{source}: respuesta vacía")

    errors: list[Exception] = []
    df: pd.DataFrame | None = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            candidate = pd.read_csv(io.BytesIO(content), encoding=encoding, low_memory=False)
            df = candidate
            break
        except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            errors.append(exc)
    if df is None:
        raise ValueError(f"{source}: no se pudo interpretar el CSV") from errors[-1]

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            f"{source}: CSV inválido; faltan columnas {sorted(missing)} "
            f"(posible HTML/error del proveedor)"
        )
    if df.empty:
        raise ValueError(f"{source}: CSV sin filas")

    if expected_division is not None:
        divisions = set(df["Div"].dropna().astype(str).str.strip().str.upper())
        if divisions != {expected_division.upper()}:
            raise ValueError(
                f"{source}: división esperada {expected_division!r}, "
                f"pero la respuesta declara {sorted(divisions)!r}; posible redirección errónea"
            )

    # Team names are normalized before validating dates and duplicate keys.
    for column in ("HomeTeam", "AwayTeam"):
        df[column] = df[column].astype("string").str.strip()
        df[column] = df[column].replace("", pd.NA)

    parsed_dates = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    has_teams = df["HomeTeam"].notna() & df["AwayTeam"].notna()
    bad_dates = has_teams & parsed_dates.isna()
    if bool(bad_dates.any()):
        sample = df.loc[bad_dates, "Date"].astype(str).head(3).tolist()
        raise ValueError(f"{source}: fechas no interpretables en filas con equipos: {sample}")

    for column in ("FTHG", "FTAG"):
        raw = df[column]
        numeric = pd.to_numeric(raw, errors="coerce")
        malformed = raw.notna() & numeric.isna()
        if bool(malformed.any()):
            sample = raw.loc[malformed].astype(str).head(3).tolist()
            raise ValueError(f"{source}: valores inválidos en {column}: {sample}")
        if bool((numeric.dropna() < 0).any()):
            raise ValueError(f"{source}: goles negativos en {column}")
        non_integer = numeric.dropna().mod(1).ne(0)
        if bool(non_integer.any()):
            raise ValueError(f"{source}: goles no enteros en {column}")
        df[column] = numeric

    one_sided_score = df["FTHG"].isna() ^ df["FTAG"].isna()
    if bool(one_sided_score.any()):
        raise ValueError(f"{source}: hay partidos con solo uno de los dos marcadores")

    # Add an internal parsed date to ensure chronology is real, not lexical.
    df["_ParsedDate"] = parsed_dates
    return df


def _atomic_write(path: Path, content: bytes) -> None:
    """Replace a file atomically, leaving any previous valid copy untouched on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temp_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def fetch_csv(
    url: str,
    cache_path: str | Path,
    *,
    session: requests.Session | None = None,
    cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
    refresh: bool = False,
    expected_division: str | None = None,
) -> pd.DataFrame:
    """Read a validated cache or download the source, retrying and falling back safely."""
    path = Path(cache_path)
    cached_content: bytes | None = None
    cached_df: pd.DataFrame | None = None

    if path.is_file():
        try:
            candidate = path.read_bytes()
            validated = _parse_source_csv(candidate, f"caché {path}", expected_division)
            cached_content, cached_df = candidate, validated
            age_hours = max(0.0, time.time() - path.stat().st_mtime) / 3600
            if not refresh and age_hours <= max(0.0, cache_ttl_hours):
                log.info("Cache hit: %s (%.1f h)", path, age_hours)
                return validated
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            log.warning("Ignorando caché inválida %s: %s", path, exc)

    client = session or make_session()
    try:
        response = client.get(url, timeout=(5, 30))
        response.raise_for_status()
        # Validate before replacing the last known-good cached file.
        downloaded = _parse_source_csv(response.content, url, expected_division)
        try:
            _atomic_write(path, response.content)
        except OSError as exc:
            log.warning("No se pudo guardar caché %s: %s", path, exc)
        log.info("Descargado y validado: %s", url)
        return downloaded
    except (requests.RequestException, ValueError, pd.errors.ParserError) as exc:
        if cached_df is not None and cached_content is not None:
            log.warning("Fuente no disponible; usando caché válida aunque esté caducada (%s): %s", url, exc)
            return cached_df
        raise RuntimeError(f"No se pudo obtener un CSV válido de {url}: {exc}") from exc


def _atomic_write_dataframe(frame: pd.DataFrame, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=target.parent,
            prefix=f".{target.name}.", suffix=".tmp", delete=False
        ) as handle:
            temp_name = handle.name
            frame.to_csv(handle, index=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
        temp_name = None
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass



def build_dataset_profile(
    raw_frame: pd.DataFrame,
    complete_frame: pd.DataFrame,
    final_frame: pd.DataFrame,
    source_urls: list[str],
    duplicates_removed: int,
    source_metadata: list[dict[str, object]] | None = None,
    profile_generated_at: datetime | None = None,
) -> dict[str, object]:
    """Summarize provenance, coverage, missingness and integrity before modeling."""
    profile_generated_at = profile_generated_at or datetime.now(timezone.utc)
    dates = raw_frame.get("_ParsedDate")
    if dates is None:
        dates = pd.to_datetime(raw_frame["Date"], dayfirst=True, errors="coerce")

    source_columns = raw_frame.drop(columns=["_ParsedDate"], errors="ignore")
    missingness = {
        str(column): {
            "count": int(source_columns[column].isna().sum()),
            "fraction": float(source_columns[column].isna().mean()) if len(source_columns) else 0.0,
        }
        for column in source_columns.columns
    }

    home = raw_frame["HomeTeam"].astype("string").str.strip()
    away = raw_frame["AwayTeam"].astype("string").str.strip()
    team_mask = home.notna() & away.notna() & home.ne("") & away.ne("")
    score_home = pd.to_numeric(raw_frame["FTHG"], errors="coerce")
    score_away = pd.to_numeric(raw_frame["FTAG"], errors="coerce")
    complete_score = score_home.notna() & score_away.notna()
    complete_mask = team_mask & complete_score

    def fixture_keys(frame: pd.DataFrame) -> pd.DataFrame:
        frame_dates = frame.get("_ParsedDate")
        if frame_dates is None:
            frame_dates = pd.to_datetime(frame["Date"], dayfirst=True, errors="coerce")
        return pd.DataFrame(
            {
                "league": frame["League"].astype("string").str.strip().str.casefold(),
                "season": frame["Season"].astype("string").str.strip(),
                "date": frame_dates.dt.strftime("%Y-%m-%d"),
                "home": frame["HomeTeam"].astype("string").str.strip().str.casefold(),
                "away": frame["AwayTeam"].astype("string").str.strip().str.casefold(),
            },
            index=frame.index,
        )

    raw_complete = raw_frame.loc[complete_mask].copy()
    keys = fixture_keys(raw_complete)
    duplicate_count = int(keys.duplicated().sum())
    conflicting_duplicates = 0
    if duplicate_count:
        keyed = raw_complete.copy()
        keyed["_fixture_key"] = list(map(tuple, keys.to_numpy()))
        for _, group in keyed.groupby("_fixture_key", sort=False):
            if len(group) < 2:
                continue
            score_variants = group[["FTHG", "FTAG"]].drop_duplicates()
            labels = (
                group.get("FTR", pd.Series(index=group.index, dtype="object"))
                .dropna()
                .astype(str)
                .str.strip()
                .str.upper()
            )
            labels = labels[labels.ne("")]
            if len(score_variants) > 1 or labels.nunique() > 1:
                conflicting_duplicates += 1

    result_values = raw_frame.get("FTR", pd.Series(index=raw_frame.index, dtype="object"))
    normalized = result_values.astype("string").str.strip().str.upper()
    result_map = {"H": "1", "D": "X", "A": "2", "1": "1", "X": "X", "2": "2"}
    mapped = normalized.map(result_map)
    labels_present = result_values.notna() & normalized.ne("")
    invalid_labels = int((labels_present & mapped.isna()).sum())

    expected = pd.Series(index=raw_frame.index, dtype="object")
    expected.loc[score_home > score_away] = "1"
    expected.loc[score_home < score_away] = "2"
    expected.loc[score_home.eq(score_away) & complete_score] = "X"
    mismatches = int((complete_mask & mapped.notna() & expected.ne(mapped)).sum())

    valid_dates = dates.notna()
    invalid_dates_with_teams = int((team_mask & ~valid_dates).sum())
    missing_scores = int((~complete_score).sum())
    incomplete_scores = int((score_home.isna() ^ score_away.isna()).sum())

    league_season_counts: dict[str, int] = {}
    if {"League", "Season"}.issubset(final_frame.columns):
        grouped = final_frame.groupby(["League", "Season"], dropna=False).size()
        league_season_counts = {
            f"{league}/{season}": int(count)
            for (league, season), count in grouped.items()
        }

    source_counts: dict[str, int] = {}
    if "SourceURL" in raw_frame.columns:
        source_counts = {
            str(source): int(count)
            for source, count in raw_frame["SourceURL"].value_counts(dropna=False).items()
        }

    integrity_passed = not any(
        (invalid_labels, mismatches, incomplete_scores, invalid_dates_with_teams, conflicting_duplicates)
    )
    return {
        "profile_generated_at_utc": profile_generated_at.astimezone(timezone.utc).isoformat(),
        "source_urls": sorted(set(source_urls)),
        "source_cache_metadata": source_metadata or [],
        "source_row_counts": source_counts,
        "rows_before_filter": int(len(raw_frame)),
        "rows_after_complete_score_filter": int(len(complete_frame)),
        "rows_after_deduplication": int(len(final_frame)),
        "rows_missing_team_names": int((~team_mask).sum()),
        "rows_missing_final_scores": missing_scores,
        "rows_with_incomplete_scores": incomplete_scores,
        "date_coverage": {
            "start": dates.min().date().isoformat() if valid_dates.any() else None,
            "end": dates.max().date().isoformat() if valid_dates.any() else None,
            "invalid_or_missing_with_teams": invalid_dates_with_teams,
        },
        "missingness": missingness,
        "duplicate_fixtures_before_deduplication": duplicate_count,
        "duplicates_removed": int(duplicates_removed),
        "conflicting_duplicate_fixtures": int(conflicting_duplicates),
        "invalid_result_labels": invalid_labels,
        "score_result_mismatches": mismatches,
        "league_season_counts": league_season_counts,
        "integrity_passed": bool(integrity_passed),
    }


def build_history(
    *,
    seasons: Iterable[str] = SEASONS,
    leagues: Iterable[str] = tuple(LEAGUES),
    output: str | Path = Path("data/historical_spain.csv"),
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
    refresh: bool = False,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Build a validated, de-duplicated chronological history from cached/source CSVs."""
    selected_leagues = tuple(leagues)
    unknown = sorted(set(selected_leagues) - set(LEAGUES))
    if unknown:
        raise ValueError(f"Ligas desconocidas: {unknown}")
    selected_seasons = tuple(str(season) for season in seasons)
    if not selected_seasons:
        raise ValueError("Debe especificarse al menos una temporada")
    if cache_ttl_hours < 0:
        raise ValueError("cache_ttl_hours no puede ser negativo")

    frames: list[pd.DataFrame] = []
    source_urls: list[str] = []
    source_metadata: list[dict[str, object]] = []
    profile_generated_at = datetime.now(timezone.utc)
    client = session or make_session()
    cache_root = Path(cache_dir)

    for season in selected_seasons:
        for league in selected_leagues:
            code = LEAGUES[league]
            url = FOOTBALL_DATA.format(season=season, division=code)
            cache_path = cache_root / f"{season}_{code}.csv"
            df = fetch_csv(
                url,
                cache_path,
                session=client,
                cache_ttl_hours=cache_ttl_hours,
                refresh=refresh,
                expected_division=code,
            )
            source_urls.append(url)
            if cache_path.is_file():
                cache_mtime = cache_path.stat().st_mtime
                source_metadata.append(
                    {
                        "source_url": url,
                        "cache_path": str(cache_path),
                        "cache_file_mtime_utc": datetime.fromtimestamp(
                            cache_mtime, timezone.utc
                        ).isoformat(),
                        "cache_age_hours": round(
                            max(0.0, time.time() - cache_mtime) / 3600.0, 3
                        ),
                    }
                )
            else:
                source_metadata.append(
                    {
                        "source_url": url,
                        "cache_path": str(cache_path),
                        "cache_file_mtime_utc": None,
                        "cache_age_hours": None,
                    }
                )
            df["League"] = league
            df["Season"] = season
            df["SourceURL"] = url
            frames.append(df)

    combined = pd.concat(frames, ignore_index=True)
    complete = (
        combined["HomeTeam"].notna()
        & combined["AwayTeam"].notna()
        & combined["FTHG"].notna()
        & combined["FTAG"].notna()
    )
    out = combined.loc[complete].copy()
    complete_rows = out.copy()
    if out.empty:
        raise ValueError("Las fuentes no contienen ningún partido con resultado completo")

    out["FTHG"] = out["FTHG"].astype(int)
    out["FTAG"] = out["FTAG"].astype(int)

    out["_HomeKey"] = out["HomeTeam"].astype("string").str.strip().str.casefold()
    out["_AwayKey"] = out["AwayTeam"].astype("string").str.strip().str.casefold()
    key = ["League", "Season", "_ParsedDate", "_HomeKey", "_AwayKey"]
    before_dedup = len(out)
    out = out.drop_duplicates(subset=key, keep="last")
    duplicates_removed = before_dedup - len(out)
    out = out.sort_values(
        ["_ParsedDate", "League", "Season", "_HomeKey", "_AwayKey"],
        kind="mergesort",
    ).reset_index(drop=True)

    target = Path(output)
    profile = build_dataset_profile(
        combined,
        complete_rows,
        out,
        source_urls,
        duplicates_removed,
        source_metadata=source_metadata,
        profile_generated_at=profile_generated_at,
    )
    profile_target = target.with_name(f"{target.stem}.profile.json")
    _atomic_write(
        profile_target,
        (json.dumps(profile, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    if not profile["integrity_passed"]:
        raise ValueError(
            "Dataset integrity checks failed; inspect "
            f"{profile_target}: invalid labels={profile['invalid_result_labels']}, "
            f"score/result mismatches={profile['score_result_mismatches']}, "
            f"conflicting duplicates={profile['conflicting_duplicate_fixtures']}"
        )

    out = out.drop(columns=["_ParsedDate", "_HomeKey", "_AwayKey"])
    _atomic_write_dataframe(out, target)
    log.info(
        "Histórico escrito: %s; partidos=%d; duplicados eliminados=%d; temporadas=%d; ligas=%d; perfil=%s",
        target, len(out), duplicates_removed, len(selected_seasons), len(selected_leagues), profile_target,
    )
    return out


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Descarga y valida el histórico español de Football-Data.")
    parser.add_argument("--output", type=Path, default=Path("data/historical_spain.csv"))
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--cache-ttl-hours", type=float, default=DEFAULT_CACHE_TTL_HOURS)
    parser.add_argument("--refresh", action="store_true", help="Intentar renovar los CSV aunque la caché siga vigente.")
    parser.add_argument("--seasons", nargs="+", default=list(SEASONS), help="Códigos de temporada, por ejemplo 2526 2627.")
    parser.add_argument("--leagues", nargs="+", choices=tuple(LEAGUES), default=list(LEAGUES))
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args()
    history = build_history(
        seasons=args.seasons,
        leagues=args.leagues,
        output=args.output,
        cache_dir=args.cache_dir,
        cache_ttl_hours=args.cache_ttl_hours,
        refresh=args.refresh,
    )
    print(f"Wrote {len(history)} matches to {args.output}")


if __name__ == "__main__":
    main()
