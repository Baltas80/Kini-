from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import tempfile
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

OFFICIAL_HOSTS = frozenset({"ligaf.es", "www.ligaf.es"})
ARCHIVE_URL = (
    "https://ligaf.es/resultados/primera_division_femenina/{matchday}/{season_end_year}"
)
MATCH_PATH = re.compile(r"^/partido/.+/([0-9]+)/detalle/?$")
MONTHS = {
    "ENE": 1,
    "FEB": 2,
    "MAR": 3,
    "ABR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AGO": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DIC": 12,
}
DEFAULT_SEASONS = (2023, 2024, 2025, 2026, 2027)
DEFAULT_CACHE_DIR = Path(".cache/ligaf")
DEFAULT_OUTPUT = Path("data/ligaf_history.jsonl")
DEFAULT_PROFILE = Path("data/ligaf_history.profile.json")
TRAINING_EXCLUSION_REASON = (
    "Liga F history is evidence-only until team identity, source coverage, "
    "and pre-kickoff feature availability have been independently validated."
)

log = logging.getLogger("kini.ligaf_ingestion")


class LigaFHistoryError(ValueError):
    """Raised when official Liga F historical data cannot be validated."""


class _HTMLDocument(HTMLParser):
    """Small standard-library HTML reader for titles, visible text and anchors."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._title_depth = 0
        self._ignore_depth = 0
        self._anchor: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript"}:
            self._ignore_depth += 1
            return
        if self._ignore_depth:
            return
        if tag == "title":
            self._title_depth += 1
        elif tag == "a" and self._anchor is None:
            values = dict(attrs)
            self._anchor = {"href": values.get("href") or "", "parts": []}

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript"} and self._ignore_depth:
            self._ignore_depth -= 1
            return
        if self._ignore_depth:
            return
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        elif tag == "a" and self._anchor is not None:
            text = " ".join(self._anchor["parts"])
            self.links.append({"href": self._anchor["href"], "text": text})
            self._anchor = None

    def handle_data(self, data: str) -> None:
        if self._ignore_depth:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        self.text_parts.append(cleaned)
        if self._title_depth:
            self.title_parts.append(cleaned)
        if self._anchor is not None:
            self._anchor["parts"].append(cleaned)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()

    @property
    def text(self) -> str:
        return " ".join(self.text_parts).strip()


def _parse_document(html: str) -> _HTMLDocument:
    parser = _HTMLDocument()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:
        raise LigaFHistoryError(f"invalid HTML document: {exc}") from exc
    return parser


def _official_url(url: str, field: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_HOSTS:
        raise LigaFHistoryError(f"{field} must be HTTPS on the official ligaf.es domain")
    return url


def make_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": "Kini-LigaF-history/1.0 (+https://github.com/Baltas80/Kini-)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9",
        }
    )
    return session


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _cache_paths(cache_dir: Path, url: str) -> tuple[Path, Path]:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{key}.html", cache_dir / f"{key}.json"


def _read_cache(html_path: Path, metadata_path: Path) -> tuple[str, dict[str, Any]] | None:
    if not html_path.is_file() or not metadata_path.is_file():
        return None
    try:
        html_bytes = html_path.read_bytes()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise LigaFHistoryError(f"invalid cache metadata: {metadata_path}")
        if hashlib.sha256(html_bytes).hexdigest() != metadata.get("content_sha256"):
            raise LigaFHistoryError(f"cache hash mismatch: {html_path}")
        encoding = metadata.get("encoding", "utf-8")
        if not isinstance(encoding, str) or not encoding:
            raise LigaFHistoryError(f"invalid cache encoding: {metadata_path}")
        return html_bytes.decode(encoding, errors="strict"), metadata
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LigaFHistoryError(f"cannot read cached source {html_path}: {exc}") from exc


def fetch_html(
    url: str,
    *,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    session: requests.Session | None = None,
    cache_ttl_hours: float = 24.0,
    refresh: bool = False,
    offline: bool = False,
    request_delay: float = 0.25,
) -> tuple[str, dict[str, Any]]:
    """Fetch or reuse an official page, retaining its exact bytes and SHA-256."""
    _official_url(url, "source_url")
    if cache_ttl_hours < 0 or request_delay < 0:
        raise ValueError("cache TTL and request delay must be non-negative")

    cache_root = Path(cache_dir)
    html_path, metadata_path = _cache_paths(cache_root, url)
    cached = _read_cache(html_path, metadata_path)
    now = datetime.now(UTC)
    if cached is not None:
        html, metadata = cached
        retrieved_at = datetime.fromisoformat(metadata["retrieved_at_utc"])
        age_hours = max(0.0, (now - retrieved_at.astimezone(UTC)).total_seconds() / 3600)
        if not refresh and age_hours <= cache_ttl_hours:
            return html, {**metadata, "cache_used": True, "cache_stale": False}
    else:
        age_hours = None

    if offline:
        if cached is None:
            raise LigaFHistoryError(f"offline mode has no cached source for {url}")
        html, metadata = cached
        return html, {**metadata, "cache_used": True, "cache_stale": True}

    client = session or make_session()
    if request_delay:
        time.sleep(request_delay)
    try:
        response = client.get(url, timeout=(10, 30))
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").casefold()
        if content_type and "html" not in content_type:
            raise LigaFHistoryError(
                f"unexpected content type for {url}: {content_type}"
            )
        encoding = response.encoding or "utf-8"
        html_bytes = response.content
        html = html_bytes.decode(encoding, errors="strict")
        document = _parse_document(html)
        if "ligaf" not in document.title.casefold() and "liga f" not in document.text[:3000].casefold():
            raise LigaFHistoryError(f"response is not a recognizable Liga F page: {url}")
        retrieved_at = datetime.now(UTC).isoformat()
        metadata = {
            "source_url": url,
            "retrieved_at_utc": retrieved_at,
            "content_sha256": hashlib.sha256(html_bytes).hexdigest(),
            "http_status": int(response.status_code),
            "encoding": encoding,
            "cache_used": False,
            "cache_stale": False,
        }
        _atomic_write(html_path, html_bytes)
        _atomic_write(
            metadata_path,
            (json.dumps(metadata, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        )
        return html, metadata
    except (requests.RequestException, UnicodeDecodeError, LigaFHistoryError) as exc:
        if cached is None:
            raise LigaFHistoryError(f"official source request failed for {url}: {exc}") from exc
        html, metadata = cached
        log.warning("Using stale validated cache for %s after source error: %s", url, exc)
        return html, {
            **metadata,
            "cache_used": True,
            "cache_stale": True,
            "refresh_error": str(exc),
            "cache_age_hours_at_attempt": age_hours,
        }


def extract_match_links(html: str, *, page_url: str) -> list[dict[str, str]]:
    """Extract unique official match-detail links from one round archive page."""
    _official_url(page_url, "round_url")
    document = _parse_document(html)
    found: dict[str, str] = {}
    for link in document.links:
        href = link["href"].strip()
        if not href:
            continue
        absolute = urljoin(page_url, href)
        parsed = urlparse(absolute)
        match = MATCH_PATH.fullmatch(parsed.path)
        if match is None:
            continue
        _official_url(absolute, "match_url")
        match_id = match.group(1)
        canonical_url = f"https://ligaf.es{parsed.path}"
        previous = found.get(match_id)
        if previous is not None and previous != canonical_url:
            raise LigaFHistoryError(
                f"match ID {match_id} appears with conflicting official URLs"
            )
        found[match_id] = canonical_url

    if not found:
        raise LigaFHistoryError(f"no official Liga F match links found on {page_url}")
    return [{"match_id": key, "match_url": value} for key, value in found.items()]


def extract_round_dates(html: str, *, season_end_year: int) -> set[date]:
    """Read explicit calendar dates shown in the official round archive."""
    document = _parse_document(html)
    season_start = date(season_end_year - 1, 7, 1)
    season_end = date(season_end_year, 6, 30)
    dates: set[date] = set()
    pattern = re.compile(
        r"\b(?P<day>\d{1,2})\s+(?P<month>[A-Za-zÁÉÍÓÚÜáéíóúü]{3})\s+"
        r"(?P<year>20\d{2})\b",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(document.text):
        month = MONTHS.get(match.group("month").upper())
        if month is None:
            continue
        try:
            value = date(
                int(match.group("year")),
                month,
                int(match.group("day")),
            )
        except ValueError:
            continue
        if season_start <= value <= season_end:
            dates.add(value)
    if not dates:
        raise LigaFHistoryError(
            f"official round page has no explicit dates for season {season_end_year}"
        )
    return dates


def _parse_match_title(title: str) -> tuple[str, str]:
    """Extract teams without trusting the site's title year for historical seasons."""
    cleaned = re.sub(r"\s+", " ", title).strip()
    match = re.search(
        r"^(?P<home>.+?)\s+vs\.?\s+(?P<away>.+?)\s+-\s+"
        r"(?:Liga F(?:\s+Moeve)?|Primera Iberdrola|Primera División Femenina)"
        r"(?:\s+20\d{2})?(?:\s*\||$)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise LigaFHistoryError(
            f"cannot extract home/away teams from match title: {title!r}"
        )
    return match.group("home").strip(), match.group("away").strip()


def _parse_matchday_and_kickoff(
    text: str, season_end_year: int
) -> tuple[int, datetime] | None:
    match = re.search(
        r"\bJOR\.\s*(?P<matchday>\d{1,2})\s*\|\s*"
        r"[\wÁÉÍÓÚÜáéíóúü]+\s+(?P<day>\d{1,2})\s+"
        r"(?P<month>[A-Za-zÁÉÍÓÚÜáéíóúü]{3})\s+"
        r"(?P<time>\d{2}:\d{2})\b",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    matchday = int(match.group("matchday"))
    month_key = match.group("month").upper()
    month = MONTHS.get(month_key)
    if month is None:
        raise LigaFHistoryError(f"unsupported Spanish month abbreviation: {month_key}")
    year = season_end_year - 1 if month >= 8 else season_end_year
    try:
        local_date = date(year, month, int(match.group("day")))
        hour, minute = (int(part) for part in match.group("time").split(":"))
        kickoff = datetime(
            local_date.year,
            local_date.month,
            local_date.day,
            hour,
            minute,
            tzinfo=ZoneInfo("Europe/Madrid"),
        )
    except ValueError as exc:
        raise LigaFHistoryError(f"invalid Liga F kickoff header: {match.group(0)!r}") from exc

    season_start = date(season_end_year - 1, 7, 1)
    season_end = date(season_end_year, 6, 30)
    if not season_start <= local_date <= season_end:
        raise LigaFHistoryError(
            f"kickoff date {local_date} falls outside season ending {season_end_year}"
        )
    return matchday, kickoff


def parse_match_detail(
    html: str,
    *,
    match_url: str,
    season_end_year: int,
    expected_matchday: int,
    round_url: str,
    match_source_metadata: dict[str, Any],
    round_source_metadata: dict[str, Any],
    allowed_round_dates: set[date] | None = None,
) -> dict[str, Any]:
    """Parse one official match page; unknown statuses and malformed scores fail closed."""
    _official_url(match_url, "match_url")
    _official_url(round_url, "round_url")
    match_id_match = MATCH_PATH.fullmatch(urlparse(match_url).path)
    if match_id_match is None:
        raise LigaFHistoryError(f"invalid official match URL: {match_url}")
    match_id = match_id_match.group(1)

    document = _parse_document(html)
    if "ligaf" not in document.title.casefold() and "liga f" not in document.text[:3000].casefold():
        raise LigaFHistoryError(f"match page {match_id} is not recognizable as Liga F")
    home, away = _parse_match_title(document.title)
    header = _parse_matchday_and_kickoff(document.text, season_end_year)
    if header is None:
        matchday = expected_matchday
        kickoff = None
    else:
        matchday, kickoff = header
        if matchday != expected_matchday:
            raise LigaFHistoryError(
                f"match {match_id} belongs to jornada {matchday}, "
                f"but was linked from jornada {expected_matchday}"
            )
        if (
            kickoff is not None
            and allowed_round_dates is not None
            and kickoff.date() not in allowed_round_dates
        ):
            raise LigaFHistoryError(
                f"match {match_id} kickoff date {kickoff.date()} is absent "
                "from the official round archive dates"
            )

    leading_text = document.text[:2500].casefold()
    if "aplazado" in leading_text or "pospuesto" in leading_text:
        status = "postponed"
        home_goals = away_goals = None
        result = None
    elif "suspendido" in leading_text:
        status = "suspended"
        home_goals = away_goals = None
        result = None
    elif "finalizado" in leading_text:
        status = "played"
        score = re.search(
            r"\bFinalizado\b.*?(\d{1,2})\s*[-–]\s*(\d{1,2})\b",
            document.text,
            flags=re.IGNORECASE,
        )
        if score is None:
            raise LigaFHistoryError(f"finished match {match_id} has no parseable score")
        home_goals, away_goals = (int(score.group(1)), int(score.group(2)))
        result = (
            "1"
            if home_goals > away_goals
            else "2"
            if home_goals < away_goals
            else "X"
        )
        if kickoff is None:
            raise LigaFHistoryError(
                f"finished match {match_id} has no timezone-aware kickoff header"
            )
    elif "en juego" in leading_text or "en directo" in leading_text:
        status = "in_progress"
        home_goals = away_goals = None
        result = None
    else:
        raise LigaFHistoryError(
            f"match {match_id} has an unknown or missing official status"
        )

    if kickoff is not None and kickoff.date() > date.today():
        if status == "played":
            raise LigaFHistoryError(f"finished match {match_id} has a future kickoff")

    season = f"{season_end_year - 1}-{str(season_end_year)[-2:]}"
    return {
        "schema_version": 1,
        "provider": "LIGA_F",
        "competition_id": "LIGA_F",
        "gender": "women",
        "season": season,
        "season_end_year": season_end_year,
        "matchday": matchday,
        "match_id": match_id,
        "kickoff_at": kickoff.isoformat() if kickoff else None,
        "home_team_name": home,
        "away_team_name": away,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "result_1x2": result,
        "match_status": status,
        "match_url": match_url,
        "round_url": round_url,
        "match_source_retrieved_at_utc": match_source_metadata["retrieved_at_utc"],
        "match_source_sha256": match_source_metadata["content_sha256"],
        "round_source_retrieved_at_utc": round_source_metadata["retrieved_at_utc"],
        "round_source_sha256": round_source_metadata["content_sha256"],
        "training_label_eligible": False,
        "training_exclusion_reason": TRAINING_EXCLUSION_REASON,
    }


def _normalized_name(value: str) -> str:
    return " ".join(value.casefold().split())


def validate_history(
    records: list[dict[str, Any]],
    *,
    completed_seasons: set[int],
    requested_rounds: dict[int, int],
    expected_fixtures_per_round: int = 8,
) -> dict[str, Any]:
    """Validate fixture identity, score integrity and round coverage without training promotion."""
    if not records:
        raise LigaFHistoryError("Liga F history is empty")
    if expected_fixtures_per_round <= 0:
        raise ValueError("expected_fixtures_per_round must be positive")

    seen_ids: set[str] = set()
    seen_fixtures: set[tuple[str, str, str, str]] = set()
    seen_scheduled_pairs: set[tuple[str, str, str]] = set()
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    stale_sources: set[str] = set()

    for index, row in enumerate(records):
        location = f"records[{index}]"
        match_id = str(row.get("match_id", "")).strip()
        if not match_id.isdigit():
            raise LigaFHistoryError(f"{location}.match_id must be numeric")
        if match_id in seen_ids:
            raise LigaFHistoryError(f"duplicate Liga F match ID: {match_id}")
        seen_ids.add(match_id)

        season_end_year = row.get("season_end_year")
        if isinstance(season_end_year, bool) or not isinstance(season_end_year, int):
            raise LigaFHistoryError(f"{location}.season_end_year must be an integer")
        expected_season = f"{season_end_year - 1}-{str(season_end_year)[-2:]}"
        if row.get("season") != expected_season:
            raise LigaFHistoryError(f"{location}.season does not match season_end_year")
        if row.get("provider") != "LIGA_F" or row.get("competition_id") != "LIGA_F":
            raise LigaFHistoryError(f"{location} has an invalid provider or competition")
        if row.get("gender") != "women":
            raise LigaFHistoryError(f"{location}.gender must equal women")
        if row.get("training_label_eligible") is not False:
            raise LigaFHistoryError(f"{location} must remain excluded from model training")
        if not isinstance(row.get("training_exclusion_reason"), str) or not row["training_exclusion_reason"].strip():
            raise LigaFHistoryError(f"{location} is missing its training exclusion reason")

        matchday = row.get("matchday")
        if isinstance(matchday, bool) or not isinstance(matchday, int) or matchday < 1:
            raise LigaFHistoryError(f"{location}.matchday must be a positive integer")
        if matchday > requested_rounds.get(season_end_year, 0):
            raise LigaFHistoryError(f"{location} exceeds the requested matchday range")

        home = row.get("home_team_name")
        away = row.get("away_team_name")
        if not isinstance(home, str) or not home.strip() or not isinstance(away, str) or not away.strip():
            raise LigaFHistoryError(f"{location} has missing team names")
        if _normalized_name(home) == _normalized_name(away):
            raise LigaFHistoryError(f"{location} has identical home and away teams")

        match_url = _official_url(row.get("match_url", ""), f"{location}.match_url")
        match_path = MATCH_PATH.fullmatch(urlparse(match_url).path)
        if match_path is None or match_path.group(1) != match_id:
            raise LigaFHistoryError(f"{location}.match_url does not identify match_id")
        round_url = _official_url(row.get("round_url", ""), f"{location}.round_url")
        expected_round_path = (
            f"/resultados/primera_division_femenina/{matchday}/{season_end_year}"
        )
        if urlparse(round_url).path.rstrip("/") != expected_round_path:
            raise LigaFHistoryError(f"{location}.round_url does not match season/matchday")
        scheduled_pair = (
            expected_season,
            _normalized_name(home),
            _normalized_name(away),
        )
        if scheduled_pair in seen_scheduled_pairs:
            raise LigaFHistoryError(f"duplicate scheduled home/away pair: {scheduled_pair}")
        seen_scheduled_pairs.add(scheduled_pair)
        for field in (
            "match_source_sha256",
            "round_source_sha256",
        ):
            digest = row.get(field)
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise LigaFHistoryError(f"{location}.{field} must be a SHA-256 hex digest")

        status = row.get("match_status")
        if status == "played":
            kickoff_raw = row.get("kickoff_at")
            if not isinstance(kickoff_raw, str):
                raise LigaFHistoryError(f"{location} played match is missing kickoff_at")
            try:
                kickoff = datetime.fromisoformat(kickoff_raw)
            except ValueError as exc:
                raise LigaFHistoryError(f"{location}.kickoff_at is invalid") from exc
            if kickoff.tzinfo is None or kickoff.utcoffset() is None:
                raise LigaFHistoryError(f"{location}.kickoff_at must include timezone")
            season_start = date(season_end_year - 1, 7, 1)
            season_end = date(season_end_year, 6, 30)
            if not season_start <= kickoff.date() <= season_end:
                raise LigaFHistoryError(f"{location}.kickoff_at falls outside its season")
            goals = (row.get("home_goals"), row.get("away_goals"))
            if any(isinstance(goal, bool) or not isinstance(goal, int) or goal < 0 for goal in goals):
                raise LigaFHistoryError(f"{location} has invalid full-time goals")
            expected_result = (
                "1"
                if goals[0] > goals[1]
                else "2"
                if goals[0] < goals[1]
                else "X"
            )
            if row.get("result_1x2") != expected_result:
                raise LigaFHistoryError(f"{location} result conflicts with the full-time score")
            fixture_key = (
                expected_season,
                kickoff.astimezone(UTC).isoformat(),
                _normalized_name(home),
                _normalized_name(away),
            )
            if fixture_key in seen_fixtures:
                raise LigaFHistoryError(f"duplicate canonical Liga F fixture: {fixture_key}")
            seen_fixtures.add(fixture_key)
        elif status in {"postponed", "suspended", "in_progress"}:
            if row.get("home_goals") is not None or row.get("away_goals") is not None or row.get("result_1x2") is not None:
                raise LigaFHistoryError(f"{location} non-final fixture contains a football result")
        else:
            raise LigaFHistoryError(f"{location} has unsupported match_status {status!r}")

        if row.get("match_source_cache_stale") or row.get("round_source_cache_stale"):
            stale_sources.add(row["match_url"] if row.get("match_source_cache_stale") else row["round_url"])
        grouped[season_end_year].append(row)

    season_profiles: dict[str, Any] = {}
    for season_end_year, rounds in requested_rounds.items():
        rows = grouped.get(season_end_year, [])
        expected_scheduled = rounds * expected_fixtures_per_round
        matchday_counts = Counter(row["matchday"] for row in rows)
        missing_rounds = [
            matchday
            for matchday in range(1, rounds + 1)
            if matchday_counts.get(matchday, 0) != expected_fixtures_per_round
        ]
        played = [row for row in rows if row["match_status"] == "played"]
        postponed = [row for row in rows if row["match_status"] == "postponed"]
        suspended = [row for row in rows if row["match_status"] == "suspended"]
        in_progress = [row for row in rows if row["match_status"] == "in_progress"]

        if len(rows) != expected_scheduled:
            raise LigaFHistoryError(
                f"season {season_end_year} has {len(rows)} scheduled fixtures; "
                f"expected {expected_scheduled}"
            )
        if missing_rounds:
            raise LigaFHistoryError(
                f"season {season_end_year} has invalid round coverage: {missing_rounds}"
            )

        team_home = Counter(row["home_team_name"] for row in played)
        team_away = Counter(row["away_team_name"] for row in played)
        appearances = team_home + team_away
        scheduled_teams = {
            _normalized_name(team)
            for row in rows
            for team in (row["home_team_name"], row["away_team_name"])
        }
        if len(scheduled_teams) != 16:
            raise LigaFHistoryError(
                f"season {season_end_year} does not contain the expected 16 scheduled teams"
            )
        if season_end_year in completed_seasons:
            if postponed or suspended or in_progress:
                raise LigaFHistoryError(
                    f"completed season {season_end_year} still has non-final fixtures"
                )
            if len(played) != expected_scheduled:
                raise LigaFHistoryError(
                    f"completed season {season_end_year} has {len(played)} played fixtures; "
                    f"expected {expected_scheduled}"
                )
            if len(appearances) != 16 or any(count != 30 for count in appearances.values()):
                raise LigaFHistoryError(
                    f"completed season {season_end_year} does not have 16 teams with 30 appearances each"
                )
            if any(count != 15 for count in team_home.values()) or any(
                count != 15 for count in team_away.values()
            ):
                raise LigaFHistoryError(
                    f"completed season {season_end_year} does not have 15 home and 15 away matches per team"
                )

        season_profiles[str(season_end_year)] = {
            "season": f"{season_end_year - 1}-{str(season_end_year)[-2:]}",
            "requested_matchdays": rounds,
            "scheduled_fixtures": len(rows),
            "played_fixtures": len(played),
            "postponed_fixtures": len(postponed),
            "suspended_fixtures": len(suspended),
            "in_progress_fixtures": len(in_progress),
            "team_count_in_played_fixtures": len(appearances),
            "rounds_with_expected_fixture_count": rounds - len(missing_rounds),
            "missing_or_incomplete_rounds": missing_rounds,
        }

    if set(grouped) - set(requested_rounds):
        raise LigaFHistoryError("history contains an unrequested season")

    return {
        "schema_version": 1,
        "provider": "LIGA_F",
        "competition_id": "LIGA_F",
        "gender": "women",
        "source_host": "ligaf.es",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "season_profiles": season_profiles,
        "total_scheduled_fixtures": len(records),
        "total_played_fixtures": sum(row["match_status"] == "played" for row in records),
        "total_non_final_fixtures": sum(row["match_status"] != "played" for row in records),
        "unique_match_ids": len(seen_ids),
        "stale_cache_sources": sorted(stale_sources),
        "training_eligibility": {
            "eligible": False,
            "reason": TRAINING_EXCLUSION_REASON,
        },
        "integrity_passed": True,
    }


def import_ligaf_history(
    *,
    seasons: tuple[int, ...] = DEFAULT_SEASONS,
    current_season: int = 2027,
    max_current_matchday: int = 10,
    rounds_per_season: int = 30,
    expected_fixtures_per_round: int = 8,
    output: str | Path = DEFAULT_OUTPUT,
    profile_output: str | Path = DEFAULT_PROFILE,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    cache_ttl_hours: float = 24.0,
    refresh: bool = False,
    offline: bool = False,
    request_delay: float = 0.25,
    session: requests.Session | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected = tuple(dict.fromkeys(int(year) for year in seasons))
    if not selected:
        raise ValueError("at least one season must be selected")
    if current_season not in selected:
        raise ValueError("current_season must be included in seasons")
    if rounds_per_season != 30:
        raise ValueError("Liga F archive validation currently requires 30 matchdays")
    if not 1 <= max_current_matchday <= rounds_per_season:
        raise ValueError("max_current_matchday is outside the season")
    if any(year < 2023 or year > 2100 for year in selected):
        raise ValueError("season end years must be between 2023 and 2100")

    requested_rounds = {
        year: max_current_matchday if year == current_season else rounds_per_season
        for year in selected
    }
    completed_seasons = set(selected) - {current_season}
    client = session or make_session()
    records: list[dict[str, Any]] = []
    for season_end_year in selected:
        for matchday in range(1, requested_rounds[season_end_year] + 1):
            round_url = ARCHIVE_URL.format(
                matchday=matchday, season_end_year=season_end_year
            )
            round_html, round_meta = fetch_html(
                round_url,
                cache_dir=cache_dir,
                session=client,
                cache_ttl_hours=cache_ttl_hours,
                refresh=refresh,
                offline=offline,
                request_delay=request_delay,
            )
            links = extract_match_links(round_html, page_url=round_url)
            round_dates = extract_round_dates(
                round_html,
                season_end_year=season_end_year,
            )
            if len(links) != expected_fixtures_per_round:
                raise LigaFHistoryError(
                    f"season {season_end_year} matchday {matchday} exposes "
                    f"{len(links)} match links; expected {expected_fixtures_per_round}"
                )
            for link in links:
                match_html, match_meta = fetch_html(
                    link["match_url"],
                    cache_dir=cache_dir,
                    session=client,
                    cache_ttl_hours=cache_ttl_hours,
                    refresh=refresh,
                    offline=offline,
                    request_delay=request_delay,
                )
                row = parse_match_detail(
                    match_html,
                    match_url=link["match_url"],
                    season_end_year=season_end_year,
                    expected_matchday=matchday,
                    round_url=round_url,
                    match_source_metadata=match_meta,
                    round_source_metadata=round_meta,
                    allowed_round_dates=round_dates,
                )
                row["match_source_cache_stale"] = bool(match_meta.get("cache_stale"))
                row["round_source_cache_stale"] = bool(round_meta.get("cache_stale"))
                records.append(row)

    profile = validate_history(
        records,
        completed_seasons=completed_seasons,
        requested_rounds=requested_rounds,
        expected_fixtures_per_round=expected_fixtures_per_round,
    )
    output_path = Path(output)
    profile_path = Path(profile_output)
    jsonl = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in sorted(
            records,
            key=lambda item: (
                item["season_end_year"],
                item["matchday"],
                item["kickoff_at"] or "",
                item["match_id"],
            ),
        )
    )
    _atomic_write(output_path, jsonl.encode("utf-8"))
    _atomic_write(
        profile_path,
        (json.dumps(profile, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
    )
    log.info(
        "Liga F history written: %s; scheduled=%d; played=%d; non-final=%d",
        output_path,
        profile["total_scheduled_fixtures"],
        profile["total_played_fixtures"],
        profile["total_non_final_fixtures"],
    )
    return records, profile


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and validate official Liga F match history."
    )
    parser.add_argument("--seasons", nargs="+", type=int, default=list(DEFAULT_SEASONS))
    parser.add_argument("--current-season", type=int, default=2027)
    parser.add_argument("--max-current-matchday", type=int, default=10)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--profile-output", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--cache-ttl-hours", type=float, default=24.0)
    parser.add_argument("--request-delay", type=float, default=0.25)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--offline", action="store_true")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = _parse_args()
    records, profile = import_ligaf_history(
        seasons=tuple(args.seasons),
        current_season=args.current_season,
        max_current_matchday=args.max_current_matchday,
        output=args.output,
        profile_output=args.profile_output,
        cache_dir=args.cache_dir,
        cache_ttl_hours=args.cache_ttl_hours,
        refresh=args.refresh,
        offline=args.offline,
        request_delay=args.request_delay,
    )
    print(
        f"LIGA_F_HISTORY_OK: scheduled={len(records)} "
        f"played={profile['total_played_fixtures']} "
        f"non_final={profile['total_non_final_fixtures']}"
    )


if __name__ == "__main__":
    main()
