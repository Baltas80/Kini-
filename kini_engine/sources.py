from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd
import requests
import xmltodict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)


class KinielaGPTSource:
    """KinielaGPT-compatible source adapter for LAE/Quinielista percentages and details."""

    BASE = "https://www.quinielista.es/xml2/porcentajes.asp"
    LAE = "https://www.quinielista.es/xml2/porcentajes_lae.asp?jornada={}&temporada={}"
    QUINI = "https://www.quinielista.es/xml2/porcentajes.asp?jornada={}&temporada={}"
    DETAILS = "https://api.eduardolosilla.es/detallePartido"
    HOME = "https://www.eduardolosilla.es/"

    def __init__(self, timeout: int = 15) -> None:
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.timeout = timeout
        self.headers = {"User-Agent": "Kini/0.2 (+https://github.com/Baltas80/Kini-)", "Accept-Language": "es-ES,es;q=0.9"}

    def _xml(self, url: str) -> dict[str, Any]:
        r = self.session.get(url, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return xmltodict.parse(r.content, attr_prefix="")

    def last(self) -> tuple[int, int, list[dict[str, Any]]]:
        data = self._xml(self.BASE)["quinielista"]["porcentajes"]
        jornada = int(data["jornada"])
        temporada = int(data["temporada"])
        matches = [{"id": int(p["num"]), "home": p["local"], "away": p["visitante"]} for p in data["partido"]]
        return jornada, temporada, matches

    def probabilities(self, jornada: int, temporada: int) -> list[dict[str, Any]]:
        a = self._xml(self.LAE.format(jornada, temporada))
        b = self._xml(self.QUINI.format(jornada, temporada))
        pa = pd.DataFrame(a["quinielista"]["porcentajes"]["partido"]).fillna(0)
        pb = pd.DataFrame(b["quinielista"]["porcentajes"]["partido"]).fillna(0)
        both = pd.concat([pa, pb], ignore_index=True)
        both["num"] = pd.to_numeric(both["num"], errors="coerce").fillna(0).astype(int)
        cols = [c for c in both.columns if c.startswith("porc_")]
        both[cols] = both[cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
        agg = {"local": "first", "visitante": "first"} | {c: "mean" for c in cols}
        out = both.groupby("num").agg(agg).reset_index()
        out = out.rename(columns={"num": "id", "porc_1": "1", "porc_X": "X", "porc_2": "2"})
        for c in SIGNS:
            if c not in out:
                out[c] = 0.0
        s = out[list(SIGNS)].sum(axis=1).replace(0, 1)
        out[list(SIGNS)] = out[list(SIGNS)].div(s, axis=0)
        return out.to_dict("records")

    def details(self, jornada: int, temporada: int) -> list[dict[str, Any]]:
        self.session.get(self.HOME, headers=self.headers, timeout=self.timeout).raise_for_status()
        r = self.session.get(self.DETAILS, params={"jornada": jornada, "temporada": temporada, "uts": int(time.time() * 1000)}, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("detallePartidos", [])


class SelaeSource:
    """SELAE JSON-first fixture/results adapter with HTML fallback."""

    BASE = "https://www.loteriasyapuestas.es"
    SEARCH = BASE + "/servicios/buscadorSorteos"
    QUINIELA = BASE + "/es/quiniela"

    def __init__(self, timeout: int = 15) -> None:
        self.session = requests.Session()
        self.timeout = timeout
        self.headers = {"User-Agent": "Kini/0.2", "Accept-Language": "es-ES,es;q=0.9"}

    def fixture(self, date_yyyymmdd: str) -> dict[str, Any] | None:
        r = self.session.get(self.SEARCH, params={"game_id": "LAQU", "celebrados": "false", "fechaInicioInclusiva": date_yyyymmdd, "num_results": 1}, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        if not data:
            return None
        s = data[0] if isinstance(data, list) else data
        raw = s.get("partidos") or s.get("jornada_partidos") or s.get("combinacion") or []
        parts = []
        for i, p in enumerate(raw, 1):
            parts.append({"numero": i, "local": (p.get("equipoLocal") or p.get("local") or "").strip(), "visitante": (p.get("equipoVisitante") or p.get("visitante") or "").strip(), "pleno15": i == 15})
        return {"numero_jornada": s.get("num_sorteo") or s.get("jornada"), "fecha_cierre": s.get("fecha_sorteo"), "partidos": parts, "fuente": "selae_json"}
