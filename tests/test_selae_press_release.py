from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.import_selae_press_release import (
    import_press_release,
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
    assert validate_official_source_url(
        "https://www.loteriasyapuestas.es:443/f/loterias/documentos/nota.pdf"
    ).startswith("https://")

    unsafe_urls = (
        "http://www.loteriasyapuestas.es/f/loterias/documentos/nota.pdf",
        "https://www.loteriasyapuestas.es:8443/f/loterias/documentos/nota.pdf",
        "https://user@www.loteriasyapuestas.es/f/loterias/documentos/nota.pdf",
        "https://user:secret@www.loteriasyapuestas.es/f/loterias/documentos/nota.pdf",
        "https://www.loteriasyapuestas.es.evil.example/f/loterias/documentos/nota.pdf",
        "https://www.loteriasyapuestas.es:notaport/f/loterias/documentos/nota.pdf",
    )
    for unsafe_url in unsafe_urls:
        with pytest.raises(ValueError, match="official SELAE host"):
            validate_official_source_url(unsafe_url)

    with pytest.raises(ValueError, match="official SELAE host"):
        validate_official_source_url("https://example.com/nota.pdf")

    with pytest.raises(ValueError, match="official PDF"):
        validate_official_source_url("https://www.loteriasyapuestas.es/es/la-quiniela")


def test_draw_date_rejects_impossible_calendar_date() -> None:
    with pytest.raises(ValueError, match="draw_date must use ISO format"):
        validate_draw_date_in_text("Resultados", "2026-02-30")


def test_import_emits_hashable_pleno15_report_for_ticket_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "official.pdf"
    pdf_bytes = b"%PDF-1.7 synthetic official press-release bytes"
    pdf_path.write_bytes(pdf_bytes)
    press_text = """
    Jornada celebrada el 8 de noviembre de 2026.
    Resultados:
    2 - X - 2 - 2 - 1 - X - 1 - 2 - 2 - 2 - X - X - 2 - 1 - 12 -
    """
    monkeypatch.setattr(
        "scripts.import_selae_press_release.extract_pdf_text",
        lambda _path: press_text,
    )

    record = import_press_release(
        pdf_path,
        "2026-11-08",
        "https://www.loteriasyapuestas.es/f/loterias/documentos/nota.pdf",
        verified_at_utc="2026-11-08T16:00:00Z",
    )

    report = record["pleno15_result"]
    assert report["evidence_type"] == "official_press_release_pdf"
    assert report["draw_date"] == "2026-11-08"
    assert report["home_category"] == "1"
    assert report["away_category"] == "2"
    assert report["source_sha256"] == hashlib.sha256(pdf_bytes).hexdigest()
    assert report["verified_at_utc"] == "2026-11-08T16:00:00Z"


def test_import_rejects_non_pdf_bytes_before_text_extraction(tmp_path: Path) -> None:
    source = tmp_path / "not-a-pdf.pdf"
    source.write_bytes(b"not a PDF document")

    with pytest.raises(ValueError, match="PDF signature"):
        import_press_release(
            source,
            "2026-11-08",
            "https://www.loteriasyapuestas.es/f/loterias/documentos/nota.pdf",
        )


def test_parse_official_2026_11_15_press_release_compact_pleno() -> None:
    text = """
    En la jornada de la Quiniela celebrada hoy domingo día 15 de noviembre de 2026.
    Resultados:
    2 - X - 1 - X - 2 - 1 - 1 - X - 1 - 1 - 1 - 2 - 2 - X - 2M -
    """

    outcome = parse_selae_press_release_text(text)

    assert outcome.signs == (
        "2",
        "X",
        "1",
        "X",
        "2",
        "1",
        "1",
        "X",
        "1",
        "1",
        "1",
        "2",
        "2",
        "X",
    )
    assert outcome.pleno_home == "2"
    assert outcome.pleno_away == "M"
    assert outcome.pleno_code == "2M"
    assert validate_draw_date_in_text(text, "2026-11-15") == "2026-11-15"
