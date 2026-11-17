from __future__ import annotations

import json
import logging
import math
import os
import time
import unicodedata
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd
import requests
import xmltodict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .core import LAE_KICKOFF_EVIDENCE_MAX_AGE, LAE_SOURCE_ID, SIGNS

log = logging.getLogger(__name__)


def _normalize_fixture_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    normalized = " ".join(
        "".join(
            character if character.isalnum() else " " for character in without_marks
        ).split()
    )
    return normalized or None


def _parse_aware_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


class KinielaGPTAuthorizationRequired(RuntimeError):
    """Raised when the provider details API is used without its required auth header."""


class KinielaGPTSource:
    """KinielaGPT-compatible source adapter for LAE/Quinielista percentages and details."""

    BASE = "https://www.quinielista.es/xml2/porcentajes.asp"
    LAE = "https://www.quinielista.es/xml2/porcentajes_lae.asp?jornada={}&temporada={}"
    QUINI = "https://www.quinielista.es/xml2/porcentajes.asp?jornada={}&temporada={}"
    DETAILS = "https://api.eduardolosilla.es/detallePartido"
    HOME = "https://www.eduardolosilla.es/"
    DETAILS_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
    )
    DETAILS_HOME_HEADERS: ClassVar[dict[str, str]] = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "es-ES,es;q=0.9,en;q=0.8",
        "user-agent": DETAILS_USER_AGENT,
    }
    DETAILS_REQUEST_HEADERS: ClassVar[dict[str, str]] = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "es-ES,es;q=0.9,en;q=0.8",
        "cache-control": "no-cache",
        "origin": "https://www.eduardolosilla.es",
        "pragma": "no-cache",
        "referer": "https://www.eduardolosilla.es/",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": DETAILS_USER_AGENT,
    }
    LAE_SOURCE = LAE_SOURCE_ID
    QUINIELISTA_SOURCE = "quinielista.es:porcentajes.asp"
    KICKOFF_CROSSWALK_PATH = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "kinielagpt_fixture_kickoffs.json"
    )

    def __init__(
        self,
        timeout: int = 15,
        authorization: str | None = None,
    ) -> None:
        configured_authorization = authorization or os.environ.get(
            "KINIELAGPT_AUTHORIZATION"
        )
        self.authorization = (
            configured_authorization.strip() if configured_authorization else None
        ) or None
        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Kini/0.2 (+https://github.com/Baltas80/Kini-)",
            "Accept-Language": "es-ES,es;q=0.9",
        }
        self.last_round_resolution: dict[str, Any] | None = None

    def _xml_snapshot(self, url: str) -> tuple[dict[str, Any], str]:
        """Fetch XML and timestamp when its complete response became available locally."""
        response = self.session.get(url, headers=self.headers, timeout=self.timeout)
        response.raise_for_status()
        captured_at = datetime.now(UTC).isoformat()
        return xmltodict.parse(response.content, attr_prefix=""), captured_at

    def _xml(self, url: str) -> dict[str, Any]:
        """Compatibility wrapper for callers that do not need response provenance."""
        payload, _ = self._xml_snapshot(url)
        return payload

    @staticmethod
    def _probability_map(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
        """Extract one normalized probability vector per match ID from a source response."""
        root = payload.get("quinielista", {})
        percentages = root.get("porcentajes", {}) if isinstance(root, dict) else {}
        raw_matches = (
            percentages.get("partido", []) if isinstance(percentages, dict) else []
        )
        if isinstance(raw_matches, dict):
            records = [raw_matches]
        elif isinstance(raw_matches, list):
            records = raw_matches
        else:
            records = []

        frame = pd.DataFrame(records)
        if frame.empty or "num" not in frame:
            return {}

        for column in ("local", "visitante"):
            if column not in frame:
                frame[column] = ""

        frame["num"] = pd.to_numeric(frame["num"], errors="coerce")
        frame = frame.dropna(subset=["num"]).copy()
        if frame.empty:
            return {}
        frame["num"] = frame["num"].astype(int)

        probability_columns = {"1": "porc_1", "X": "porc_X", "2": "porc_2"}
        for column in probability_columns.values():
            if column not in frame:
                frame[column] = 0.0
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

        aggregations = {"local": "first", "visitante": "first"} | {
            column: "mean" for column in probability_columns.values()
        }
        grouped = frame.groupby("num", sort=True).agg(aggregations)
        result: dict[int, dict[str, Any]] = {}

        for match_id, row in grouped.iterrows():
            values: list[float] = []
            valid = True
            for column in probability_columns.values():
                value = row[column]
                if pd.isna(value):
                    valid = False
                    break
                numeric = float(value)
                if not math.isfinite(numeric) or numeric < 0:
                    valid = False
                    break
                values.append(numeric)

            total = sum(values)
            probabilities = (
                dict(zip(SIGNS, (value / total for value in values)))
                if valid and math.isfinite(total) and total > 0
                else None
            )
            local = row["local"]
            away = row["visitante"]
            result[int(match_id)] = {
                "local": str(local) if pd.notna(local) else "",
                "visitante": str(away) if pd.notna(away) else "",
                "probabilities": probabilities,
            }
        return result

    @staticmethod
    def _combined_probabilities(*vectors: dict[str, float] | None) -> dict[str, float]:
        """Return an equal-weight mean of available, individually normalized sources."""
        available = [vector for vector in vectors if vector is not None]
        if not available:
            return {sign: 0.0 for sign in SIGNS}
        return {
            sign: sum(vector[sign] for vector in available) / len(available)
            for sign in SIGNS
        }

    @staticmethod
    def _active_flag(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().casefold() if value is not None else ""
        if normalized in {"si", "sí", "yes", "true", "1"}:
            return True
        if normalized in {"no", "false", "0"}:
            return False
        return None

    @staticmethod
    def _matches_from_probability_rows(
        rows: dict[int, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": match_id,
                "home": row.get("local", ""),
                "away": row.get("visitante", ""),
            }
            for match_id, row in sorted(rows.items())
        ]

    def last(self) -> tuple[int, int, list[dict[str, Any]]]:
        base_payload = self._xml(self.BASE)
        data = base_payload["quinielista"]["porcentajes"]
        base_jornada = int(data["jornada"])
        temporada = int(data["temporada"])
        base_rows = self._probability_map(base_payload)
        base_matches = self._matches_from_probability_rows(base_rows)

        candidates: list[dict[str, Any]] = []
        selected_jornada: int | None = None
        selected_matches = base_matches
        resolution_reason = "base_feed_no_active_lae_round_found"

        # The BASE feed can advance to a future jornada before its LAE market opens.
        # Prefer the most recent round explicitly marked active by the LAE feed.
        for candidate in range(base_jornada, max(base_jornada - 3, 0), -1):
            lae_payload = self._xml(self.LAE.format(candidate, temporada))
            percentages = lae_payload.get("quinielista", {}).get("porcentajes", {})
            active_raw = (
                percentages.get("activo") if isinstance(percentages, dict) else None
            )
            active = self._active_flag(active_raw)
            lae_rows = self._probability_map(lae_payload)
            valid_vector_count = sum(
                row.get("probabilities") is not None for row in lae_rows.values()
            )
            matches = self._matches_from_probability_rows(lae_rows)
            candidates.append(
                {
                    "jornada": candidate,
                    "active_raw": str(active_raw) if active_raw is not None else None,
                    "active": active,
                    "valid_lae_vector_count": valid_vector_count,
                    "match_count": len(matches),
                }
            )

            if active is True or (active is None and valid_vector_count > 0):
                selected_jornada = candidate
                selected_matches = matches or (
                    base_matches if candidate == base_jornada else []
                )
                resolution_reason = (
                    "active_lae_round"
                    if active is True
                    else "nonzero_lae_vectors_without_active_flag"
                )
                break

        if selected_jornada is None:
            selected_jornada = base_jornada
            selected_matches = base_matches

        self.last_round_resolution = {
            "base_jornada": base_jornada,
            "resolved_jornada": selected_jornada,
            "temporada": temporada,
            "reason": resolution_reason,
            "candidates": candidates,
        }
        return selected_jornada, temporada, selected_matches

    @classmethod
    def _load_kickoff_crosswalk(
        cls, jornada: int, temporada: int
    ) -> dict[tuple[int, str, str], dict[str, str]]:
        """Load only a fully verified, timezone-aware fixture schedule."""
        try:
            payload = json.loads(cls.KICKOFF_CROSSWALK_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Kickoff crosswalk unavailable: %s", exc)
            return {}

        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != 1
            or payload.get("jornada") != jornada
            or payload.get("temporada") != temporada
        ):
            return {}

        fixtures = payload.get("fixtures")
        evidence = payload.get("crosswalk_evidence")
        raw_sources = payload.get("schedule_sources")
        if (
            not isinstance(fixtures, list)
            or not fixtures
            or not isinstance(evidence, dict)
            or not isinstance(raw_sources, list)
            or evidence.get("status") != "verified"
            or any(
                evidence.get(field) != len(fixtures)
                for field in (
                    "details_count",
                    "percentage_matches_count",
                    "verified_count",
                )
            )
        ):
            log.warning("Kickoff crosswalk has incomplete verification evidence")
            return {}

        checked_at = _parse_aware_timestamp(
            payload.get("schedule_evidence_checked_at_utc")
        )
        crosswalk_checked_at = _parse_aware_timestamp(evidence.get("checked_at_utc"))
        if (
            checked_at is None
            or crosswalk_checked_at is None
            or checked_at < crosswalk_checked_at
        ):
            log.warning("Kickoff schedule evidence timestamp is missing or invalid")
            return {}

        sources: dict[str, dict[str, Any]] = {}
        for source in raw_sources:
            if not isinstance(source, dict):
                return {}
            source_id = source.get("id")
            url = source.get("url")
            try:
                published_date = date.fromisoformat(source.get("published_date", ""))
            except (TypeError, ValueError):
                return {}
            if (
                not isinstance(source_id, str)
                or not source_id
                or source_id in sources
                or not isinstance(url, str)
                or not url.startswith("https://www.uefa.com/")
                or source.get("timezone") not in {"CET", "CEST"}
                or not isinstance(source.get("competition"), str)
                or published_date > checked_at.date()
            ):
                log.warning("Kickoff crosswalk contains an untrusted schedule source")
                return {}
            sources[source_id] = source

        weekday_numbers = {
            "LUN": 0,
            "MAR": 1,
            "MIE": 2,
            "JUE": 3,
            "VIE": 4,
            "SAB": 5,
            "DOM": 6,
        }
        mapping: dict[tuple[int, str, str], dict[str, str]] = {}
        seen_numbers: set[int] = set()

        for fixture in fixtures:
            if not isinstance(fixture, dict):
                return {}
            number = fixture.get("num")
            if isinstance(number, bool) or not isinstance(number, int) or number < 1:
                return {}
            home = _normalize_fixture_name(fixture.get("home_provider_name"))
            away = _normalize_fixture_name(fixture.get("away_provider_name"))
            kickoff = _parse_aware_timestamp(fixture.get("kickoff_at"))
            source = sources.get(fixture.get("schedule_source_id"))
            day_label = fixture.get("provider_day_label")
            clock_time = fixture.get("provider_clock_time")

            source_timezone = source.get("timezone") if source is not None else None
            expected_offset = (
                {"CET": timedelta(hours=1), "CEST": timedelta(hours=2)}.get(
                    source_timezone
                )
                if isinstance(source_timezone, str)
                else None
            )

            if (
                number in seen_numbers
                or home is None
                or away is None
                or kickoff is None
                or expected_offset is None
                or kickoff.utcoffset() != expected_offset
                or kickoff <= checked_at
                or source is None
                or weekday_numbers.get(day_label) != kickoff.weekday()
                or clock_time != kickoff.strftime("%H:%M")
            ):
                log.warning("Kickoff crosswalk contains an invalid fixture row")
                return {}

            seen_numbers.add(number)
            mapping[(number, home, away)] = {
                "kickoff_at": kickoff.isoformat(),
                "kickoff_source": source["competition"],
                "kickoff_evidence_url": source["url"],
                "kickoff_evidence_checked_at_utc": checked_at.isoformat(),
                "kickoff_timezone": source["timezone"],
            }

        return mapping

    def probabilities(self, jornada: int, temporada: int) -> list[dict[str, Any]]:
        """Return the legacy blend plus separate, timestamped source vectors.

        Capture timestamps are local response-receipt times. They prove when this
        client obtained a response, not when the provider originally published or
        last refreshed its contents.
        """
        lae_payload, lae_captured_at = self._xml_snapshot(
            self.LAE.format(jornada, temporada)
        )
        quinielista_payload, quinielista_captured_at = self._xml_snapshot(
            self.QUINI.format(jornada, temporada)
        )
        lae_rows = self._probability_map(lae_payload)
        quinielista_rows = self._probability_map(quinielista_payload)
        kickoff_map = self._load_kickoff_crosswalk(jornada, temporada)

        out = []
        for match_id in sorted(set(lae_rows) | set(quinielista_rows)):
            lae_row = lae_rows.get(match_id)
            quinielista_row = quinielista_rows.get(match_id)
            lae_probabilities = lae_row["probabilities"] if lae_row else None
            quinielista_probabilities = (
                quinielista_row["probabilities"] if quinielista_row else None
            )
            combined = self._combined_probabilities(
                lae_probabilities, quinielista_probabilities
            )
            preferred = lae_row or quinielista_row or {}
            result_row = {
                "id": match_id,
                "local": preferred.get("local", ""),
                "visitante": preferred.get("visitante", ""),
                **combined,
                "lae": lae_probabilities,
                "lae_source": self.LAE_SOURCE if lae_row else None,
                "lae_captured_at": lae_captured_at if lae_row else None,
                "quinielista": quinielista_probabilities,
                "quinielista_source": self.QUINIELISTA_SOURCE
                if quinielista_row
                else None,
                "quinielista_captured_at": quinielista_captured_at
                if quinielista_row
                else None,
                "probability_method": "equal_weight_mean_of_available_source_vectors",
                "kickoff_at": None,
                "kickoff_source": None,
                "kickoff_evidence_url": None,
                "kickoff_evidence_checked_at_utc": None,
                "kickoff_timezone": None,
                "fixture_identity_status": "unverified",
            }

            if quinielista_row is not None:
                home = _normalize_fixture_name(quinielista_row.get("local"))
                away = _normalize_fixture_name(quinielista_row.get("visitante"))
                candidate = (
                    kickoff_map.get((match_id, home, away))
                    if home is not None and away is not None
                    else None
                )
                source_rows = [quinielista_row]
                if lae_row is not None:
                    source_rows.append(lae_row)
                names_match = candidate is not None and all(
                    _normalize_fixture_name(source_row.get("local")) == home
                    and _normalize_fixture_name(source_row.get("visitante")) == away
                    for source_row in source_rows
                )
                evidence_checked_at = (
                    _parse_aware_timestamp(
                        candidate.get("kickoff_evidence_checked_at_utc")
                    )
                    if candidate is not None
                    else None
                )
                lae_received_at = _parse_aware_timestamp(lae_captured_at)
                evidence_age = (
                    lae_received_at - evidence_checked_at
                    if evidence_checked_at is not None and lae_received_at is not None
                    else None
                )
                evidence_precedes_capture = lae_row is None or (
                    evidence_age is not None
                    and timedelta(0) <= evidence_age <= LAE_KICKOFF_EVIDENCE_MAX_AGE
                )
                if names_match and evidence_precedes_capture:
                    result_row.update(candidate)
                    result_row["fixture_identity_status"] = "verified"
                elif candidate is not None and names_match:
                    result_row["fixture_identity_status"] = (
                        "schedule_evidence_after_lae_capture"
                        if evidence_age is not None and evidence_age < timedelta(0)
                        else "schedule_evidence_stale"
                    )
                elif candidate is not None:
                    result_row["fixture_identity_status"] = "source_name_mismatch"

            out.append(result_row)
        return out

    def details_payload(
        self, jornada: int, temporada: int
    ) -> tuple[dict[str, Any], str]:
        """Return the provider JSON unchanged plus its local response-receipt time.

        The timestamp is when this client received the HTTP response. It is not
        evidence of the provider's publication time or of a fixture's kickoff.
        """
        if not self.authorization:
            raise KinielaGPTAuthorizationRequired(
                "KinielaGPT details API requires an Authorization header; configure "
                "KINIELAGPT_AUTHORIZATION with the provider-issued header value."
            )

        self.session.get(
            self.HOME,
            headers=self.DETAILS_HOME_HEADERS,
            timeout=self.timeout,
        ).raise_for_status()
        details_headers = dict(self.DETAILS_REQUEST_HEADERS)
        details_headers["Authorization"] = self.authorization
        response = self.session.get(
            self.DETAILS,
            params={
                "jornada": jornada,
                "temporada": temporada,
                "uts": int(time.time() * 1000),
            },
            headers=details_headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        captured_at = datetime.now(UTC).isoformat()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("KinielaGPT details response must be a JSON object")
        return payload, captured_at

    def details(self, jornada: int, temporada: int) -> list[dict[str, Any]]:
        """Return the provider's detail records, failing on an unknown schema."""
        payload, _ = self.details_payload(jornada, temporada)
        if "detallePartidos" not in payload:
            raise ValueError("KinielaGPT details response is missing 'detallePartidos'")
        records = payload["detallePartidos"]
        if not isinstance(records, list):
            raise TypeError("KinielaGPT 'detallePartidos' must be a JSON array")
        if any(not isinstance(record, dict) for record in records):
            raise TypeError("KinielaGPT detail records must be JSON objects")
        return records


class SelaeSource:
    """SELAE JSON-first fixture/results adapter with a stable external interface."""

    BASE = "https://www.loteriasyapuestas.es"
    SEARCH = BASE + "/servicios/buscadorSorteos"

    def __init__(self, timeout: int = 15) -> None:
        self.session = requests.Session()
        self.timeout = timeout
        self.headers = {"User-Agent": "Kini/0.2", "Accept-Language": "es-ES,es;q=0.9"}

    def fixture(self, date_yyyymmdd: str) -> dict[str, Any] | None:
        response = self.session.get(
            self.SEARCH,
            params={
                "game_id": "LAQU",
                "celebrados": "false",
                "fechaInicioInclusiva": date_yyyymmdd,
                "num_results": 1,
            },
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not data:
            return None
        draw = data[0] if isinstance(data, list) else data
        raw = (
            draw.get("partidos")
            or draw.get("jornada_partidos")
            or draw.get("combinacion")
            or []
        )
        parts = [
            {
                "numero": i,
                "local": (match.get("equipoLocal") or match.get("local") or "").strip(),
                "visitante": (
                    match.get("equipoVisitante") or match.get("visitante") or ""
                ).strip(),
                "pleno15": i == 15,
            }
            for i, match in enumerate(raw, 1)
        ]
        return {
            "numero_jornada": draw.get("num_sorteo") or draw.get("jornada"),
            "fecha_cierre": draw.get("fecha_sorteo"),
            "partidos": parts,
            "fuente": "selae_json",
        }
