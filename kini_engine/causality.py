from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .temporal import parse_information_at


class CausalityViolation(ValueError):
    """Raised when data crosses the prediction information boundary."""


def assert_available_at(
    available_at: datetime | str,
    information_at: datetime | str,
    *,
    subject: str,
    strict: bool = False,
) -> None:
    """Enforce the single anti-leakage rule.

    By default, data available exactly at the cutoff is allowed.
    ``strict=True`` is used for event timestamps that must already have
    occurred before the prediction boundary.
    """
    available = parse_information_at(available_at, "available_at")
    cutoff = parse_information_at(information_at)
    valid = available < cutoff if strict else available <= cutoff
    if not valid:
        operator = "<" if strict else "<="
        raise CausalityViolation(
            f"future information blocked: {subject} has availability_at={available.isoformat()} "
            f"but requires availability_at {operator} information_at={cutoff.isoformat()}"
        )


def assert_causal_match(match: object, information_at: datetime | str) -> None:
    """Reject a historical match that cannot be known before the cutoff."""
    cutoff = parse_information_at(information_at)
    date = getattr(match, "date", None)
    if date is None:
        raise CausalityViolation("historical match has no timestamp")
    assert_available_at(date, cutoff, subject="historical match kickoff", strict=True)

    status = getattr(match, "status", None)
    if status is not None and status != "finished":
        raise CausalityViolation(
            f"historical match is not finished at the causal boundary: status={status!r}"
        )


def assert_causal_history(history: Iterable[object], information_at: datetime | str) -> None:
    """Reject the complete history if any observation crosses the cutoff."""
    cutoff = parse_information_at(information_at)
    for match in history:
        assert_causal_match(match, cutoff)
