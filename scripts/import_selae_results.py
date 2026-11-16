from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import tempfile
import time
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://www.loteriasyapuestas.es"
MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
DEFAULT_CACHE_DIR = Path(".cache/selae-quiniela")
DEFAULT_OUTPUT = Path("data/selae_quiniela_draws.jsonl")
DEFAULT_FIXTURE_OVERRIDES = (
    Path(__file__).resolve().parents[1] / "data" / "selae_fixture_overrides.json"
)
CACHE_TTL_HOURS = 24.0
TEAM_CATEGORY_RE = re.compile(r"^(.*?)\s+\(([MF])\)$", re.IGNORECASE)
SCORE_RE = re.compile(r"^(\d+)\s*[-–]\s*(\d+)$")
PLENO_SCORE_RE = re.compile(r"^(M|\d+)\s*[-–]\s*(M|\d+)$", re.IGNORECASE)
log = logging.getLogger("kini.selae")


class CouponPageParser(HTMLParser):
    """Collect visible list-item and table text without depending on SELAE CSS classes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.list_items: list[str] = []
        self.table_rows: list[list[str]] = []
        self.text_parts: list[str] = []
        self._li_stack: list[list[str]] = []
        self._cell_stack: list[list[str]] = []
        self._row_stack: list[list[str]] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "li":
            self._li_stack.append([])
        elif tag == "tr":
            self._row_stack.append([])
        elif tag in {"td", "th"}:
            self._cell_stack.append([])

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "li" and self._li_stack:
            value = " ".join(self._li_stack.pop()).strip()
            if value:
                self.list_items.append(value)
        elif tag in {"td", "th"} and self._cell_stack:
            value = " ".join(self._cell_stack.pop()).strip()
            if value and self._row_stack:
                self._row_stack[-1].append(value)
        elif tag == "tr" and self._row_stack:
            row = self._row_stack.pop()
            if row:
                self.table_rows.append(row)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = " ".join(data.split())
        if not value:
            return
        self.text_parts.append(value)
        if self._li_stack:
            self._li_stack[-1].append(value)
        if self._cell_stack:
            self._cell_stack[-1].append(value)


def make_draw_url(draw_date: date) -> str:
    month = MONTHS[draw_date.month - 1]
    return (
        f"{BASE_URL}/es/la-quiniela/escrutinios/"
        f"la-quiniela-premios-y-ganadores-del-{draw_date.day:02d}-de-{month}-de-{draw_date.year}"
    )


def _is_official_selae_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "www.loteriasyapuestas.es"
            and parsed.port in {None, 443}
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def _validated_utc_timestamp(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        timestamp = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if (
        timestamp.tzinfo is None
        or timestamp.utcoffset() is None
        or timestamp.utcoffset().total_seconds() != 0
    ):
        return None
    return timestamp.astimezone(UTC).isoformat()


def _clean(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split()).strip()


def _is_position_block(items: list[str], start: int) -> bool:
    expected = [str(i) for i in range(1, 15)]
    actual = [_clean(item).rstrip(".") for item in items[start : start + 14]]
    return actual == expected


def _is_score(value: str) -> bool:
    return SCORE_RE.fullmatch(_clean(value)) is not None


def _is_sign(value: str) -> bool:
    return _clean(value).upper() in {"1", "X", "2"}


def _is_team(value: str) -> bool:
    value = _clean(value)
    return bool(value) and value.casefold() != "pleno al quince" and value != "15" and not (
        value.isdigit() or _is_score(value) or _is_sign(value)
    )


def _parse_score(value: str) -> tuple[int, int]:
    match = SCORE_RE.fullmatch(_clean(value))
    if not match:
        raise ValueError(f"Marcador no válido: {value!r}")
    return int(match.group(1)), int(match.group(2))


def _team_fields(value: str) -> dict[str, str | None]:
    display_name = _clean(value)
    match = TEAM_CATEGORY_RE.fullmatch(display_name)
    if match:
        return {"name": match.group(1).strip(), "category_marker": match.group(2).upper(), "display_name": display_name}
    return {"name": display_name, "category_marker": None, "display_name": display_name}


def _find_fixture_groups(items: list[str]) -> tuple[list[str], list[str], list[str], list[str], int]:
    positions = [i for i in range(max(0, len(items) - 13)) if _is_position_block(items, i)]
    if len(positions) != 1:
        raise ValueError(f"Se esperaba un único bloque de posiciones 1..14; encontrados {len(positions)}")
    tail_start = positions[0] + 14
    candidates: list[tuple[list[str], list[str], list[str], list[str], int]] = []
    for start in range(tail_start, max(tail_start, len(items) - 55)):
        block = items[start : start + 56]
        if len(block) != 56:
            continue
        home, away, scores, signs = block[:14], block[14:28], block[28:42], block[42:56]
        if (
            all(_is_team(value) for value in home + away)
            and all(_is_score(value) for value in scores)
            and all(_is_sign(value) for value in signs)
        ):
            candidates.append((home, away, scores, [value.upper() for value in signs], start + 56))
    if len(candidates) != 1:
        raise ValueError(f"No se pudo aislar un único bloque completo de 14 partidos; candidatos={len(candidates)}")
    return candidates[0]


def _parse_pleno(items: list[str], after_index: int) -> dict[str, object]:
    marker = next(
        (i for i in range(after_index, len(items)) if _clean(items[i]).rstrip(".") == "15"),
        None,
    )
    if marker is None:
        raise ValueError("La página no contiene el marcador 15 del Pleno al 15")
    tail = items[marker + 1 :]
    teams: list[str] = []
    score_raw: str | None = None
    for value in tail:
        value = _clean(value)
        if score_raw is None and PLENO_SCORE_RE.fullmatch(value):
            score_raw = value
            break
        if _is_team(value):
            teams.append(value)
            if len(teams) == 2:
                continue
    if len(teams) < 2 or score_raw is None:
        raise ValueError("Pleno al 15 incompleto: faltan equipos o marcador")
    score_match = PLENO_SCORE_RE.fullmatch(score_raw)
    assert score_match is not None
    home_goals = None if score_match.group(1).upper() == "M" else int(score_match.group(1))
    away_goals = None if score_match.group(2).upper() == "M" else int(score_match.group(2))
    return {
        "home": _team_fields(teams[0]),
        "away": _team_fields(teams[1]),
        "score_raw": score_raw,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "score_complete": home_goals is not None and away_goals is not None,
    }


def _parse_integer(value: str) -> int | None:
    compact = _clean(value).replace(".", "").replace(" ", "")
    if not compact or compact in {"-", "—"}:
        return None
    if not compact.isdigit():
        return None
    return int(compact)


def _parse_eur_cents(value: str) -> int | None:
    cleaned = _clean(value).replace("€", "").replace("EUR", "").replace(" ", "")
    cleaned = cleaned.replace(".", "").replace(",", ".")
    match = re.search(r"\d+(?:\.\d{1,2})?", cleaned)
    if not match:
        return None
    try:
        amount = Decimal(match.group(0)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return int(amount * 100)


def _parse_prize_tiers(rows: list[list[str]]) -> list[dict[str, object]]:
    tiers: list[dict[str, object]] = []
    for row in rows:
        if len(row) < 3:
            continue
        category = _clean(row[0])
        if "acierto" not in category.casefold() and "pleno al 15" not in category.casefold():
            continue
        winners = _parse_integer(row[1])
        prize_raw = _clean(row[2])
        prize_status = (
            "bote"
            if "bote" in prize_raw.casefold() or "acumulado" in prize_raw.casefold()
            else "published_unit_amount"
        )
        prize_cents = _parse_eur_cents(prize_raw)
        if prize_status != "bote" and (winners is None or prize_cents is None):
            continue
        tiers.append(
            {
                "category": category,
                "winners": winners,
                "unit_prize_cents": prize_cents,
                "unit_prize_currency": "EUR" if prize_cents is not None else None,
                "prize_status": prize_status,
                "unit_prize_raw": prize_raw,
            }
        )
    return tiers


def parse_selae_draw(
    html: str,
    draw_date: date,
    *,
    source_url: str | None = None,
    source_retrieved_at_utc: str | None = None,
    raw_content: bytes | None = None,
    fixture_overrides: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Parse one completed SELAE escrutinio page and fail closed on structural drift."""
    parser = CouponPageParser()
    parser.feed(html)
    parser.close()
    text = " ".join(parser.text_parts)
    date_phrase = f"{draw_date.day:02d} de {MONTHS[draw_date.month - 1]} de {draw_date.year}"
    if "la quiniela" not in text.casefold() or date_phrase.casefold() not in text.casefold():
        raise ValueError(f"La página no confirma La Quiniela y la fecha esperada {date_phrase!r}")

    home, away, scores, signs, sign_end_index = _find_fixture_groups(parser.list_items)
    overrides_by_position = {
        int(override["position"]): override
        for override in (fixture_overrides or [])
        if override.get("draw_date") == draw_date.isoformat()
    }
    fixtures: list[dict[str, object]] = []
    for position, (home_raw, away_raw, score_raw, sign) in enumerate(
        zip(home, away, scores, signs, strict=True), start=1
    ):
        home_goals, away_goals = _parse_score(score_raw)
        expected_sign = "1" if home_goals > away_goals else "2" if home_goals < away_goals else "X"
        override = overrides_by_position.get(position)
        if override is not None and (
            override.get("reported_score_raw") != _clean(score_raw)
            or override.get("sign") != sign
        ):
            raise ValueError(
                f"Partido {position}: marcador o signo no coincide con el manifiesto oficial"
            )
        if sign != expected_sign and override is None:
            raise ValueError(
                f"Partido {position}: el signo {sign} no coincide con el marcador {score_raw} "
                f"(esperado {expected_sign})"
            )
        fixtures.append(
            {
                "position": position,
                "home": _team_fields(home_raw),
                "away": _team_fields(away_raw),
                "score_raw": _clean(score_raw),
                "reported_score_raw": _clean(score_raw),
                "score_status": "played",
                "sign_determination": "score",
                "sign_evidence_url": None,
                "sign_evidence_checked_at_utc": None,
                "home_goals": home_goals,
                "away_goals": away_goals,
                "sign": sign,
                "kickoff_date": None,
                "kickoff_time": None,
                "kickoff_metadata_status": "not_published_in_escrutinio_payload",
            }
        )

    pleno = _parse_pleno(parser.list_items, sign_end_index)
    prize_tiers = _parse_prize_tiers(parser.table_rows)
    if len(prize_tiers) < 5:
        raise ValueError(f"Desglose de premios incompleto: se esperaban al menos 5 categorías, hay {len(prize_tiers)}")

    now = datetime.now(UTC).isoformat()
    resolved_source_url = source_url or make_draw_url(draw_date)
    if not _is_official_selae_url(resolved_source_url):
        raise ValueError("La URL de origen debe ser HTTPS y pertenecer al dominio oficial SELAE")
    retrieved_at = _validated_utc_timestamp(source_retrieved_at_utc or now)
    if retrieved_at is None:
        raise ValueError("source_retrieved_at_utc debe ser una fecha ISO-8601 con zona UTC")
    raw_bytes = raw_content if raw_content is not None else html.encode("utf-8")
    return {
        "schema_version": 2,
        "provider": "SELAE",
        "record_type": "completed_quiniela_draw",
        "draw_date": draw_date.isoformat(),
        "draw_id": None,
        "source_url": resolved_source_url,
        "source_retrieved_at_utc": retrieved_at,
        "imported_at_utc": now,
        "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "fixture_count": len(fixtures),
        "fixtures": fixtures,
        "pleno_al_15": pleno,
        "prize_tiers": prize_tiers,
        "limitations": [
            "La página de escrutinio no acredita la fecha ni la hora de inicio individual de cada partido.",
            "Los partidos no disputados cuyo signo se determina por sorteo público se marcan como not_played; su signo solo sirve para puntuar el cupón, nunca como resultado futbolístico de entrenamiento.",
            "El marcador y el signo son resultados observados; no son variables predictoras prepartido.",
            "Los premios unitarios y acertantes no bastan para reconstruir por sí solos el valor esperado del boleto.",
        ],
    }



def load_fixture_overrides(
    path: str | Path = DEFAULT_FIXTURE_OVERRIDES,
) -> list[dict[str, object]]:
    """Load curated, source-evidenced exceptions for non-played coupon fixtures."""
    override_path = Path(path)
    try:
        document = json.loads(override_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"No se puede leer el manifiesto de excepciones {override_path}: {exc}") from exc

    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("Manifiesto de excepciones SELAE: schema_version no compatible")
    if document.get("provider") != "SELAE":
        raise ValueError("Manifiesto de excepciones SELAE: provider debe ser SELAE")
    entries = document.get("overrides")
    if not isinstance(entries, list):
        raise TypeError("Manifiesto de excepciones SELAE: overrides debe ser una lista")

    required_fields = {
        "draw_date",
        "position",
        "status",
        "determination",
        "sign",
        "reported_score_raw",
        "evidence_url",
        "evidence_checked_at_utc",
        "reason",
    }
    seen: set[tuple[str, int]] = set()
    validated: list[dict[str, object]] = []
    for index, raw in enumerate(entries):
        location = f"overrides[{index}]"
        if not isinstance(raw, dict) or set(raw) != required_fields:
            raise ValueError(
                f"{location}: campos requeridos exactos: {sorted(required_fields)}"
            )
        try:
            draw_date = date.fromisoformat(str(raw["draw_date"])).isoformat()
        except ValueError as exc:
            raise ValueError(f"{location}.draw_date no es una fecha ISO válida") from exc

        position = raw["position"]
        if isinstance(position, bool) or not isinstance(position, int) or not 1 <= position <= 14:
            raise ValueError(f"{location}.position debe ser un entero entre 1 y 14")
        if raw["status"] != "not_played" or raw["determination"] != "public_draw":
            raise ValueError(f"{location}: solo se admiten partidos no disputados con signo por sorteo público")
        sign = str(raw["sign"]).upper()
        if sign not in {"1", "X", "2"}:
            raise ValueError(f"{location}.sign debe ser 1, X o 2")

        reported_score_raw = _clean(str(raw["reported_score_raw"]))
        if not _is_score(reported_score_raw):
            raise ValueError(f"{location}.reported_score_raw debe conservar el marcador mostrado por SELAE")

        evidence_url = str(raw["evidence_url"]).strip()
        if not _is_official_selae_url(evidence_url):
            raise ValueError(f"{location}.evidence_url debe ser HTTPS y pertenecer al dominio oficial SELAE")

        checked_raw = str(raw["evidence_checked_at_utc"]).strip()
        try:
            checked_at = datetime.fromisoformat(checked_raw)
        except ValueError as exc:
            raise ValueError(f"{location}.evidence_checked_at_utc no es ISO-8601") from exc
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError(f"{location}.evidence_checked_at_utc debe incluir zona horaria")

        reason = str(raw["reason"]).strip()
        if not reason:
            raise ValueError(f"{location}.reason no puede estar vacío")

        key = (draw_date, position)
        if key in seen:
            raise ValueError(f"Manifiesto de excepciones: override duplicado para {key}")
        seen.add(key)
        validated.append(
            {
                "draw_date": draw_date,
                "position": position,
                "status": "not_played",
                "determination": "public_draw",
                "sign": sign,
                "reported_score_raw": reported_score_raw,
                "evidence_url": evidence_url,
                "evidence_checked_at_utc": checked_at.isoformat(),
                "reason": reason,
            }
        )
    return validated


def apply_fixture_overrides(
    draws: list[dict[str, object]],
    overrides: list[dict[str, object]],
) -> int:
    """Separate a coupon sign decided by public draw from a played football score."""
    draws_by_date = {str(draw.get("draw_date")): draw for draw in draws}
    applied = 0
    for override in overrides:
        draw = draws_by_date.get(str(override["draw_date"]))
        if draw is None:
            continue
        fixtures = draw.get("fixtures")
        position = int(override["position"])
        if not isinstance(fixtures, list) or len(fixtures) != 14:
            raise ValueError(f"Sorteo {override['draw_date']}: no contiene 14 partidos")
        fixture = fixtures[position - 1]
        if not isinstance(fixture, dict):
            raise TypeError(f"Sorteo {override['draw_date']}, partido {position}: registro inválido")
        if fixture.get("reported_score_raw", fixture.get("score_raw")) != override["reported_score_raw"]:
            raise ValueError(
                f"Sorteo {override['draw_date']}, partido {position}: "
                "el marcador mostrado no coincide con el manifiesto de evidencia"
            )
        if fixture.get("sign") != override["sign"]:
            raise ValueError(
                f"Sorteo {override['draw_date']}, partido {position}: "
                "el signo publicado no coincide con el manifiesto de evidencia"
            )
        if fixture.get("score_status", "played") != "played":
            raise ValueError(
                f"Sorteo {override['draw_date']}, partido {position}: "
                "no se puede aplicar el override dos veces"
            )

        fixture["reported_score_raw"] = str(override["reported_score_raw"])
        fixture["score_raw"] = None
        fixture["home_goals"] = None
        fixture["away_goals"] = None
        fixture["score_status"] = "not_played"
        fixture["sign_determination"] = "public_draw"
        fixture["sign_evidence_url"] = str(override["evidence_url"])
        fixture["sign_evidence_checked_at_utc"] = str(override["evidence_checked_at_utc"])
        fixture["status_reason"] = str(override["reason"])
        applied += 1
    return applied


def make_session() -> requests.Session:
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
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
            "Referer": f"{BASE_URL}/es/la-quiniela/resultados",
        }
    )
    return session


def _atomic_write(path: Path, content: bytes) -> None:
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


def fetch_draw(
    draw_date: date,
    *,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    cache_ttl_hours: float = CACHE_TTL_HOURS,
    refresh: bool = False,
    session: requests.Session | None = None,
    fixture_overrides: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if cache_ttl_hours < 0:
        raise ValueError("cache_ttl_hours no puede ser negativo")
    url = make_draw_url(draw_date)
    cache_path = Path(cache_dir) / f"{draw_date.isoformat()}.html"
    metadata_path = cache_path.with_suffix(".meta.json")
    cached_draw: dict[str, object] | None = None

    if cache_path.is_file():
        try:
            cached_bytes = cache_path.read_bytes()
            if not metadata_path.is_file():
                raise ValueError("Falta el sidecar de procedencia de la caché SELAE")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict):
                raise ValueError("El sidecar de caché SELAE no es un objeto JSON")
            cache_source_url = metadata.get("source_url")
            if not _is_official_selae_url(cache_source_url):
                raise ValueError("La caché SELAE no tiene una URL oficial HTTPS")
            cache_retrieved_at = _validated_utc_timestamp(metadata.get("source_retrieved_at_utc"))
            if cache_retrieved_at is None:
                raise ValueError("La caché SELAE no tiene una hora UTC de recuperación válida")
            actual_sha256 = hashlib.sha256(cached_bytes).hexdigest()
            if metadata.get("raw_sha256") != actual_sha256:
                raise ValueError("El SHA-256 de la caché SELAE no coincide con sus bytes")
            encoding_value = metadata.get("encoding")
            if not isinstance(encoding_value, str) or not encoding_value.strip():
                raise ValueError("La caché SELAE no declara una codificación válida")
            cached_html = cached_bytes.decode(encoding_value, errors="strict")
            cached_draw = parse_selae_draw(
                cached_html,
                draw_date,
                source_url=cache_source_url,
                source_retrieved_at_utc=cache_retrieved_at,
                raw_content=cached_bytes,
                fixture_overrides=fixture_overrides,
            )
            age_hours = max(0.0, time.time() - cache_path.stat().st_mtime) / 3600
            if not refresh and age_hours <= cache_ttl_hours:
                return cached_draw
        except (OSError, ValueError, TypeError, json.JSONDecodeError, LookupError, UnicodeError) as exc:
            log.warning("Caché SELAE inválida %s: %s", cache_path, exc)
            cached_draw = None

    client = session or make_session()
    try:
        response = client.get(url, timeout=(5, 30))
        response.raise_for_status()
        encoding = getattr(response, "encoding", None) or "utf-8"
        raw_content = response.content
        html = raw_content.decode(encoding, errors="replace")
        fetched_at = datetime.now(UTC).isoformat()
        response_url = str(getattr(response, "url", None) or url)
        if not _is_official_selae_url(response_url):
            raise ValueError(f"Redirección a una URL no HTTPS del dominio oficial SELAE: {response_url}")
        parsed = parse_selae_draw(
            html,
            draw_date,
            source_url=response_url,
            source_retrieved_at_utc=fetched_at,
            raw_content=raw_content,
            fixture_overrides=fixture_overrides,
        )
        _atomic_write(cache_path, raw_content)
        metadata = {
            "source_url": response_url,
            "source_retrieved_at_utc": fetched_at,
            "raw_sha256": parsed["raw_sha256"],
            "encoding": encoding,
        }
        _atomic_write(
            metadata_path,
            (json.dumps(metadata, ensure_ascii=False) + "\n").encode("utf-8"),
        )
        return parsed
    except (requests.RequestException, ValueError, UnicodeError, LookupError) as exc:
        if cached_draw is not None:
            log.warning("SELAE no disponible; se conserva caché validada (%s): %s", url, exc)
            return cached_draw
        raise RuntimeError(f"No se pudo obtener un escrutinio SELAE válido para {draw_date}: {exc}") from exc


def load_local_draw(
    draw_date: date,
    html_dir: str | Path,
    *,
    fixture_overrides: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Parse a page saved locally from the official SELAE site (useful when a runner is geo-blocked)."""
    html_path = Path(html_dir) / f"{draw_date.isoformat()}.html"
    if not html_path.is_file():
        raise FileNotFoundError(f"No existe el HTML local esperado: {html_path}")
    raw_content = html_path.read_bytes()
    metadata_path = html_path.with_suffix(".meta.json")
    if not metadata_path.is_file():
        raise ValueError(
            f"Falta el sidecar {metadata_path.name}; no se infieren URL ni hora de captura desde el nombre o mtime"
        )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError("El sidecar del HTML local no es un objeto JSON")
    source_url = metadata.get("source_url")
    if not _is_official_selae_url(source_url) or source_url != make_draw_url(draw_date):
        raise ValueError("El HTML local no declara la URL HTTPS exacta del escrutinio oficial SELAE")
    retrieved_at = _validated_utc_timestamp(metadata.get("source_retrieved_at_utc"))
    if retrieved_at is None:
        raise ValueError("El HTML local no declara una hora de captura ISO-8601 en UTC")
    expected_sha256 = hashlib.sha256(raw_content).hexdigest()
    if metadata.get("raw_sha256") != expected_sha256:
        raise ValueError("El SHA-256 del HTML local no coincide con el sidecar de procedencia")
    encoding_value = metadata.get("encoding")
    if not isinstance(encoding_value, str) or not encoding_value.strip():
        raise ValueError("El sidecar del HTML local no declara una codificación válida")
    html = raw_content.decode(encoding_value, errors="strict")
    return parse_selae_draw(
        html,
        draw_date,
        source_url=source_url,
        source_retrieved_at_utc=retrieved_at,
        raw_content=raw_content,
        fixture_overrides=fixture_overrides,
    )

def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Fecha inválida {value!r}; use YYYY-MM-DD") from exc


def load_dates(values: Iterable[str], date_file: str | Path | None = None) -> list[date]:
    raw_values = list(values)
    if date_file is not None:
        for line in Path(date_file).read_text(encoding="utf-8").splitlines():
            value = line.split("#", 1)[0].strip()
            if value:
                raw_values.append(value)
    if not raw_values:
        raise ValueError("Debe indicar --dates o --date-file; no se exploran fechas a ciegas")
    parsed = [parse_iso_date(value) for value in raw_values]
    if len(parsed) != len(set(parsed)):
        raise ValueError("La lista contiene fechas de sorteo duplicadas")
    return sorted(parsed)


def _validate_draw_record(draw: dict[str, object]) -> bool:
    if draw.get("schema_version") not in {1, 2}:
        return False
    if draw.get("provider") != "SELAE" or draw.get("record_type") != "completed_quiniela_draw":
        return False
    try:
        date.fromisoformat(str(draw["draw_date"]))
    except (KeyError, ValueError):
        return False
    if not _is_official_selae_url(draw.get("source_url")):
        return False
    if _validated_utc_timestamp(draw.get("source_retrieved_at_utc")) is None:
        return False
    if re.fullmatch(r"[0-9a-f]{64}", str(draw.get("raw_sha256", "")).lower()) is None:
        return False
    fixtures = draw.get("fixtures")
    if not isinstance(fixtures, list) or len(fixtures) != 14 or draw.get("fixture_count") != 14:
        return False
    for expected_position, fixture in enumerate(fixtures, start=1):
        if not isinstance(fixture, dict) or fixture.get("position") != expected_position:
            return False
        home = fixture.get("home")
        away = fixture.get("away")
        if not isinstance(home, dict) or not home.get("name"):
            return False
        if not isinstance(away, dict) or not away.get("name"):
            return False
        sign = fixture.get("sign")
        if not isinstance(sign, str) or sign not in {"1", "X", "2"}:
            return False
        score_status = fixture.get("score_status", "played")
        determination = fixture.get("sign_determination", "score")
        home_goals = fixture.get("home_goals")
        away_goals = fixture.get("away_goals")
        if score_status == "played":
            if (
                isinstance(home_goals, bool)
                or isinstance(away_goals, bool)
                or not isinstance(home_goals, int)
                or not isinstance(away_goals, int)
                or home_goals < 0
                or away_goals < 0
                or determination != "score"
            ):
                return False
            expected_sign = "1" if home_goals > away_goals else "2" if home_goals < away_goals else "X"
            if sign != expected_sign:
                return False
            score_raw = fixture.get("score_raw")
            if not isinstance(score_raw, str) or not _is_score(score_raw):
                return False
            parsed_home, parsed_away = _parse_score(score_raw)
            if (parsed_home, parsed_away) != (home_goals, away_goals):
                return False
            if draw.get("schema_version") == 2 and fixture.get("reported_score_raw") != score_raw:
                return False
        elif score_status == "not_played":
            if (
                home_goals is not None
                or away_goals is not None
                or fixture.get("score_raw") is not None
                or determination != "public_draw"
                or not _is_score(str(fixture.get("reported_score_raw", "")))
                or not isinstance(fixture.get("status_reason"), str)
                or not fixture.get("status_reason", "").strip()
            ):
                return False
            if not _is_official_selae_url(fixture.get("sign_evidence_url")):
                return False
            checked_raw = str(fixture.get("sign_evidence_checked_at_utc", ""))
            try:
                checked_at = datetime.fromisoformat(checked_raw)
            except ValueError:
                return False
            if checked_at.tzinfo is None or checked_at.utcoffset() is None:
                return False
        else:
            return False
    return True


def write_draws(
    draws: list[dict[str, object]],
    output: str | Path,
    *,
    replace_existing: bool = False,
) -> None:
    if not draws:
        raise ValueError("No se puede escribir un histórico de sorteos vacío")
    incoming_dates = [str(draw["draw_date"]) for draw in draws]
    if len(incoming_dates) != len(set(incoming_dates)):
        raise ValueError("La importación contiene fechas de sorteo duplicadas")

    target = Path(output)
    merged: dict[str, dict[str, object]] = {}
    if target.is_file():
        for line_number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                existing = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL existente corrupto en línea {line_number}: {exc}") from exc
            if not isinstance(existing, dict) or not existing.get("draw_date"):
                raise ValueError(f"Registro JSONL inválido en línea {line_number}")
            draw_date = str(existing["draw_date"])
            if draw_date in merged:
                raise ValueError(f"El histórico existente contiene la fecha duplicada {draw_date}")
            merged[draw_date] = existing

    unchanged_count = 0
    replaced_count = 0
    for draw in draws:
        draw_date = str(draw["draw_date"])
        existing = merged.get(draw_date)
        if existing is not None:
            if existing.get("raw_sha256") == draw.get("raw_sha256"):
                unchanged_count += 1
                continue
            if not replace_existing:
                raise ValueError(
                    f"El sorteo {draw_date} ya existe con otro SHA-256; "
                    "use --replace-existing solo tras revisar la corrección de origen"
                )
            replaced_count += 1
        merged[draw_date] = draw

    ordered_draws = [merged[key] for key in sorted(merged)]
    if not ordered_draws:
        raise ValueError("El histórico final quedaría vacío")

    integrity_passed = all(_validate_draw_record(draw) for draw in ordered_draws)
    if not integrity_passed:
        raise ValueError("El perfil de integridad del histórico SELAE no ha superado las comprobaciones")

    lines = [
        json.dumps(draw, ensure_ascii=False, sort_keys=True)
        for draw in ordered_draws
    ]
    _atomic_write(target, ("\n".join(lines) + "\n").encode("utf-8"))
    all_fixtures = [
        fixture
        for draw in ordered_draws
        for fixture in draw.get("fixtures", [])
        if isinstance(fixture, dict)
    ]
    not_played_count = sum(
        fixture.get("score_status", "played") == "not_played"
        for fixture in all_fixtures
    )
    profile = {
        "profile_generated_at_utc": datetime.now(UTC).isoformat(),
        "provider": "SELAE",
        "source_urls": sorted({str(draw["source_url"]) for draw in ordered_draws}),
        "draw_count": len(ordered_draws),
        "fixture_count": sum(int(draw["fixture_count"]) for draw in ordered_draws),
        "played_fixture_count": len(all_fixtures) - not_played_count,
        "not_played_fixture_count": not_played_count,
        "public_draw_fixture_count": sum(
            fixture.get("sign_determination") == "public_draw"
            for fixture in all_fixtures
        ),
        "football_result_usable_fixture_count": len(all_fixtures) - not_played_count,
        "draw_dates": [str(draw["draw_date"]) for draw in ordered_draws],
        "raw_sha256_by_draw_date": {
            str(draw["draw_date"]): draw["raw_sha256"] for draw in ordered_draws
        },
        "integrity_passed": integrity_passed,
        "unchanged_draws_in_this_import": unchanged_count,
        "replaced_draws_in_this_import": replaced_count,
        "match_kickoff_dates_available": False,
        "expected_payout_validated": False,
    }
    _atomic_write(
        target.with_name(f"{target.stem}.profile.json"),
        (json.dumps(profile, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Importa escrutinios de La Quiniela desde fechas explícitas; no explora días a ciegas."
    )
    parser.add_argument("--dates", nargs="*", default=[], help="Fechas de sorteo ISO (YYYY-MM-DD).")
    parser.add_argument("--date-file", type=Path, help="Archivo UTF-8 con una fecha ISO por línea.")
    parser.add_argument("--html-dir", type=Path, help="Usa HTML oficial guardado localmente como YYYY-MM-DD.html; no realiza peticiones.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--cache-ttl-hours", type=float, default=CACHE_TTL_HOURS)
    parser.add_argument("--refresh", action="store_true", help="Renovar incluso una caché válida.")
    parser.add_argument("--replace-existing", action="store_true", help="Reemplazar un sorteo existente solo si su SHA-256 de origen ha cambiado.")
    parser.add_argument(
        "--fixture-overrides",
        type=Path,
        default=DEFAULT_FIXTURE_OVERRIDES,
        help="Manifiesto oficial de partidos aplazados o con signo decidido por sorteo público.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args()
    dates = load_dates(args.dates, args.date_file)
    overrides = load_fixture_overrides(args.fixture_overrides)
    if args.html_dir is not None:
        draws = [
            load_local_draw(draw_date, args.html_dir, fixture_overrides=overrides)
            for draw_date in dates
        ]
    else:
        draws = [
            fetch_draw(
                draw_date,
                cache_dir=args.cache_dir,
                cache_ttl_hours=args.cache_ttl_hours,
                refresh=args.refresh,
                fixture_overrides=overrides,
            )
            for draw_date in dates
        ]
    applied_overrides = apply_fixture_overrides(draws, overrides)
    if applied_overrides:
        log.info("Aplicadas %s excepciones oficiales de partidos no disputados", applied_overrides)
    write_draws(draws, args.output, replace_existing=args.replace_existing)
    profile_path = args.output.with_name(f"{args.output.stem}.profile.json")
    print(f"SELAE_IMPORT_OK: {sum(int(draw['fixture_count']) for draw in draws)} imported fixtures")
    print(f"Official non-played overrides applied: {applied_overrides}")
    print(f"Dataset: {args.output}")
    print(f"Profile: {profile_path}")


if __name__ == "__main__":
    main()
