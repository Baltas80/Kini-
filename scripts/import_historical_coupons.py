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

from kini_engine.coupon_snapshot import (
    load_official_coupon_snapshot,
    verify_coupon_against_selae_snapshot,
)
from kini_engine.coupons import (
    extract_historical_journeys,
    parse_historicoquiniela_coupon_html,
    selae_result_url,
    verify_coupon_against_selae,
    write_coupon_jsonl,
)

BASE_URL = "https://www.historicoquiniela.com"
SELAE_HOST = "www.loteriasyapuestas.es"
SELAE_INDEX_URL = "https://www.loteriasyapuestas.es/es/la-quiniela/resultados"
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
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
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


def fetch_page(
    session: requests.Session,
    url: str,
    *,
    referer: str | None = None,
) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc not in {
        "www.historicoquiniela.com",
        SELAE_HOST,
    }:
        raise ValueError(f"refusing unexpected source URL: {url}")
    response = session.get(
        url,
        headers={"Referer": referer} if referer else None,
        timeout=(10, 35),
        allow_redirects=True,
    )
    response.raise_for_status()
    if urlparse(response.url).netloc != parsed.netloc:
        raise ValueError(f"{url}: unexpected redirect to {response.url}")
    content_type = response.headers.get("Content-Type", "").casefold()
    if "html" not in content_type:
        raise ValueError(f"{url}: expected HTML, got {content_type!r}")
    return response.content, hashlib.sha256(response.content).hexdigest()


def save_raw(raw_dir: Path | None, name: str, content: bytes) -> None:
    if raw_dir is None:
        return
    target = raw_dir / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"refusing to overwrite raw source capture: {target}")
    target.write_bytes(content)



def load_official_snapshot_for_journey(
    snapshot_dir: Path,
    season: str,
    jornada: int,
) -> tuple[dict[str, object], str, Path]:
    """Load the reviewed SELAE extract assigned to one season/journey."""
    if not snapshot_dir.is_dir():
        raise NotADirectoryError(
            f"official SELAE snapshot directory does not exist: {snapshot_dir}"
        )
    if isinstance(jornada, bool) or not isinstance(jornada, int) or jornada < 1:
        raise ValueError("journey number must be a positive integer")
    path = snapshot_dir / f"{season}-{jornada}.json"
    if path.is_symlink():
        raise ValueError(f"refusing symlinked official snapshot: {path}")
    if not path.is_file():
        raise FileNotFoundError(
            f"missing official SELAE snapshot for {season} journey {jornada}: {path}"
        )
    snapshot, digest = load_official_coupon_snapshot(path)
    return snapshot, digest, path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import historical Quiniela coupons and verify ordered results against SELAE."
    )
    parser.add_argument("--season", required=True, help="Season slug, e.g. 2020-2021")
    parser.add_argument(
        "--journeys", type=int, nargs="*", help="Optional explicit journey numbers"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--official-snapshot", type=Path)
    parser.add_argument(
        "--official-snapshot-dir",
        type=Path,
        help="Directory of reviewed snapshots named SEASON-JOURNEY.json",
    )
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
    if args.official_snapshot is not None and args.official_snapshot_dir is not None:
        parser.error("--official-snapshot and --official-snapshot-dir are mutually exclusive")
    if args.official_snapshot_dir is not None and not args.official_snapshot_dir.is_dir():
        parser.error(f"official snapshot directory does not exist: {args.official_snapshot_dir}")
    if args.official_snapshot and (
        args.journeys is None or len(set(args.journeys)) != 1
    ):
        parser.error(
            "an official snapshot can only be used with exactly one explicit journey"
        )

    official_snapshot = None
    official_snapshot_sha = None
    if args.official_snapshot:
        official_snapshot, official_snapshot_sha = load_official_coupon_snapshot(
            args.official_snapshot
        )
    snapshot_records: list[dict[str, object]] = []

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    session = make_session()
    season_url = f"{BASE_URL}/historico/{args.season}"
    if args.journeys is None:
        season_bytes, season_sha = fetch_page(
            session, season_url, referer=f"{BASE_URL}/"
        )
        season_html = decode_html(season_bytes, season_url)
        journeys = extract_historical_journeys(season_html, season=args.season)
        save_raw(args.raw_dir, f"{args.season}/season-index.html", season_bytes)
    else:
        season_sha = None
        journeys = sorted(set(args.journeys))

    coupons = []
    for position, jornada in enumerate(journeys, start=1):
        source_url = f"{BASE_URL}/historico/{args.season}/{jornada}"
        source_bytes, source_sha = fetch_page(session, source_url, referer=season_url)
        source_html = decode_html(source_bytes, source_url)
        coupon = parse_historicoquiniela_coupon_html(
            source_html,
            season=args.season,
            jornada=jornada,
            source_url=source_url,
            source_sha256=source_sha,
            retrieved_at_utc=datetime.now(UTC).isoformat(),
        )
        if coupon["source_date"] is None:
            raise ValueError(
                f"{coupon['coupon_id']}: source date label is missing; cannot derive SELAE draw-date URL"
            )

        official_bytes = None
        coupon_snapshot = official_snapshot
        coupon_snapshot_sha = official_snapshot_sha
        coupon_snapshot_path = args.official_snapshot
        if args.official_snapshot_dir is not None:
            (
                coupon_snapshot,
                coupon_snapshot_sha,
                coupon_snapshot_path,
            ) = load_official_snapshot_for_journey(
                args.official_snapshot_dir,
                args.season,
                jornada,
            )
        if coupon_snapshot is not None:
            official_url = coupon_snapshot["source_url"]
            coupon = verify_coupon_against_selae_snapshot(
                coupon,
                coupon_snapshot,
                snapshot_sha256=coupon_snapshot_sha,
            )
            coupon["official_result_snapshot_path"] = str(coupon_snapshot_path)
            snapshot_records.append(
                {
                    "journey": jornada,
                    "path": str(coupon_snapshot_path),
                    "sha256": coupon_snapshot_sha,
                }
            )
        else:
            official_url = selae_result_url(coupon["source_date"])
            official_bytes, official_sha = fetch_page(
                session,
                official_url,
                referer=SELAE_INDEX_URL,
            )
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
        if official_bytes is not None:
            save_raw(
                args.raw_dir,
                f"{args.season}/jornada-{jornada:02d}-selae.html",
                official_bytes,
            )
        coupons.append(coupon)
        log.info(
            "Verified %s (%d/%d): 15 fixtures, first kickoff %s, Pleno verified=%s",
            coupon["coupon_id"],
            position,
            len(journeys),
            coupon["first_kickoff_at"],
            coupon["official_pleno_verified"],
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
            "14 main fixtures and Pleno al 15 reconciled by exact order, names and scores against SELAE"
        ),
        "official_snapshot_path": str(args.official_snapshot)
        if args.official_snapshot
        else None,
        "official_snapshot_dir": str(args.official_snapshot_dir)
        if args.official_snapshot_dir
        else None,
        "official_snapshots": snapshot_records,
        "official_snapshot_sha256": official_snapshot_sha,
    }
    count = write_coupon_jsonl(args.output, coupons, manifest)
    log.info("COUPON_IMPORT_OK: %d verified coupons written to %s", count, args.output)


if __name__ == "__main__":
    main()
