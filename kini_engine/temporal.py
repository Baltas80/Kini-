from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


def parse_information_at(value: datetime | str, field_name: str = "information_at") -> datetime:
    """Parse an explicit information cutoff and normalize it to UTC.

    A naive timestamp is rejected because its temporal meaning is ambiguous.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            raise ValueError(f"{field_name} must not be empty")
        try:
            parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"invalid {field_name}: {value}") from exc
    else:
        raise TypeError(f"{field_name} must be a datetime or ISO-8601 string")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")

    return parsed.astimezone(timezone.utc)


def utc_iso(value: datetime) -> str:
    parsed = parse_information_at(value, "timestamp")
    return parsed.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class PredictionContext:
    """The temporal boundary under which a pre-match prediction is valid."""

    information_at: datetime
    target_kickoff_at: datetime

    def __post_init__(self) -> None:
        information_at = parse_information_at(self.information_at)
        target_kickoff_at = parse_information_at(self.target_kickoff_at, "target_kickoff_at")
        if information_at >= target_kickoff_at:
            raise ValueError(
                "information_at must be strictly before target_kickoff_at for a pre-match prediction"
            )
        object.__setattr__(self, "information_at", information_at)
        object.__setattr__(self, "target_kickoff_at", target_kickoff_at)

    @classmethod
    def from_match(
        cls,
        kickoff_at: datetime | str,
        information_at: datetime | str,
    ) -> "PredictionContext":
        return cls(
            information_at=parse_information_at(information_at),
            target_kickoff_at=parse_information_at(kickoff_at, "target_kickoff_at"),
        )

    @property
    def information_at_iso(self) -> str:
        return utc_iso(self.information_at)

    @property
    def target_kickoff_at_iso(self) -> str:
        return utc_iso(self.target_kickoff_at)

    def to_dict(self) -> dict[str, str]:
        return {
            "information_at": self.information_at_iso,
            "target_kickoff_at": self.target_kickoff_at_iso,
        }
