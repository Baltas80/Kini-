from __future__ import annotations

import pytest

from scripts.import_selae_press_release import (
    parse_selae_press_release_text,
    validate_draw_date_in_text,
    validate_official_source_url,
)


def test_parse_official_2026_11_08_press_release_vector() -> None:
    text = """
    Resultados:
    2 - X - 2 - 2 - 1 - X - 1 - 2 - 2 - 2 - X - X - 2 - 1 - 12 -
    """

    outcome = parse_selae_press_release_text(text)

    assert outcome.signs == (
        "2",
        "X",
        "2",
        "2",
        "1",
        "X",
        "1",
        "2",
        "2",
        "2",
        "X",
        "X",
        "2",
        "1",
    )
    assert outcome.pleno_home == "1"
    assert outcome.pleno_away == "2"
    assert outcome.pleno_code == "12"


def test_parse_official_2023_12_17_press_release_with_m_category() -> None:
    text = """
    Resultados:
    1 - 1 - 2 - X - X - X - X - 1 - X - X - 1 - 1 - X - 1 - M0 -
    """

    outcome = parse_selae_press_release_text(text)

    assert len(outcome.signs) == 14
    assert outcome.pleno_home == "M"
    assert outcome.pleno_away == "0"
    assert outcome.pleno_code == "M0"


def test_parse_official_2026_11_01_press_release_vector() -> None:
    text = """
    Resultados:
    2 - 1 - 1 - 1 - 1 - 2 - 2 - X - 2 - X - X - 1 - 2 - 1 - 21 -
    """

    outcome = parse_selae_press_release_text(text)

    assert outcome.signs == (
        "2",
        "1",
        "1",
        "1",
        "1",
        "2",
        "2",
        "X",
        "2",
        "X",
        "X",
        "1",
        "2",
        "1",
    )
    assert outcome.pleno_code == "21"


def test_parse_accepts_pleno_categories_separated_by_hyphen() -> None:
    text = """
    Resultados:
    2 - X - 2 - 2 - 1 - X - 1 - 2 - 2 - 2 - X - X - 2 - 1 - 2-1 -
    """

    outcome = parse_selae_press_release_text(text)

    assert outcome.pleno_code == "21"


def test_parse_rejects_missing_or_incomplete_result_vector() -> None:
    with pytest.raises(ValueError, match="no complete"):
        parse_selae_press_release_text("Resultados: 1 - X - 2 - 1")


def test_parse_rejects_conflicting_vectors() -> None:
    text = """
    Resultados: 2 - X - 2 - 2 - 1 - X - 1 - 2 - 2 - 2 - X - X - 2 - 1 - 12 -
    Results: 1 - 1 - 2 - X - X - X - X - 1 - X - X - 1 - 1 - X - 1 - M0 -
    """

    with pytest.raises(ValueError, match="conflicting"):
        parse_selae_press_release_text(text)


def test_draw_date_must_be_present_in_press_release_text() -> None:
    text = "Jornada celebrada el 8 de noviembre de 2026. Resultados: ..."
    assert validate_draw_date_in_text(text, "2026-11-08") == "2026-11-08"

    with pytest.raises(ValueError, match="not explicitly present"):
        validate_draw_date_in_text(text, "2026-11-01")


def test_source_url_must_be_official_https_pdf() -> None:
    assert validate_official_source_url(
        "https://www.loteriasyapuestas.es/f/loterias/documentos/nota.pdf"
    ).startswith("https://")

    with pytest.raises(ValueError, match="official SELAE host"):
        validate_official_source_url("https://example.com/nota.pdf")

    with pytest.raises(ValueError, match="official PDF"):
        validate_official_source_url("https://www.loteriasyapuestas.es/es/la-quiniela")
