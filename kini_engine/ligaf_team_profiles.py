from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from kini_engine.ligaf_history import (
    ARCHIVE_URL,
    DEFAULT_CACHE_DIR,
    MATCH_PATH,
    LigaFHistoryError,
    _atomic_write,
    _official_url,
    _parse_document,
    extract_match_links,
    extract_round_dates,
    fetch_html,
    make_session,
    parse_match_detail,
)

DEFAULT_OUTPUT = Path("data/ligaf_historical_team_profiles.json")
DEFAULT_SEASONS = (2023, 2024, 2025, 2026)
PROFILE_PATH = re.compile(
    r"^/equipo/(?P<slug>[^/]+)/(?P<profile_id>[0-9]+)/"
    r"plantilla/(?P<link_year>[0-9]{4})/?$"
)


def _normalized_name(value: str) -> str:
    return " ".join(value.casefold().split())


def extract_team_profile_link(
    html: str,
    *,
    match_url: str,
    team_name: str,
) -> dict[str, str]:
    """Resolve a team's profile ID only from its exact official match-page anchor."""
    _official_url(match_url, "match_url")
    expected_name = _normalized_name(team_name)
    document = _parse_document(html)
    candidates: dict[tuple[str, str, str], str] = {}

    for link in document.links:
        if _normalized_name(link["text"]) != expected_name:
            continue
        href = link["href"].strip()
        if not href:
            continue
        absolute = urljoin(match_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme != "https" or parsed.hostname not in {
            "ligaf.es",
            "www.ligaf.es",
        }:
            continue
        match = PROFILE_PATH.fullmatch(parsed.path)
        if match is None:
            continue
        _official_url(absolute, "team_profile_link_url")
        key = (
            match.group("slug"),
            match.group("profile_id"),
            match.group("link_year"),
        )
        candidates[key] = f"https://ligaf.es{parsed.path}"

    if not candidates:
        raise LigaFHistoryError(
            f"match page has no official team-profile link for {team_name!r}"
        )
    if len(candidates) != 1:
        raise LigaFHistoryError(
            f"team {team_name!r} has conflicting official profile links"
        )

    (slug, profile_id, link_year), source_url = next(iter(candidates.items()))
    return {
        "profile_slug": slug,
        "provider_team_profile_id": profile_id,
        "profile_link_season_end_year": link_year,
        "match_detail_profile_link_url": source_url,
    }


def parse_team_profile_page(
    html: str,
    *,
    profile_url: str,
    season_end_year: int,
) -> str:
    """Validate a season-scoped official profile page and return its heading."""
    _official_url(profile_url, "team_profile_url")
    parsed_url = urlparse(profile_url)
    path_match = PROFILE_PATH.fullmatch(parsed_url.path)
    if path_match is None:
        raise LigaFHistoryError("team_profile_url has an invalid official path")
    if path_match.group("link_year") != str(season_end_year):
        raise LigaFHistoryError(
            "team_profile_url does not identify the requested season"
        )

    document = _parse_document(html)
    title_match = re.fullmatch(
        r"\s*Plantilla\s+(?P<name>.+?)\s*(?:\|\s*LPFF)?\s*",
        document.title,
        flags=re.IGNORECASE,
    )
    if title_match is None:
        raise LigaFHistoryError(
            f"official profile page has no recognizable team heading: {profile_url}"
        )
    if re.search(
        r"Clasificación\s+Jornada\s+\d+",
        document.text,
        flags=re.IGNORECASE,
    ) is None:
        raise LigaFHistoryError(
            f"official profile page has no season standings: {profile_url}"
        )
    return title_match.group("name").strip()


def _season_name(season_end_year: int) -> str:
    return f"{season_end_year - 1}-{str(season_end_year)[-2:]}"


def _cross_season_observations(
    seasons: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    observed: dict[str, list[dict[str, str]]] = defaultdict(list)
    for season_end_year, season in seasons.items():
        for entry in season["entries"]:
            observed[entry["provider_team_profile_id"]].append(
                {
                    "season_end_year": season_end_year,
                    "team_name_in_match": entry["team_name_in_match"],
                    "team_profile_url": entry["team_profile_url"],
                }
            )

    summaries = []
    for profile_id, rows in sorted(observed.items()):
        season_years = sorted({row["season_end_year"] for row in rows})
        labels = sorted({row["team_name_in_match"] for row in rows})
        if len(season_years) < 2:
            status = "single_season_observation"
        elif len(labels) == 1:
            status = "repeat_profile_id_same_label_unreviewed"
        else:
            status = "repeat_profile_id_with_label_change_requires_review"
        summaries.append(
            {
                "provider_team_profile_id": profile_id,
                "seasons": season_years,
                "observed_team_names": labels,
                "continuity_status": status,
                "observations": sorted(
                    rows,
                    key=lambda row: (
                        row["season_end_year"],
                        row["team_name_in_match"],
                    ),
                ),
            }
        )
    return summaries


def _cross_season_display_name_observations(
    seasons: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect one source display name being assigned multiple provider IDs."""
    observed: dict[str, list[dict[str, str]]] = defaultdict(list)
    for season_end_year, season in seasons.items():
        for entry in season["entries"]:
            observed[_normalized_name(entry["team_name_in_match"])].append(
                {
                    "season_end_year": season_end_year,
                    "team_name_in_match": entry["team_name_in_match"],
                    "provider_team_profile_id": entry["provider_team_profile_id"],
                    "team_profile_url": entry["team_profile_url"],
                }
            )

    summaries = []
    for normalized_name, rows in sorted(observed.items()):
        season_years = sorted({row["season_end_year"] for row in rows})
        profile_ids = sorted(
            {row["provider_team_profile_id"] for row in rows}
        )
        labels = sorted({row["team_name_in_match"] for row in rows})
        if len(season_years) < 2:
            status = "single_season_observation"
        elif len(profile_ids) == 1:
            status = "same_display_name_same_profile_id_unreviewed"
        else:
            status = "same_display_name_multiple_profile_ids_requires_review"
        summaries.append(
            {
                "normalized_name": normalized_name,
                "seasons": season_years,
                "observed_team_names": labels,
                "provider_team_profile_ids": profile_ids,
                "continuity_status": status,
                "observations": sorted(
                    rows,
                    key=lambda row: (
                        row["season_end_year"],
                        row["provider_team_profile_id"],
                    ),
                ),
            }
        )
    return summaries


def validate_historical_team_profiles(document: dict[str, Any]) -> None:
    """Validate evidence structure without assigning canonical club identities."""
    if document.get("schema_version") != 1:
        raise LigaFHistoryError("historical team-profile schema_version must equal 1")
    if document.get("provider") != "LIGA_F":
        raise LigaFHistoryError("historical team-profile provider must equal LIGA_F")
    if document.get("competition_id") != "LIGA_F":
        raise LigaFHistoryError(
            "historical team-profile competition_id must equal LIGA_F"
        )
    if document.get("gender") != "women":
        raise LigaFHistoryError("historical team-profile gender must equal women")
    eligibility = document.get("training_eligibility")
    if not isinstance(eligibility, dict) or eligibility.get("eligible") is not False:
        raise LigaFHistoryError(
            "historical team profiles must remain excluded from training"
        )

    seasons = document.get("seasons")
    if not isinstance(seasons, dict) or not seasons:
        raise LigaFHistoryError("historical team-profile seasons must be non-empty")

    for season_end_year, season in seasons.items():
        if not season_end_year.isdigit():
            raise LigaFHistoryError(
                "historical team-profile season key must be numeric"
            )
        expected_year = int(season_end_year)
        if season.get("season_end_year") != expected_year:
            raise LigaFHistoryError("season_end_year does not match its season key")
        if season.get("season") != _season_name(expected_year):
            raise LigaFHistoryError("season label does not match season_end_year")
        if season.get("matchday") != 30:
            raise LigaFHistoryError("historical profile evidence must use matchday 30")
        if season.get("all_profile_pages_verified") is not True:
            raise LigaFHistoryError("all historical profile pages must be verified")
        entries = season.get("entries")
        if not isinstance(entries, list) or len(entries) != 16:
            raise LigaFHistoryError(
                f"season {season_end_year} must contain exactly 16 team profiles"
            )
        names: set[str] = set()
        profile_ids: set[str] = set()
        for index, entry in enumerate(entries):
            location = f"seasons[{season_end_year}].entries[{index}]"
            if "team_id" in entry or "canonical_team_id" in entry:
                raise LigaFHistoryError(
                    f"{location} must not assign a canonical team identity"
                )
            name = entry.get("team_name_in_match")
            profile_id = entry.get("provider_team_profile_id")
            if not isinstance(name, str) or not name.strip():
                raise LigaFHistoryError(f"{location} has no source team name")
            if not isinstance(profile_id, str) or not profile_id.isdigit():
                raise LigaFHistoryError(
                    f"{location} has an invalid provider profile ID"
                )
            normalized = _normalized_name(name)
            if normalized in names:
                raise LigaFHistoryError(
                    f"season {season_end_year} has duplicate team display names"
                )
            if profile_id in profile_ids:
                raise LigaFHistoryError(
                    f"season {season_end_year} has duplicate provider profile IDs"
                )
            names.add(normalized)
            profile_ids.add(profile_id)

            profile_url = _official_url(
                entry.get("team_profile_url", ""),
                f"{location}.team_profile_url",
            )
            profile_path = PROFILE_PATH.fullmatch(urlparse(profile_url).path)
            if (
                profile_path is None
                or profile_path.group("profile_id") != profile_id
                or profile_path.group("link_year") != season_end_year
            ):
                raise LigaFHistoryError(
                    f"{location}.team_profile_url conflicts with its ID or season"
                )
            profile_link_url = _official_url(
                entry.get("match_detail_profile_link_url", ""),
                f"{location}.match_detail_profile_link_url",
            )
            profile_link_path = PROFILE_PATH.fullmatch(
                urlparse(profile_link_url).path
            )
            if (
                profile_link_path is None
                or profile_link_path.group("profile_id") != profile_id
                or profile_link_path.group("slug") != profile_path.group("slug")
            ):
                raise LigaFHistoryError(
                    f"{location}.match_detail_profile_link_url conflicts "
                    "with its profile"
                )
            match_evidence_url = _official_url(
                entry.get("match_evidence_url", ""),
                f"{location}.match_evidence_url",
            )
            if MATCH_PATH.fullmatch(urlparse(match_evidence_url).path) is None:
                raise LigaFHistoryError(
                    f"{location}.match_evidence_url is not an official match URL"
                )
            heading = entry.get("profile_heading")
            if not isinstance(heading, str) or not heading.strip():
                raise LigaFHistoryError(f"{location} has no verified profile heading")
            name_match_exact = entry.get("name_match_exact")
            review_required = entry.get("identity_review_required")
            if not isinstance(name_match_exact, bool) or not isinstance(
                review_required, bool
            ):
                raise LigaFHistoryError(
                    f"{location} has invalid identity-review flags"
                )
            if review_required != (not name_match_exact):
                raise LigaFHistoryError(
                    f"{location} has inconsistent identity-review status"
                )
            for digest_field in (
                "match_evidence_sha256",
                "profile_page_sha256",
            ):
                digest = entry.get(digest_field)
                if not isinstance(digest, str) or re.fullmatch(
                    r"[0-9a-f]{64}", digest
                ) is None:
                    raise LigaFHistoryError(
                        f"{location}.{digest_field} must be a SHA-256 hex digest"
                    )
            if entry.get("identity_status") not in {
                "exact_name_match",
                "manual_review_required",
            }:
                raise LigaFHistoryError(f"{location} has an invalid identity status")
        exact_matches = sum(
            entry["name_match_exact"] for entry in entries
        )
        review_count = sum(
            entry["identity_review_required"] for entry in entries
        )
        if (
            season.get("team_count") != 16
            or season.get("unique_profile_ids") != 16
            or season.get("verified_profile_pages") != 16
            or season.get("exact_name_matches") != exact_matches
            or season.get("review_required_count") != review_count
        ):
            raise LigaFHistoryError(
                f"season {season_end_year} profile coverage summary is inconsistent"
            )

    provider_observations = _cross_season_observations(seasons)
    name_observations = _cross_season_display_name_observations(seasons)
    expected_identity_summary = {
        "unique_display_names": len(name_observations),
        "unique_provider_profile_ids": len(provider_observations),
        "display_names_with_multiple_provider_ids": sum(
            item["continuity_status"]
            == "same_display_name_multiple_profile_ids_requires_review"
            for item in name_observations
        ),
        "provider_ids_with_multiple_display_names": sum(
            item["continuity_status"]
            == "repeat_profile_id_with_label_change_requires_review"
            for item in provider_observations
        ),
        "canonical_identity_assignments": 0,
    }
    if document.get("cross_season_provider_id_observations") != provider_observations:
        raise LigaFHistoryError(
            "cross-season provider-ID observations are inconsistent"
        )
    if document.get("cross_season_display_name_observations") != name_observations:
        raise LigaFHistoryError(
            "cross-season display-name observations are inconsistent"
        )
    if document.get("identity_audit_summary") != expected_identity_summary:
        raise LigaFHistoryError("cross-season identity audit summary is inconsistent")


def build_historical_team_profiles(
    *,
    seasons: tuple[int, ...] = DEFAULT_SEASONS,
    output: str | Path = DEFAULT_OUTPUT,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    cache_ttl_hours: float = 168.0,
    refresh: bool = False,
    offline: bool = False,
    request_delay: float = 0.25,
    session: Any | None = None,
) -> dict[str, Any]:
    """Build season-scoped provider-ID evidence from official match/profile pages."""
    selected = tuple(sorted({int(year) for year in seasons}))
    if not selected:
        raise ValueError("at least one completed season must be selected")
    if any(year < 2023 or year > 2100 for year in selected):
        raise ValueError("season end years must be between 2023 and 2100")

    client = session or make_session()
    season_documents: dict[str, dict[str, Any]] = {}

    for season_end_year in selected:
        round_url = ARCHIVE_URL.format(
            matchday=30,
            season_end_year=season_end_year,
        )
        round_html, round_meta = fetch_html(
            round_url,
            cache_dir=cache_dir,
            session=client,
            cache_ttl_hours=cache_ttl_hours,
            refresh=refresh,
            offline=offline,
            request_delay=request_delay,
        )
        links = extract_match_links(round_html, page_url=round_url)
        if len(links) != 8:
            raise LigaFHistoryError(
                f"season {season_end_year} final round has {len(links)} "
                "matches; expected 8"
            )
        round_dates = extract_round_dates(
            round_html,
            season_end_year=season_end_year,
            matchday=30,
        )
        teams: dict[str, dict[str, Any]] = {}

        for link in links:
            match_html, match_meta = fetch_html(
                link["match_url"],
                cache_dir=cache_dir,
                session=client,
                cache_ttl_hours=cache_ttl_hours,
                refresh=refresh,
                offline=offline,
                request_delay=request_delay,
            )
            row = parse_match_detail(
                match_html,
                match_url=link["match_url"],
                season_end_year=season_end_year,
                expected_matchday=30,
                round_url=round_url,
                match_source_metadata=match_meta,
                round_source_metadata=round_meta,
                allowed_round_dates=round_dates,
            )
            if row["match_status"] != "played":
                raise LigaFHistoryError(
                    f"completed season {season_end_year} final-round match "
                    f"{row['match_id']} is not final"
                )

            for side in ("home", "away"):
                team_name = row[f"{side}_team_name"]
                profile_link = extract_team_profile_link(
                    match_html,
                    match_url=link["match_url"],
                    team_name=team_name,
                )
                key = _normalized_name(team_name)
                candidate = {
                    **profile_link,
                    "team_name_in_match": team_name,
                    "match_evidence_url": link["match_url"],
                    "match_evidence_sha256": match_meta["content_sha256"],
                }
                previous = teams.get(key)
                if previous is not None and (
                    previous["provider_team_profile_id"]
                    != candidate["provider_team_profile_id"]
                    or previous["profile_slug"] != candidate["profile_slug"]
                ):
                    raise LigaFHistoryError(
                        f"season {season_end_year} has conflicting provider IDs "
                        f"for {team_name!r}"
                    )
                teams.setdefault(key, candidate)

        if len(teams) != 16:
            raise LigaFHistoryError(
                f"season {season_end_year} final round resolves {len(teams)} "
                "distinct teams; expected 16"
            )
        profile_ids = {
            item["provider_team_profile_id"] for item in teams.values()
        }
        if len(profile_ids) != 16:
            raise LigaFHistoryError(
                f"season {season_end_year} does not resolve 16 unique provider IDs"
            )

        entries = []
        for key, item in sorted(teams.items()):
            profile_url = (
                "https://ligaf.es/equipo/"
                f"{item['profile_slug']}/"
                f"{item['provider_team_profile_id']}/plantilla/{season_end_year}"
            )
            _official_url(profile_url, "team_profile_url")
            profile_html, profile_meta = fetch_html(
                profile_url,
                cache_dir=cache_dir,
                session=client,
                cache_ttl_hours=cache_ttl_hours,
                refresh=refresh,
                offline=offline,
                request_delay=request_delay,
            )
            heading = parse_team_profile_page(
                profile_html,
                profile_url=profile_url,
                season_end_year=season_end_year,
            )
            exact_name_match = _normalized_name(heading) == key
            entries.append(
                {
                    "season": _season_name(season_end_year),
                    "season_end_year": season_end_year,
                    "team_name_in_match": item["team_name_in_match"],
                    "profile_heading": heading,
                    "provider_team_profile_id": item["provider_team_profile_id"],
                    "profile_slug": item["profile_slug"],
                    "profile_link_season_end_year": int(
                        item["profile_link_season_end_year"]
                    ),
                    "match_detail_profile_link_url": item[
                        "match_detail_profile_link_url"
                    ],
                    "team_profile_url": profile_url,
                    "match_evidence_url": item["match_evidence_url"],
                    "match_evidence_sha256": item["match_evidence_sha256"],
                    "profile_page_retrieved_at_utc": profile_meta[
                        "retrieved_at_utc"
                    ],
                    "profile_page_sha256": profile_meta["content_sha256"],
                    "name_match_exact": exact_name_match,
                    "identity_review_required": not exact_name_match,
                    "identity_status": (
                        "exact_name_match"
                        if exact_name_match
                        else "manual_review_required"
                    ),
                }
            )

        season_documents[str(season_end_year)] = {
            "season": _season_name(season_end_year),
            "season_end_year": season_end_year,
            "matchday": 30,
            "source_archive_url": round_url,
            "source_archive_sha256": round_meta["content_sha256"],
            "team_count": len(entries),
            "unique_profile_ids": len(profile_ids),
            "verified_profile_pages": len(entries),
            "exact_name_matches": sum(
                entry["name_match_exact"] for entry in entries
            ),
            "review_required_count": sum(
                entry["identity_review_required"] for entry in entries
            ),
            "all_profile_pages_verified": True,
            "entries": sorted(
                entries,
                key=lambda entry: (
                    _normalized_name(entry["team_name_in_match"]),
                    entry["provider_team_profile_id"],
                ),
            ),
        }

    provider_observations = _cross_season_observations(season_documents)
    name_observations = _cross_season_display_name_observations(season_documents)
    identity_summary = {
        "unique_display_names": len(name_observations),
        "unique_provider_profile_ids": len(provider_observations),
        "display_names_with_multiple_provider_ids": sum(
            item["continuity_status"]
            == "same_display_name_multiple_profile_ids_requires_review"
            for item in name_observations
        ),
        "provider_ids_with_multiple_display_names": sum(
            item["continuity_status"]
            == "repeat_profile_id_with_label_change_requires_review"
            for item in provider_observations
        ),
        "canonical_identity_assignments": 0,
    }
    document = {
        "schema_version": 1,
        "provider": "LIGA_F",
        "competition_id": "LIGA_F",
        "gender": "women",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "verification_method": (
            "For each completed season, provider profile IDs are extracted from "
            "the exact home/away team-name anchors on official final-round match "
            "pages. The same provider ID and slug are then used to request the "
            "season-end-year profile route; the page title and season standings "
            "must validate. Cross-season repetition is reported as evidence only; "
            "no canonical team identity or rename is inferred."
        ),
        "seasons": season_documents,
        "cross_season_provider_id_observations": provider_observations,
        "cross_season_display_name_observations": name_observations,
        "identity_audit_summary": identity_summary,
        "training_eligibility": {
            "eligible": False,
            "reason": (
                "Historical profile IDs are source evidence only. Club identity "
                "continuity, renames and pre-kickoff feature availability require "
                "separate validation before any training use."
            ),
        },
    }
    validate_historical_team_profiles(document)
    _atomic_write(
        Path(output),
        (
            json.dumps(
                document,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8"),
    )
    return document


def _parse_args() -> Any:
    import argparse

    parser = argparse.ArgumentParser(
        description="Build a season-scoped Liga F team-profile evidence crosswalk."
    )
    parser.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        default=list(DEFAULT_SEASONS),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--cache-ttl-hours", type=float, default=168.0)
    parser.add_argument("--request-delay", type=float, default=0.25)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--offline", action="store_true")
    return parser.parse_args()


def main() -> None:
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = _parse_args()
    document = build_historical_team_profiles(
        seasons=tuple(args.seasons),
        output=args.output,
        cache_dir=args.cache_dir,
        cache_ttl_hours=args.cache_ttl_hours,
        request_delay=args.request_delay,
        refresh=args.refresh,
        offline=args.offline,
    )
    for year, season in document["seasons"].items():
        print(
            "LIGA_F_TEAM_PROFILES_OK: "
            f"season={year} teams={season['team_count']} "
            f"exact_names={season['exact_name_matches']} "
            f"review_required={season['review_required_count']}"
        )


if __name__ == "__main__":
    main()
