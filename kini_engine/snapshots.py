from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .causality import CausalityViolation, assert_available_at
from .temporal import parse_information_at, utc_iso


@dataclass(frozen=True)
class SnapshotObservation:
    """A source observation frozen for one point-in-time snapshot."""

    observation_id: str
    match_id: str
    source_id: str
    source_record_id: str
    captured_at: datetime
    payload_hash: str
    payload: dict[str, Any]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SnapshotObservation":
        required = (
            "observation_id",
            "match_id",
            "source_id",
            "source_record_id",
            "captured_at",
            "payload_hash",
            "payload",
        )
        missing = [field for field in required if field not in value]
        if missing:
            raise ValueError(f"observation missing required fields: {', '.join(missing)}")

        identifiers = ("observation_id", "match_id", "source_id", "source_record_id", "payload_hash")
        for field in identifiers:
            if not isinstance(value[field], str) or not value[field]:
                raise ValueError(f"observation {field} must be a non-empty string")
        if not isinstance(value["payload"], dict):
            raise ValueError("observation payload must be an object")

        captured_at = parse_information_at(value["captured_at"], "captured_at")
        return cls(
            observation_id=value["observation_id"],
            match_id=value["match_id"],
            source_id=value["source_id"],
            source_record_id=value["source_record_id"],
            captured_at=captured_at,
            payload=dict(value["payload"]),
            payload_hash=value["payload_hash"],
        )

    def identity_key(self) -> tuple[str, str]:
        return self.source_id, self.match_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "match_id": self.match_id,
            "source_id": self.source_id,
            "source_record_id": self.source_record_id,
            "captured_at": utc_iso(self.captured_at),
            "payload_hash": self.payload_hash,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class TemporalSnapshot:
    """Deterministic point-in-time view of source observations."""

    information_at: datetime
    observations: tuple[SnapshotObservation, ...]
    snapshot_id: str

    def __post_init__(self) -> None:
        information_at = parse_information_at(self.information_at)
        ordered = tuple(
            sorted(
                self.observations,
                key=lambda observation: (
                    observation.source_id,
                    observation.match_id,
                    observation.captured_at,
                    observation.observation_id,
                ),
            )
        )
        if any(observation.captured_at > information_at for observation in ordered):
            raise ValueError("snapshot contains an observation after information_at")
        expected_id = snapshot_id_for(information_at, ordered)
        if self.snapshot_id != expected_id:
            raise ValueError("snapshot_id does not match snapshot contents")
        object.__setattr__(self, "information_at", information_at)
        object.__setattr__(self, "observations", ordered)

    @property
    def observation_count(self) -> int:
        return len(self.observations)

    def for_match(self, match_id: str, source_id: str | None = None) -> tuple[SnapshotObservation, ...]:
        return tuple(
            observation
            for observation in self.observations
            if observation.match_id == match_id
            and (source_id is None or observation.source_id == source_id)
        )

    def by_match(self) -> dict[str, tuple[SnapshotObservation, ...]]:
        result: dict[str, list[SnapshotObservation]] = {}
        for observation in self.observations:
            result.setdefault(observation.match_id, []).append(observation)
        return {match_id: tuple(items) for match_id, items in result.items()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "information_at": utc_iso(self.information_at),
            "observation_count": self.observation_count,
            "observations": [observation.to_dict() for observation in self.observations],
        }


def snapshot_id_for(
    information_at: datetime | str,
    observations: Iterable[SnapshotObservation],
) -> str:
    cutoff = parse_information_at(information_at)
    canonical_observations = [
        observation.to_dict()
        for observation in sorted(
            observations,
            key=lambda item: (
                item.source_id,
                item.match_id,
                item.captured_at,
                item.observation_id,
            ),
        )
    ]
    encoded = json.dumps(
        {
            "information_at": utc_iso(cutoff),
            "observations": canonical_observations,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def select_latest_observations(
    observations: Iterable[SnapshotObservation],
    *,
    information_at: datetime | str,
) -> tuple[SnapshotObservation, ...]:
    cutoff = parse_information_at(information_at)
    selected: dict[tuple[str, str], SnapshotObservation] = {}
    timestamps: set[tuple[str, str, datetime]] = set()

    for observation in observations:
        try:
            assert_available_at(
                observation.captured_at,
                cutoff,
                subject=f"observation {observation.observation_id}",
            )
        except CausalityViolation:
            continue
        key = observation.identity_key()
        timestamp_key = (*key, observation.captured_at)
        if timestamp_key in timestamps:
            raise ValueError(
                "multiple observations share the same source, match and captured_at: "
                f"{observation.source_id}/{observation.match_id}/{utc_iso(observation.captured_at)}"
            )
        timestamps.add(timestamp_key)

        previous = selected.get(key)
        if previous is None or observation.captured_at > previous.captured_at:
            selected[key] = observation

    return tuple(
        sorted(
            selected.values(),
            key=lambda observation: (
                observation.source_id,
                observation.match_id,
                observation.captured_at,
                observation.observation_id,
            ),
        )
    )


def build_snapshot(
    observations: Iterable[SnapshotObservation],
    *,
    information_at: datetime | str,
) -> TemporalSnapshot:
    cutoff = parse_information_at(information_at)
    selected = select_latest_observations(observations, information_at=cutoff)
    return TemporalSnapshot(
        information_at=cutoff,
        observations=selected,
        snapshot_id=snapshot_id_for(cutoff, selected),
    )


def load_observations_jsonl(path: Path) -> list[SnapshotObservation]:
    observations: list[SnapshotObservation] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at line {line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"observation at line {line_number} must be an object")
            observations.append(SnapshotObservation.from_dict(value))
    return observations
