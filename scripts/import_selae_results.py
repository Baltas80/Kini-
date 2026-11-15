from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import tempfile
import time
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

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
CACHE_TTL_HOURS = 24.0
TEAM_CATEGORY_RE = re.compile(r"^(.*?)\\s+\\(([MF])\\)$", re.IGNORECASE)
SCORE_RE = re.compile(r"^(\\d+)\\s*[-–]\\s*(\\d+)$")
PLENO_SCORE_RE = re.compile(r"^(M|\\d+)\\s*[-–]\\s*(M|\\d+)$", re.IGNORECASE)
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


def _clean(value: str) -> str:
    return " ".join(value.replace("\\xa0", " ").split()).strip()


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


def _find_fixture_groups(items: list[str]) -> tuple[list[str], list[str], list[str], list[str]]:
    positions = [i for i in range(max(0, len(items) - 13)) if _is_position_block(items, i)]
    if len(positions) != 1:
        raise ValueError(f"Se esperaba un único bloque de posiciones 1..14; encontrados {len(positions)}")
    tail_start = positions[0] + 14
    candidates: list[tuple[list[str], list[str], list[str], list[str]]] = []
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
            candidates.append((home, away, scores, [value.upper() for value in signs]))
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
    match = re.search(r"\\d+(?:\\.\\d{1,2})?", cleaned)
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
        prize_cents = _parse_eur_cents(row[2])
        if winners is None or prize_cents is None:
            continue
        tiers.append(
            {
                "category": category,
                "winners": winners,
                "unit_prize_cents": prize_cents,
                "unit_prize_currency": "EUR",
            }
        )
    return tiers


def parse_selae_draw(
    html: str,
    draw_date: date,
    *,
    source_url: str | None = None,
    source_retrieved_at_utc: str | None = None,
) -> dict[str, object]:
    """Parse one completed SELAE escrutinio page and fail closed on structural drift."""
    parser = CouponPageParser()
    parser.feed(html)
    parser.close()
    text = " ".join(parser.text_parts)
    date_phrase = f"{draw_date.day:02d} de {MONTHS[draw_date.month - 1]} de {draw_date.year}"
    if "la quiniela" not in text.casefold() or date_phrase.casefold() not in text.casefold():
        raise ValueError(f"La página no confirma La Quiniela y la fecha esperada {date_phrase!r}")

    home, away, scores, signs = _find_fixture_groups(parser.list_items)
    fixtures: list[dict[str, object]] = []
    for position, (home_raw, away_raw, score_raw, sign) in enumerate(
        zip(home, away, scores, signs, strict=True), start=1
    ):
        home_goals, away_goals = _parse_score(score_raw)
        expected_sign = "1" if home_goals > away_goals else "2" if home_goals < away_goals else "X"
        if sign != expected_sign:
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
                "home_goals": home_goals,
                "away_goals": away_goals,
                "sign": sign,
                "kickoff_date": None,
                "kickoff_time": None,
                "kickoff_metadata_status": "not_published_in_escrutinio_payload",
            }
        )

    pleno = _parse_pleno(parser.list_items, parser.list_items.index(signs[-1]) + 1 if signs[-1] in parser.list_items else 0)
    prize_tiers = _parse_prize_tiers(parser.table_rows)
    if len(prize_tiers) < 5:
        raise ValueError(f"Desglose de premios incompleto: se esperaban al menos 5 categorías, hay {len(prize_tiers)}")

    now = datetime.now(timezone.utc).isoformat()
    raw_bytes = html.encode("utf-8")
    return {
        "schema_version": 1,
        "provider": "SELAE",
        "record_type": "completed_quiniela_draw",
        "draw_date": draw_date.isoformat(),
        "draw_id": None,
        "source_url": source_url or make_draw_url(draw_date),
        "source_retrieved_at_utc": source_retrieved_at_utc or now,
        "imported_at_utc": now,
        "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "fixture_count": len(fixtures),
        "fixtures": fixtures,
        "pleno_al_15": pleno,
        "prize_tiers": prize_tiers,
        "limitations": [
            "La página de escrutinio no acredita la fecha ni la hora de inicio individual de cada partido.",
            "El marcador y el signo son resultados observados; no son variables predictoras prepartido.",
            "Los premios unitarios y acertantes no bastan para reconstruir por sí solos el valor esperado del boleto.",
        ],
    }


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
            "User-Agent": "Kini-QuinielaResearch/1.0 (+https://github.com/Baltas80/Kini-)",
            "Accept": "text/html,application/xhtml+xml",
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
) -> dict[str, object]:
    if cache_ttl_hours < 0:
        raise ValueError("cache_ttl_hours no puede ser negativo")
    url = make_draw_url(draw_date)
    cache_path = Path(cache_dir) / f"{draw_date.isoformat()}.html"
    metadata_path = cache_path.with_suffix(".meta.json")
    cached_html: str | None = None
    cached_draw: dict[str, object] | None = None
    cached_retrieved_at: str | None = None

    if cache_path.is_file():
        try:
            cached_html = cache_path.read_text(encoding="utf-8")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
            cached_retrieved_at = metadata.get("source_retrieved_at_utc")
            cached_draw = parse_selae_draw(
                cached_html,
                draw_date,
                source_url=url,
                source_retrieved_at_utc=cached_retrieved_at,
            )
            age_hours = max(0.0, time.time() - cache_path.stat().st_mtime) / 3600
            if not refresh and age_hours <= cache_ttl_hours:
                return cached_draw
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            log.warning("Caché SELAE inválida %s: %s", cache_path, exc)
            cached_html = None
            cached_draw = None

    client = session or make_session()
    try:
        response = client.get(url, timeout=(5, 30))
        response.raise_for_status()
        encoding = getattr(response, "encoding", None) or "utf-8"
        html = response.content.decode(encoding, errors="replace")
        fetched_at = datetime.now(timezone.utc).isoformat()
        parsed = parse_selae_draw(
            html,
            draw_date,
            source_url=getattr(response, "url", None) or url,
            source_retrieved_at_utc=fetched_at,
        )
        _atomic_write(cache_path, html.encode("utf-8"))
        _atomic_write(
            metadata_path,
            (json.dumps({"source_url": url, "source_retrieved_at_utc": fetched_at, "raw_sha256": parsed["raw_sha256"]}, ensure_ascii=False) + "\\n").encode("utf-8"),
        )
        return parsed
    except (requests.RequestException, ValueError, UnicodeError) as exc:
        if cached_draw is not None:
            log.warning("SELAE no disponible; se conserva caché validada (%s): %s", url, exc)
            return cached_draw
        raise RuntimeError(f"No se pudo obtener un escrutinio SELAE válido para {draw_date}: {exc}") from exc


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


def write_draws(draws: list[dict[str, object]], output: str | Path) -> None:
    if not draws:
        raise ValueError("No se puede escribir un histórico de sorteos vacío")
    dates = [str(draw["draw_date"]) for draw in draws]
    if len(dates) != len(set(dates)):
        raise ValueError("Hay fechas de sorteo duplicadas")
    lines = [json.dumps(draw, ensure_ascii=False, sort_keys=True) for draw in sorted(draws, key=lambda item: str(item["draw_date"]))]
    target = Path(output)
    _atomic_write(target, ("\\n".join(lines) + "\\n").encode("utf-8"))
    profile = {
        "profile_generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": "SELAE",
        "source_urls": sorted({str(draw["source_url"]) for draw in draws}),
        "draw_count": len(draws),
        "fixture_count": sum(int(draw["fixture_count"]) for draw in draws),
        "draw_dates": sorted(dates),
        "raw_sha256_by_draw_date": {str(draw["draw_date"]): draw["raw_sha256"] for draw in draws},
        "integrity_passed": all(
            int(draw["fixture_count"]) == 14
            and len(draw["fixtures"]) == 14
            and all(fixture["sign"] in {"1", "X", "2"} for fixture in draw["fixtures"])
            for draw in draws
        ),
        "match_kickoff_dates_available": False,
        "expected_payout_validated": False,
    }
    _atomic_write(
        target.with_name(f"{target.stem}.profile.json"),
        (json.dumps(profile, indent=2, ensure_ascii=False) + "\\n").encode("utf-8"),
    )
    if not profile["integrity_passed"]:
        raise ValueError("El perfil de integridad del histórico SELAE no ha superado las comprobaciones")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Importa escrutinios oficiales de La Quiniela desde fechas explícitas; no explora días a ciegas."
    )
    parser.add_argument("--dates", nargs="*", default=[], help="Fechas de sorteo ISO (YYYY-MM-DD).")
    parser.add_argument("--date-file", type=Path, help="Archivo UTF-8 con una fecha ISO por línea.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--cache-ttl-hours", type=float, default=CACHE_TTL_HOURS)
    parser.add_argument("--refresh", action="store_true", help="Renovar incluso una caché válida.")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args()
    dates = load_dates(args.dates, args.date_file)
    draws = [
        fetch_draw(
            draw_date,
            cache_dir=args.cache_dir,
            cache_ttl_hours=args.cache_ttl_hours,
            refresh=args.refresh,
        )
        for draw_date in dates
    ]
    write_draws(draws, args.output)
    profile_path = args.output.with_name(f"{args.output.stem}.profile.json")
    print(f"SELAE_IMPORT_OK: {sum(int(draw['fixture_count']) for draw in draws)} fixtures in {len(draws)} draws")
    print(f"Dataset: {args.output}")
    print(f"Profile: {profile_path}")


if __name__ == "__main__":
    main()
