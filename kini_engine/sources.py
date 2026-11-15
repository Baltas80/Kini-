from __future__ import annotations

import logging
import math
import time
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import requests
import xmltodict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .core import SIGNS

log = logging.getLogger(__name__)


class KinielaGPTSource:
    """KinielaGPT-compatible source adapter for LAE/Quinielista percentages and details."""

    BASE = "https://www.quinielista.es/xml2/porcentajes.asp"
    LAE = "https://www.quinielista.es/xml2/porcentajes_lae.asp?jornada={}&temporada={}"
    QUINI = "https://www.quinielista.es/xml2/porcentajes.asp?jornada={}&temporada={}"
    DETAILS = "https://api.eduardolosilla.es/detallePartido"
    HOME = "https://www.eduardolosilla.es/"
    LAE_SOURCE = "quinielista.es:porcentajes_lae.asp"
    QUINIELISTA_SOURCE = "quinielista.es:porcentajes.asp"

    def __init__(self, timeout: int = 15) -> None:
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

    def last(self) -> tuple[int, int, list[dict[str, Any]]]:
        data = self._xml(self.BASE)["quinielista"]["porcentajes"]
        jornada = int(data["jornada"])
        temporada = int(data["temporada"])
        matches = [
            {"id": int(p["num"]), "home": p["local"], "away": p["visitante"]}
            for p in data["partido"]
        ]
        return jornada, temporada, matches

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

            out.append(
                {
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
                }
            )
        return out

    def details_payload(
        self, jornada: int, temporada: int
    ) -> tuple[dict[str, Any], str]:
        """Return the provider JSON unchanged plus its local response-receipt time.

        The timestamp is when this client received the HTTP response. It is not
        evidence of the provider's publication time or of a fixture's kickoff.
        """
        self.session.get(
            self.HOME, headers=self.headers, timeout=self.timeout
        ).raise_for_status()
        response = self.session.get(
            self.DETAILS,
            params={
                "jornada": jornada,
                "temporada": temporada,
                "uts": int(time.time() * 1000),
            },
            headers=self.headers,
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
