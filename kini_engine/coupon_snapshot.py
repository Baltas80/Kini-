from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .team_identity import normalize_team_name


def load_official_coupon_snapshot(path: str | Path) -> tuple[dict[str, Any], str]:
    raw = Path(path).read_bytes()
    snapshot = json.loads(raw)
    if not isinstance(snapshot, dict):
        raise TypeError("official coupon snapshot must be a JSON object")
    return snapshot, hashlib.sha256(raw).hexdigest()


def _result(home_goals: int, away_goals: int) -> str:
    return "1" if home_goals > away_goals else ("2" if away_goals > home_goals else "X")


def _category(goals: int) -> str:
    return str(goals) if goals < 3 else "M"


def verify_coupon_against_selae_snapshot(
    coupon: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    snapshot_sha256: str,
) -> dict[str, Any]:
    """Verify a coupon against a reviewed, normalized extract of an official SELAE page.

    The digest covers the normalized JSON snapshot, not the original HTML bytes.
    """
    if snapshot.get("schema_version") != 1 or snapshot.get("source") != "SELAE":
        raise ValueError("unsupported official SELAE coupon snapshot")
    if snapshot.get("snapshot_type") != "normalized_json_extract_not_raw_html":
        raise ValueError("official snapshot must declare its normalized-extract type")
    if not re.fullmatch(r"[0-9a-f]{64}", snapshot_sha256):
        raise ValueError("official snapshot SHA-256 is invalid")
    source_url = urlparse(str(snapshot.get("source_url", "")))
    if source_url.scheme != "https" or source_url.netloc != "www.loteriasyapuestas.es":
        raise ValueError("official snapshot URL must use the SELAE HTTPS host")
    if (
        not isinstance(snapshot.get("verification_method"), str)
        or not snapshot["verification_method"].strip()
    ):
        raise ValueError("official snapshot verification method is required")
    try:
        snapshot_date = date.fromisoformat(snapshot["draw_date"])
        coupon_draw_date = date.fromisoformat(coupon["source_date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "coupon source date label and official draw date are required"
        ) from exc
    if snapshot_date != coupon_draw_date:
        raise ValueError(
            f"official snapshot draw date {snapshot_date} does not match coupon source date {coupon_draw_date}"
        )

    official_fixtures = snapshot.get("fixtures")
    if not isinstance(official_fixtures, list) or len(official_fixtures) != 14:
        raise ValueError(
            "official snapshot must contain exactly 14 ordered main fixtures"
        )
    main_errors = []
    for expected, actual in zip(
        coupon["fixtures"][:14], official_fixtures, strict=True
    ):
        number = expected["number"]
        if actual.get("number") != number:
            main_errors.append(f"fixture {number}: official order mismatch")
        if normalize_team_name(expected["home"]) != normalize_team_name(
            actual.get("home", "")
        ):
            main_errors.append(f"fixture {number}: home team mismatch")
        if normalize_team_name(expected["away"]) != normalize_team_name(
            actual.get("away", "")
        ):
            main_errors.append(f"fixture {number}: away team mismatch")
        home_goals = actual.get("home_goals")
        away_goals = actual.get("away_goals")
        if not isinstance(home_goals, int) or not isinstance(away_goals, int):
            main_errors.append(f"fixture {number}: official score is invalid")
            continue
        if expected["home_goals"] != home_goals:
            main_errors.append(f"fixture {number}: home score mismatch")
        if expected["away_goals"] != away_goals:
            main_errors.append(f"fixture {number}: away score mismatch")
        if expected["result"] != actual.get("result"):
            main_errors.append(f"fixture {number}: result mismatch")
        if actual.get("result") != _result(home_goals, away_goals):
            main_errors.append(
                f"fixture {number}: official sign conflicts with official score"
            )

    expected_pleno = coupon["fixtures"][14]
    official_pleno = snapshot.get("pleno")
    pleno_errors = []
    if not isinstance(official_pleno, dict) or official_pleno.get("number") != 15:
        pleno_errors.append("official Pleno al 15 record is missing")
    else:
        home_goals = official_pleno.get("home_goals")
        away_goals = official_pleno.get("away_goals")
        if not isinstance(home_goals, int) or not isinstance(away_goals, int):
            pleno_errors.append("official Pleno scores are invalid")
        else:
            if expected_pleno["home_goals"] != home_goals:
                pleno_errors.append("Pleno home score mismatch")
            if expected_pleno["away_goals"] != away_goals:
                pleno_errors.append("Pleno away score mismatch")
            if official_pleno.get("home_category") != _category(home_goals):
                pleno_errors.append("official Pleno home category conflicts with score")
            if official_pleno.get("away_category") != _category(away_goals):
                pleno_errors.append("official Pleno away category conflicts with score")
        if normalize_team_name(expected_pleno["home"]) != normalize_team_name(
            official_pleno.get("home", "")
        ):
            pleno_errors.append("Pleno home team mismatch")
        if normalize_team_name(expected_pleno["away"]) != normalize_team_name(
            official_pleno.get("away", "")
        ):
            pleno_errors.append("Pleno away team mismatch")
        if expected_pleno.get("pleno_home_category") != official_pleno.get(
            "home_category"
        ):
            pleno_errors.append("Pleno home category mismatch")
        if expected_pleno.get("pleno_away_category") != official_pleno.get(
            "away_category"
        ):
            pleno_errors.append("Pleno away category mismatch")

    errors = main_errors + pleno_errors
    coupon["official_result_url"] = snapshot["source_url"]
    coupon["official_result_sha256"] = snapshot_sha256
    coupon["official_result_snapshot_type"] = snapshot["snapshot_type"]
    coupon["official_verification_method"] = snapshot["verification_method"]
    coupon["official_verified_at"] = snapshot.get("verified_at")
    coupon["official_main_matches_verified"] = not main_errors
    coupon["official_pleno_verified"] = not pleno_errors
    coupon["official_verification_errors"] = errors
    if errors:
        raise ValueError(
            f"{coupon.get('coupon_id')}: SELAE snapshot reconciliation failed: {errors}"
        )
    return coupon
