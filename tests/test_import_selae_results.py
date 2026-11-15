from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from scripts.import_selae_results import (
    apply_fixture_overrides,
    fetch_draw,
    load_dates,
    load_fixture_overrides,
    load_local_draw,
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


def make_html(*, signs: list[str] | None = None, scores: list[str] | None = None, pleno_score: str = "1-2") -> str:
    signs = signs or SIGNS
    scores = scores or SCORES
    items = [str(i) for i in range(1, 15)] + HOMES + AWAYS + scores + signs
    items += ["15", "At. Madrid (M)", "Barcelona (M)", pleno_score, pleno_score]
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
    assert draw["fixtures"][0]["score_status"] == "played"
    assert draw["fixtures"][0]["sign_determination"] == "score"
    assert draw["fixtures"][0]["reported_score_raw"] == "1-2"
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


def test_parse_selae_draw_accepts_non_numeric_pleno_marker() -> None:
    draw = parse_selae_draw(make_html(pleno_score="M - M"), DRAW_DATE)
    assert draw["pleno_al_15"]["score_raw"] == "M - M"
    assert draw["pleno_al_15"]["home_goals"] is None
    assert draw["pleno_al_15"]["away_goals"] is None
    assert draw["pleno_al_15"]["score_complete"] is False


def test_load_local_draw_uses_original_bytes_and_metadata(tmp_path: Path) -> None:
    raw = make_html().encode("utf-8")
    html_path = tmp_path / "2026-11-08.html"
    html_path.write_bytes(raw)
    html_path.with_suffix(".meta.json").write_text(
        json.dumps({
            "source_url": make_draw_url(DRAW_DATE),
            "source_retrieved_at_utc": "2026-11-09T00:00:00+00:00",
            "encoding": "utf-8",
        }),
        encoding="utf-8",
    )

    draw = load_local_draw(DRAW_DATE, tmp_path)
    assert draw["raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert draw["source_retrieved_at_utc"] == "2026-11-09T00:00:00+00:00"


def test_write_draws_is_idempotent_and_requires_explicit_replacement(tmp_path: Path) -> None:
    draw = parse_selae_draw(make_html(), DRAW_DATE)
    output = tmp_path / "selae.jsonl"
    write_draws([draw], output)
    write_draws([draw], output)

    lines = output.read_text(encoding="utf-8").splitlines()
    profile = json.loads((tmp_path / "selae.profile.json").read_text(encoding="utf-8"))
    assert len(lines) == 1
    assert profile["draw_count"] == 1
    assert profile["unchanged_draws_in_this_import"] == 1

    corrected = dict(draw)
    corrected["raw_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="otro SHA-256"):
        write_draws([corrected], output)

    write_draws([corrected], output, replace_existing=True)
    final_record = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
    final_profile = json.loads((tmp_path / "selae.profile.json").read_text(encoding="utf-8"))
    assert final_record["raw_sha256"] == "a" * 64
    assert final_profile["replaced_draws_in_this_import"] == 1


def test_write_draws_rejects_corrupt_existing_jsonl(tmp_path: Path) -> None:
    output = tmp_path / "selae.jsonl"
    output.write_text("{not-json}\\n", encoding="utf-8")
    draw = parse_selae_draw(make_html(), DRAW_DATE)
    with pytest.raises(ValueError, match="corrupto"):
        write_draws([draw], output)


def test_parse_selae_draw_preserves_bote_prize_rows() -> None:
    html = make_html().replace("1.647.986,55 €", "BOTE")
    draw = parse_selae_draw(html, DRAW_DATE)
    pleno_prize = draw["prize_tiers"][0]
    assert pleno_prize["prize_status"] == "bote"
    assert pleno_prize["unit_prize_cents"] is None
    assert len(draw["prize_tiers"]) == 6


def test_load_local_draw_rejects_non_official_source_url(tmp_path: Path) -> None:
    html_path = tmp_path / "2026-11-08.html"
    html_path.write_bytes(make_html().encode("utf-8"))
    html_path.with_suffix(".meta.json").write_text(
        json.dumps({"source_url": "https://example.com/not-selae"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="procedencia SELAE"):
        load_local_draw(DRAW_DATE, tmp_path)



def test_official_override_separates_public_draw_sign_from_football_score(tmp_path: Path) -> None:
    draw = parse_selae_draw(make_html(), DRAW_DATE)
    overrides = load_fixture_overrides()
    assert len(overrides) == 1

    applied = apply_fixture_overrides([draw], overrides)

    fixture = draw["fixtures"][13]
    assert applied == 1
    assert fixture["sign"] == "1"
    assert fixture["reported_score_raw"] == "1-0"
    assert fixture["score_raw"] is None
    assert fixture["home_goals"] is None
    assert fixture["away_goals"] is None
    assert fixture["score_status"] == "not_played"
    assert fixture["sign_determination"] == "public_draw"
    assert fixture["sign_evidence_url"].startswith("https://www.loteriasyapuestas.es/")
    assert fixture["status_reason"]


def test_official_override_fails_closed_if_page_score_changes() -> None:
    draw = parse_selae_draw(make_html(), DRAW_DATE)
    overrides = load_fixture_overrides()
    overrides[0]["reported_score_raw"] = "0-0"

    with pytest.raises(ValueError, match="marcador mostrado"):
        apply_fixture_overrides([draw], overrides)


def test_official_override_fails_closed_if_coupon_sign_changes() -> None:
    draw = parse_selae_draw(make_html(), DRAW_DATE)
    overrides = load_fixture_overrides()
    overrides[0]["sign"] = "X"

    with pytest.raises(ValueError, match="signo publicado"):
        apply_fixture_overrides([draw], overrides)


def test_override_manifest_rejects_non_official_evidence_url(tmp_path: Path) -> None:
    manifest = {
        "schema_version": 1,
        "provider": "SELAE",
        "overrides": [{
            "draw_date": "2026-11-08",
            "position": 14,
            "status": "not_played",
            "determination": "public_draw",
            "sign": "1",
            "reported_score_raw": "1-0",
            "evidence_url": "https://example.com/notice.pdf",
            "evidence_checked_at_utc": "2026-11-15T07:14:47Z",
            "reason": "test",
        }],
    }
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="dominio oficial SELAE"):
        load_fixture_overrides(path)


def test_write_draws_profile_excludes_public_draw_from_football_results(tmp_path: Path) -> None:
    draw = parse_selae_draw(make_html(), DRAW_DATE)
    apply_fixture_overrides([draw], load_fixture_overrides())
    output = tmp_path / "selae.jsonl"

    write_draws([draw], output)

    profile = json.loads((tmp_path / "selae.profile.json").read_text(encoding="utf-8"))
    assert profile["fixture_count"] == 14
    assert profile["played_fixture_count"] == 13
    assert profile["not_played_fixture_count"] == 1
    assert profile["public_draw_fixture_count"] == 1
    assert profile["football_result_usable_fixture_count"] == 13


def test_write_draws_rejects_fake_football_score_for_public_draw(tmp_path: Path) -> None:
    draw = parse_selae_draw(make_html(), DRAW_DATE)
    apply_fixture_overrides([draw], load_fixture_overrides())
    corrupted = dict(draw)
    corrupted["fixtures"] = [dict(fixture) for fixture in draw["fixtures"]]
    corrupted["fixtures"][13]["home_goals"] = 1
    output = tmp_path / "selae.jsonl"

    with pytest.raises(ValueError, match="integridad"):
        write_draws([corrupted], output)


def test_write_draws_rejects_existing_record_with_score_sign_conflict(tmp_path: Path) -> None:
    draw = parse_selae_draw(make_html(), DRAW_DATE)
    corrupted = dict(draw)
    corrupted_fixtures = [dict(fixture) for fixture in draw["fixtures"]]
    corrupted_fixtures[0]["sign"] = "1"
    corrupted["fixtures"] = corrupted_fixtures
    output = tmp_path / "selae.jsonl"
    with pytest.raises(ValueError, match="integridad"):
        write_draws([corrupted], output)
