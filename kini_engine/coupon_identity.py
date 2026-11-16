from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from importlib.resources import files
from typing import Any

from .core import Match
from .team_identity import TeamIdentityRegistry


def load_coupon_team_aliases() -> dict[str, Any]:
    """Load the explicit season-scoped HistoricalQuiniela-to-Football-Data crosswalk."""
    resource = (
        files("kini_engine")
        .joinpath("data")
        .joinpath("historicoquiniela_team_aliases.json")
    )
    try:
        document = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("cannot read HistoricalQuiniela team alias crosswalk") from exc
    if (
        document.get("schema_version") != 1
        or document.get("source") != "historicoquiniela.com"
    ):
        raise ValueError("unsupported HistoricalQuiniela team alias crosswalk")
    return document


def _match_day(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    raw = str(value).strip()
    try:
        return datetime.fromisoformat(raw).date().isoformat()
    except ValueError:
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                continue
    raise ValueError(f"invalid historical match date: {value!r}")


def canonicalize_coupon(
    coupon: dict[str, Any],
    historical_matches: list[Match],
    *,
    alias_document: dict[str, Any] | None = None,
    registry: TeamIdentityRegistry | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Map all 15 source teams and reconcile exact date, fixture order and score.

    Historical results are consulted only to verify fixture identity/date/result.
    The caller must independently filter the model's training history to the
    coupon's pre-first-kickoff cutoff.
    """
    document = (
        alias_document if alias_document is not None else load_coupon_team_aliases()
    )
    if (
        document.get("schema_version") != 1
        or document.get("source") != "historicoquiniela.com"
    ):
        raise ValueError("invalid coupon team alias document")
    season_aliases = document.get("seasons", {}).get(coupon.get("season"))
    if not isinstance(season_aliases, dict) or not season_aliases:
        raise ValueError(
            f"no explicit team alias crosswalk for season {coupon.get('season')}"
        )
    team_registry = (
        registry if registry is not None else TeamIdentityRegistry.from_default()
    )
    resolved_coupon = deepcopy(coupon)
    reconciliation = []
    for fixture in resolved_coupon.get("fixtures", []):
        canonical_names = []
        for side in ("home", "away"):
            source_name = fixture[side]
            target_alias = season_aliases.get(source_name)
            if not isinstance(target_alias, str) or not target_alias.strip():
                raise ValueError(
                    f"{coupon.get('coupon_id')}: no explicit {side} alias for {source_name!r}"
                )
            identity = team_registry.resolve(target_alias, source="football-data")
            if identity is None:
                raise ValueError(
                    f"{coupon.get('coupon_id')}: Football-Data registry has no identity for {target_alias!r}"
                )
            canonical_names.append(identity.canonical_name)
        canonical_home, canonical_away = canonical_names
        fixture_day = datetime.fromisoformat(fixture["kickoff_at"]).date().isoformat()
        candidates = [
            match
            for match in historical_matches
            if _match_day(match.date) == fixture_day
            and match.home == canonical_home
            and match.away == canonical_away
        ]
        if len(candidates) != 1:
            raise ValueError(
                f"{coupon.get('coupon_id')} fixture {fixture['number']}: expected one exact "
                f"Football-Data match for {fixture_day} {canonical_home} vs {canonical_away}, "
                f"found {len(candidates)}"
            )
        match = candidates[0]
        if (
            match.home_goals != fixture["home_goals"]
            or match.away_goals != fixture["away_goals"]
            or match.outcome() != fixture["result"]
        ):
            raise ValueError(
                f"{coupon.get('coupon_id')} fixture {fixture['number']}: Football-Data score/result mismatch"
            )
        fixture["source_home"] = fixture["home"]
        fixture["source_away"] = fixture["away"]
        fixture["home"] = canonical_home
        fixture["away"] = canonical_away
        reconciliation.append(
            {
                "number": fixture["number"],
                "source_home": fixture["source_home"],
                "source_away": fixture["source_away"],
                "canonical_home": canonical_home,
                "canonical_away": canonical_away,
                "football_data_date": fixture_day,
                "football_data_division": (
                    match.detail.get("Div") if isinstance(match.detail, dict) else None
                ),
            }
        )
    if len(reconciliation) != 15:
        raise ValueError(
            f"{coupon.get('coupon_id')}: expected 15 reconciled fixtures, found {len(reconciliation)}"
        )
    return resolved_coupon, reconciliation
