from __future__ import annotations

import argparse
import hashlib
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from kini_engine.coupons import (
    extract_historical_journeys,
    parse_historicoquiniela_coupon_html,
    selae_result_url,
    verify_coupon_against_selae,
    write_coupon_jsonl,
)

BASE_URL = "https://www.historicoquiniela.com"
SELAE_HOST = "www.loteriasyapuestas.es"
log = logging.getLogger("kini.coupon_import")


def make_session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": "Kini-Coupon-Archive/1.0 (+https://github.com/Baltas80/Kini-)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
    )
    return session


def decode_html(content: bytes, url: str) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{url}: response is not decodable HTML")


def fetch_page(session: requests.Session, url: str) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"refusing non-HTTPS source URL: {url}")
    if parsed.netloc not in {"www.historicoquiniela.com", SELAE_HOST}:
        raise ValueError(f"refusing unexpected source host: {parsed.netloc}")
    response = session.get(url, timeout=(8, 35))
    response.raise_for_status()
    if "text/html" not in response.headers.get("Content-Type", "").casefold():
        raise ValueError(
            f"{url}: expected text/html, got {response.headers.get('Content-Type')!r}"
        )
    return response.content, hashlib.sha256(response.content).hexdigest()


def save_raw(raw_dir: Path | None, name: str, content: bytes) -> None:
    if raw_dir is None:
        return
    target = raw_dir / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"refusing to overwrite raw source capture: {target}")
    target.write_bytes(content)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import historical Quiniela coupons and verify ordered results against SELAE."
    )
    parser.add_argument("--season", required=True, help="Season slug, e.g. 2020-2021")
    parser.add_argument("--journeys", type=int, nargs="*", help="Optional explicit journey numbers")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--delay-seconds", type=float, default=0.25)
    args = parser.parse_args()
    if not args.season or "/" in args.season or ".." in args.season:
        parser.error("season must be a simple YYYY-YYYY slug")
    if args.delay_seconds < 0:
        parser.error("delay-seconds must be non-negative")
    if args.journeys is not None and (
        not args.journeys or any(value < 1 for value in args.journeys)
    ):
        parser.error("journeys must contain positive journey numbers")
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    session = make_session()
    season_url = f"{BASE_URL}/historico/{args.season}"
    if args.journeys is None:
        season_bytes, season_sha = fetch_page(session, season_url)
        season_html = decode_html(season_bytes, season_url)
        journeys = extract_historical_journeys(season_html, season=args.season)
        save_raw(args.raw_dir, f"{args.season}/season-index.html", season_bytes)
    else:
        season_sha = None
        journeys = sorted(set(args.journeys))

    coupons = []
    for position, jornada in enumerate(journeys, start=1):
        source_url = f"{BASE_URL}/historico/{args.season}/{jornada}"
        source_bytes, source_sha = fetch_page(session, source_url)
        source_html = decode_html(source_bytes, source_url)
        coupon = parse_historicoquiniela_coupon_html(
            source_html,
            season=args.season,
            jornada=jornada,
            source_url=source_url,
            source_sha256=source_sha,
            retrieved_at_utc=datetime.now(UTC).isoformat(),
        )
        if coupon["result_published_at"] is None:
            raise ValueError(
                f"{coupon['coupon_id']}: publication date is missing; cannot derive SELAE result URL"
            )
        official_url = selae_result_url(coupon["result_published_at"])
        official_bytes, official_sha = fetch_page(session, official_url)
        coupon = verify_coupon_against_selae(
            coupon,
            decode_html(official_bytes, official_url),
            official_url=official_url,
            official_sha256=official_sha,
        )
        if coupon["official_main_matches_verified"] is not True:
            raise ValueError(
                f"{coupon['coupon_id']}: SELAE result reconciliation failed: "
                f"{coupon['official_verification_errors']}"
            )
        if coupon["official_pleno_verified"] is not True:
            raise ValueError(
                f"{coupon['coupon_id']}: Pleno al 15 could not be verified against SELAE"
            )
        save_raw(
            args.raw_dir,
            f"{args.season}/jornada-{jornada:02d}-historicoquiniela.html",
            source_bytes,
        )
        save_raw(
            args.raw_dir,
            f"{args.season}/jornada-{jornada:02d}-selae.html",
            official_bytes,
        )
        coupons.append(coupon)
        log.info(
            "Verified %s (%d/%d): 15 fixtures, first kickoff %s",
            coupon["coupon_id"],
            position,
            len(journeys),
            coupon["first_kickoff_at"],
        )
        if position < len(journeys) and args.delay_seconds:
            time.sleep(args.delay_seconds)

    manifest = {
        "source": "historicoquiniela.com",
        "season": args.season,
        "journey_numbers": journeys,
        "coupon_count": len(coupons),
        "season_index_url": season_url if season_sha else None,
        "season_index_sha256": season_sha,
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "timezone": "Europe/Madrid",
        "official_verification": (
            "14 main fixtures and Pleno al 15 reconciled by exact order, names and scores against SELAE HTML"
        ),
    }
    count = write_coupon_jsonl(args.output, coupons, manifest)
    log.info("COUPON_IMPORT_OK: %d verified coupons written to %s", count, args.output)


if __name__ == "__main__":
    main()
