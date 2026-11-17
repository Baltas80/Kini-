from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from kini_engine.prize_scoring import (
    PrizeScoringError,
    _validate_prize_distribution,
)


SNAPSHOT_PATH = (
    Path(__file__).parents[1]
    / "kini_engine"
    / "data"
    / "selae_official_coupon_results"
    / "2020-2021-19.json"
)


def _jornada_19_snapshot() -> dict[str, object]:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def test_jornada_19_official_prize_distribution_passes_strict_validation() -> None:
    validated = _validate_prize_distribution(
        _jornada_19_snapshot(),
        expected_draw_date="2020-12-06",
    )

    assert validated["revenue_eur"] == Decimal("3491465.25")
    assert validated["categories"]["pleno_al_15"]["status"] == "rollover"
    assert validated["categories"]["14"]["status"] == "rollover"
    assert validated["categories"]["13"]["winner_count"] == 37
    assert validated["categories"]["13"]["unit_prize_eur"] == Decimal("7077.29")
    assert validated["categories"]["10"]["unit_prize_eur"] == Decimal("10.06")


def test_jornada_19_prize_validation_rejects_rollover_with_winners() -> None:
    snapshot = _jornada_19_snapshot()
    pleno_tier = next(
        item
        for item in snapshot["prize_distribution"]["categories"]
        if item["category"] == "pleno_al_15"
    )
    pleno_tier["winner_count"] = 1

    with pytest.raises(PrizeScoringError, match="rollover requires zero winners"):
        _validate_prize_distribution(snapshot, expected_draw_date="2020-12-06")
