from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import requests

from scripts.import_selae_results import (
    fetch_draw,
    load_dates,
    make_draw_url,
    parse_selae_draw,
    write_draws,
)


DRAW_DATE = date(2026, 11, 8)
HOMES = [
    "Málaga (M)", "Osasuna (M)", "Valencia (M)", "Elche (M)",
    "Real Sociedad (M)", "Celta (M)", "Villarreal (M)", "Cádiz (M)",
    "Girona (M)", "Sporting (M)", "Athletic Club (F)", "Logroño (F)",
    "Eibar (F)", "Tenerife (F)",
]
AWAYS = [
    "Racing de Santander (M)", "Athletic Club (M)", "Real Madrid (M)", "Betis (M)",
    "Rayo Vallecano (M)", "Levante (M)", "Getafe (M)", "R. Oviedo (M)",
    "Almería (M)", "R. Valladolid (M)", "Real Madrid (F)", "Sevilla (F)",
    "Real Sociedad (F)", "Alavés (F)",
]
SCORES = ["1-2", "1-1", "0-3", "0-2", "1-0", "0-0", "2-0", "1-2", "0-1", "1-2", "1-1", "2-2", "1-2", "1-0"]
SIGNS = ["2", "X", "2", "2", "1", "X", "1", "2", "2", "2", "X", "X", "2", "1"]


def make_html(*, signs: list[str] | None = None, scores: list[str] | None = None) -> str:
    signs = signs or SIGNS
    scores = scores or SCORES
    items = [str(i) for i in range(1, 15)] + HOMES + AWAYS + scores + signs
    items += ["15", "At. Madrid (M)", "Barcelona (M)", "1-2", "1 - 2"]
    list_html = "".join(f"<li><span>{item}</span></li>" for item in items)
    prizes = [
        ("Pleno al 15", "1", "1.647.986,55 €"),
        ("1ª (14 Aciertos)", "6", "90.099,00 €"),
        ("2ª (13 Aciertos)", "185", "1.369,75 €"),
        ("3ª (12 Aciertos)", "2.301", "110,13 €"),
        ("4ª (11 Aciertos)", "17.496", "14,48 €"),
        ("5ª (10 Aciertos)", "89.116", "3,41 €"),
    ]
    rows = "".join(
        f"<tr><td>{category}</td><td>{winners}</td><td>{prize}</td></tr>"
        for category, winners, prize in prizes
    )
    return (
        "<html><body>"
        "<h1>La Quiniela: premios y ganadores del 08 de noviembre de 2026</h1>"
        "<p>Los resultados correspondientes a la jornada de La Quiniela, "
        "del 08 de noviembre de 2026, son los siguientes:</p>"
        f"<ul>{list_html}</ul>"
        f"<table>{rows}</table>"
        "</body></html>"
    )


class FakeResponse:
    def __init__(self, content: bytes, url: str) -> None:
        self.content = content
        self.url = url
        self.encoding = "utf-8"

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls = 0

    def get(self, url: str, timeout: tuple[int, int]) -> FakeResponse:
        self.calls += 1
        return FakeResponse(self.content, url)


def test_make_draw_url_uses_spanish_date_slug() -> None:
    assert make_draw_url(DRAW_DATE).endswith(
        "/la-quiniela-premios-y-ganadores-del-08-de-noviembre-de-2026"
    )


def test_parse_selae_draw_extracts_14_fixtures_pleno_and_prizes() -> None:
    draw = parse_selae_draw(make_html(), DRAW_DATE)

    assert draw["provider"] == "SELAE"
    assert draw["draw_date"] == "2026-11-08"
    assert draw["fixture_count"] == 14
    assert draw["fixtures"][0]["home"]["name"] == "Málaga"
    assert draw["fixtures"][0]["home"]["category_marker"] == "M"
    assert draw["fixtures"][10]["home"]["category_marker"] == "F"
    assert draw["fixtures"][0]["sign"] == "2"
    assert draw["fixtures"][5]["sign"] == "X"
    assert draw["fixtures"][0]["kickoff_date"] is None
    assert draw["pleno_al_15"]["home"]["name"] == "At. Madrid"
    assert draw["pleno_al_15"]["home_goals"] == 1
    assert draw["pleno_al_15"]["away_goals"] == 2
    assert len(draw["prize_tiers"]) == 6
    assert draw["prize_tiers"][0]["unit_prize_cents"] == 164798655


def test_parse_selae_draw_rejects_wrong_date() -> None:
    with pytest.raises(ValueError, match="fecha esperada"):
        parse_selae_draw(make_html(), date(2026, 11, 9))


def test_parse_selae_draw_rejects_sign_score_mismatch() -> None:
    wrong_signs = SIGNS.copy()
    wrong_signs[0] = "1"
    with pytest.raises(ValueError, match="no coincide con el marcador"):
        parse_selae_draw(make_html(signs=wrong_signs), DRAW_DATE)


def test_parse_selae_draw_rejects_incomplete_coupon() -> None:
    incomplete = make_html().replace("<li><span>Tenerife (F)</span></li>", "")
    with pytest.raises(ValueError, match="bloque completo"):
        parse_selae_draw(incomplete, DRAW_DATE)


def test_load_dates_rejects_duplicates_and_requires_explicit_input(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Debe indicar"):
        load_dates([])
    with pytest.raises(ValueError, match="duplicadas"):
        load_dates(["2026-11-08", "2026-11-08"])
    date_file = tmp_path / "draws.txt"
    date_file.write_text("2026-11-08\n# historical draw\n2026-11-01\n", encoding="utf-8")
    assert load_dates([], date_file) == [date(2026, 11, 1), date(2026, 11, 8)]


def test_fetch_draw_validates_and_reuses_cache(tmp_path: Path) -> None:
    html = make_html().encode("utf-8")
    session = FakeSession(html)
    first = fetch_draw(DRAW_DATE, cache_dir=tmp_path, session=session)
    second = fetch_draw(DRAW_DATE, cache_dir=tmp_path, session=session)

    assert first["raw_sha256"] == second["raw_sha256"]
    assert first["fixture_count"] == 14
    assert session.calls == 1
    assert (tmp_path / "2026-11-08.html").is_file()
    assert (tmp_path / "2026-11-08.meta.json").is_file()


def test_write_draws_creates_jsonl_and_integrity_profile(tmp_path: Path) -> None:
    draw = parse_selae_draw(make_html(), DRAW_DATE)
    output = tmp_path / "selae.jsonl"
    write_draws([draw], output)

    lines = output.read_text(encoding="utf-8").splitlines()
    profile = json.loads((tmp_path / "selae.profile.json").read_text(encoding="utf-8"))
    assert len(lines) == 1
    assert json.loads(lines[0])["fixture_count"] == 14
    assert profile["draw_count"] == 1
    assert profile["fixture_count"] == 14
    assert profile["integrity_passed"] is True
    assert profile["match_kickoff_dates_available"] is False
