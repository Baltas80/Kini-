from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

OFFICIAL_HOSTS = {"www.loteriasyapuestas.es", "loteriasyapuestas.es"}
SPANISH_MONTHS = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}
RESULT_HEADING_RE = re.compile(r"\b(?:resultados|results)\s*:", re.IGNORECASE)
RESULT_VECTOR_RE = re.compile(
    r"(?P<signs>(?:[12X]\s*-\s*){13}[12X])"
    r"\s*-\s*(?P<pleno_home>[012M])\s*-?\s*(?P<pleno_away>[012M])\b",
    re.IGNORECASE | re.DOTALL,
)
PARSER_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class SelaePressReleaseOutcome:
    signs: tuple[str, ...]
    pleno_home: str
    pleno_away: str
    raw_vector: str

    @property
    def pleno_code(self) -> str:
        return f"{self.pleno_home}{self.pleno_away}"


def parse_selae_press_release_text(text: str) -> SelaePressReleaseOutcome:
    """Parse the official 14-sign vector and two Pleno categories from PDF text."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("press-release text is empty")

    outcomes: list[SelaePressReleaseOutcome] = []
    for heading in RESULT_HEADING_RE.finditer(text):
        window = text[heading.end() : heading.end() + 2500]
        match = RESULT_VECTOR_RE.search(window)
        if match is None:
            continue

        signs = tuple(
            token.upper()
            for token in re.findall(r"[12X]", match.group("signs"), re.IGNORECASE)
        )
        if len(signs) != 14 or any(sign not in {"1", "X", "2"} for sign in signs):
            continue

        outcomes.append(
            SelaePressReleaseOutcome(
                signs=signs,
                pleno_home=match.group("pleno_home").upper(),
                pleno_away=match.group("pleno_away").upper(),
                raw_vector=re.sub(r"\s+", " ", match.group(0)).strip(),
            )
        )

    if not outcomes:
        raise ValueError(
            "no complete 14-sign plus Pleno vector found after a Results/Resultados heading"
        )

    unique = {
        (item.signs, item.pleno_home, item.pleno_away): item for item in outcomes
    }
    if len(unique) != 1:
        raise ValueError("press-release text contains conflicting result vectors")
    return next(iter(unique.values()))


def validate_draw_date_in_text(text: str, draw_date: str) -> str:
    try:
        parsed = date.fromisoformat(draw_date)
    except ValueError as exc:
        raise ValueError("draw_date must use ISO format YYYY-MM-DD") from exc

    month = SPANISH_MONTHS[parsed.month]
    normalized_text = re.sub(r"\s+", " ", text.casefold())
    date_forms = (
        f"{parsed.day} de {month} de {parsed.year}",
        f"{parsed.day:02d} de {month} de {parsed.year}",
    )
    if not any(form in normalized_text for form in date_forms):
        raise ValueError(
            f"draw date {draw_date} is not explicitly present in the press-release text"
        )
    return parsed.isoformat()


def validate_official_source_url(source_url: str) -> str:
    parsed = urlsplit(source_url)
    if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_HOSTS:
        raise ValueError("source_url must be an HTTPS URL on an official SELAE host")
    if not parsed.path.lower().endswith(".pdf"):
        raise ValueError("source_url must point to an official PDF")
    return source_url


def extract_pdf_text(pdf_path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "PDF support is optional; install it with: pip install -e '.[selae]'"
        ) from exc

    try:
        reader = PdfReader(str(pdf_path), strict=True)
        if reader.is_encrypted:
            raise ValueError("press-release PDF is encrypted")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise ValueError(f"unable to extract text from press-release PDF: {exc}") from exc

    if not text.strip():
        raise ValueError("press-release PDF contains no extractable text")
    return text


def import_press_release(
    pdf_path: Path,
    draw_date: str,
    source_url: str,
) -> dict[str, object]:
    source_url = validate_official_source_url(source_url)
    pdf_bytes = pdf_path.read_bytes()
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("input file does not have a PDF signature")

    text = extract_pdf_text(pdf_path)
    verified_date = validate_draw_date_in_text(text, draw_date)
    outcome = parse_selae_press_release_text(text)

    return {
        "schema_version": 1,
        "source": "SELAE",
        "source_type": "official_press_release_pdf",
        "source_url": source_url,
        "source_file_name": pdf_path.name,
        "source_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "draw_date": verified_date,
        "draw_date_verified_in_pdf": True,
        "signs": list(outcome.signs),
        "pleno": {
            "home": outcome.pleno_home,
            "away": outcome.pleno_away,
            "code": outcome.pleno_code,
        },
        "raw_result_vector": outcome.raw_vector,
        "parser_version": PARSER_VERSION,
        "status": "scenario_imported_unreconciled",
        "fixture_identity_status": "not_reconciled",
        "score_data_status": "not_parsed",
        "notes": (
            "The 14 ordered coupon signs and Pleno categories are imported. "
            "Fixture identities, football scores and postponed-match semantics "
            "are not inferred from this press-release parser."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Import one locally downloaded official SELAE Quiniela press-release PDF "
            "as an unreconciled 14-sign historical scenario."
        )
    )
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--draw-date", required=True, help="Expected draw date YYYY-MM-DD")
    parser.add_argument("--source-url", required=True, help="Official SELAE PDF URL")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    output_path = args.output or Path("artifacts/selae-press-releases") / f"{args.draw_date}.json"
    try:
        record = import_press_release(args.pdf, args.draw_date, args.source_url)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"SELAE_PRESS_RELEASE_IMPORT_ERROR: {exc}", file=sys.stderr)
        return 2

    print(
        f"SELAE_PRESS_RELEASE_IMPORTED date={record['draw_date']} "
        f"signs={len(record['signs'])} pleno={record['pleno']['code']}"
    )
    print(f"Record: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
