from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
import json
from pathlib import Path
from typing import Any
import unicodedata


SUPPORTED_GENDERS = frozenset({"men", "women", "mixed", "unknown"})


class TeamIdentityRegistryError(ValueError):
    """Raised when the canonical team registry is malformed or inconsistent."""


class AmbiguousTeamIdentityError(TeamIdentityRegistryError):
    """Raised when an exact source alias resolves to more than one team."""


@dataclass(frozen=True)
class TeamIdentity:
    team_id: str
    canonical_name: str
    gender: str
    source: str
    matched_alias: str


@dataclass(frozen=True)
class _AliasBinding:
    team: TeamIdentity
    participations: frozenset[tuple[str, str]]


def normalize_team_name(value: str) -> str:
    """Normalize Unicode form, case and whitespace without fuzzy substitutions.

    Accents and punctuation are intentionally preserved. For example, "Málaga"
    does not silently become "Malaga"; a provider-specific spelling variant
    must be added as an explicit alias after its identity has been verified.
    """
    if not isinstance(value, str):
        raise TypeError("team name must be a string")
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()


class TeamIdentityRegistry:
    """Strict, source-scoped team identity lookup with no fuzzy fallback."""

    def __init__(self, document: dict[str, Any]) -> None:
        if not isinstance(document, dict):
            raise TeamIdentityRegistryError("registry document must be an object")
        if document.get("schema_version") != 1:
            raise TeamIdentityRegistryError("unsupported team registry schema_version")

        teams = document.get("teams")
        if not isinstance(teams, list) or not teams:
            raise TeamIdentityRegistryError("registry must contain a non-empty teams list")

        self.registry_id = str(document.get("registry_id") or "")
        self.source_dataset = document.get("source_dataset", {})
        self._team_ids: set[str] = set()
        self._bindings: dict[tuple[str, str], list[_AliasBinding]] = {}

        for index, raw_team in enumerate(teams):
            if not isinstance(raw_team, dict):
                raise TeamIdentityRegistryError(f"teams[{index}] must be an object")

            team_id = self._required_text(raw_team.get("team_id"), f"teams[{index}].team_id")
            canonical_name = self._required_text(
                raw_team.get("canonical_name"), f"teams[{index}].canonical_name"
            )
            gender = self._required_text(raw_team.get("gender"), f"teams[{index}].gender").casefold()
            if gender not in SUPPORTED_GENDERS:
                raise TeamIdentityRegistryError(
                    f"teams[{index}].gender must be one of {sorted(SUPPORTED_GENDERS)}"
                )
            if team_id in self._team_ids:
                raise TeamIdentityRegistryError(f"duplicate team_id: {team_id}")
            self._team_ids.add(team_id)

            aliases = raw_team.get("aliases")
            if not isinstance(aliases, list) or not aliases:
                raise TeamIdentityRegistryError(f"teams[{index}].aliases must be a non-empty list")

            for alias_index, raw_alias in enumerate(aliases):
                location = f"teams[{index}].aliases[{alias_index}]"
                if not isinstance(raw_alias, dict):
                    raise TeamIdentityRegistryError(f"{location} must be an object")
                source = self._required_text(raw_alias.get("source"), f"{location}.source").casefold()
                alias_name = self._required_text(raw_alias.get("name"), f"{location}.name")
                normalized_name = normalize_team_name(alias_name)
                if not normalized_name:
                    raise TeamIdentityRegistryError(f"{location}.name cannot be blank")

                raw_participations = raw_alias.get("participations", [])
                if not isinstance(raw_participations, list):
                    raise TeamIdentityRegistryError(f"{location}.participations must be a list")
                participations: set[tuple[str, str]] = set()
                for participation_index, participation in enumerate(raw_participations):
                    p_location = f"{location}.participations[{participation_index}]"
                    if isinstance(participation, dict):
                        competition_value = participation.get("competition_id")
                        season_value = participation.get("season")
                    elif isinstance(participation, list) and len(participation) == 2:
                        competition_value, season_value = participation
                    else:
                        raise TeamIdentityRegistryError(
                            f"{p_location} must be a [competition_id, season] pair or object"
                        )
                    competition_id = self._required_text(
                        competition_value, f"{p_location}.competition_id"
                    ).upper()
                    season = self._required_text(season_value, f"{p_location}.season")
                    pair = (competition_id, season)
                    if pair in participations:
                        raise TeamIdentityRegistryError(
                            f"duplicate participation {pair!r} for {team_id}"
                        )
                    participations.add(pair)

                identity = TeamIdentity(
                    team_id=team_id,
                    canonical_name=canonical_name,
                    gender=gender,
                    source=source,
                    matched_alias=alias_name,
                )
                key = (source, normalized_name)
                binding = _AliasBinding(
                    team=identity,
                    participations=frozenset(participations),
                )
                self._bindings.setdefault(key, []).append(binding)

    @staticmethod
    def _required_text(value: object, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise TeamIdentityRegistryError(f"{field_name} must be a non-empty string")
        return value.strip()

    @classmethod
    def from_path(cls, path: str | Path) -> "TeamIdentityRegistry":
        registry_path = Path(path)
        try:
            document = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TeamIdentityRegistryError(
                f"cannot read team registry {registry_path}: {exc}"
            ) from exc
        return cls(document)

    @classmethod
    def from_default(cls) -> "TeamIdentityRegistry":
        resource = files("kini_engine").joinpath("data").joinpath(
            "team_identity_registry.json"
        )
        try:
            with resource.open("r", encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise TeamIdentityRegistryError(
                f"cannot read packaged team registry: {exc}"
            ) from exc
        return cls(document)

    @property
    def team_count(self) -> int:
        return len(self._team_ids)

    def resolve(
        self,
        name: str,
        *,
        source: str,
        competition_id: str | None = None,
        season: str | None = None,
        gender: str | None = None,
    ) -> TeamIdentity | None:
        """Resolve one exact alias, optionally constrained by competition/season.

        None means no registered identity. Multiple exact candidates raise
        AmbiguousTeamIdentityError; callers must not pick the first result.
        Aliases are isolated by provider, so an identical string from another
        source is not accepted unless it is explicitly registered there.
        """
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must be a non-empty string")
        normalized_name = normalize_team_name(name)
        if not normalized_name:
            raise ValueError("team name cannot be blank")
        normalized_source = source.strip().casefold()

        normalized_gender: str | None = None
        if gender is not None:
            if not isinstance(gender, str) or gender.strip().casefold() not in SUPPORTED_GENDERS:
                raise ValueError(f"gender must be one of {sorted(SUPPORTED_GENDERS)}")
            normalized_gender = gender.strip().casefold()

        normalized_competition = competition_id.strip().upper() if competition_id else None
        normalized_season = season.strip() if season else None
        candidates: dict[str, TeamIdentity] = {}

        for binding in self._bindings.get((normalized_source, normalized_name), []):
            if normalized_gender is not None and binding.team.gender != normalized_gender:
                continue
            if binding.participations:
                if normalized_competition is not None and normalized_season is not None:
                    if (normalized_competition, normalized_season) not in binding.participations:
                        continue
                elif normalized_competition is not None:
                    if not any(
                        comp == normalized_competition
                        for comp, _ in binding.participations
                    ):
                        continue
                elif normalized_season is not None:
                    if not any(
                        item_season == normalized_season
                        for _, item_season in binding.participations
                    ):
                        continue
            candidates[binding.team.team_id] = binding.team

        if not candidates:
            return None
        if len(candidates) > 1:
            candidate_ids = ", ".join(sorted(candidates))
            raise AmbiguousTeamIdentityError(
                f"ambiguous team alias {name!r} from {source!r}; candidates: {candidate_ids}"
            )
        return next(iter(candidates.values()))
