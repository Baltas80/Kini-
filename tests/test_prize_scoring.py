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



def test_winner_count_diagnostics_keep_pleno_and_14_separate() -> None:
    validated = _validate_prize_distribution(
        _jornada_19_snapshot(),
        expected_draw_date="2020-12-06",
    )

    diagnostics = validated["winner_count_diagnostics"]
    assert diagnostics["status"] == "validated_per_category_only"
    assert diagnostics["counts_by_category"] == {
        "pleno_al_15": 0,
        "14": 0,
        "13": 37,
        "12": 569,
        "11": 5240,
        "10": 31232,
    }
    assert diagnostics["rollover_categories_have_zero_winners"] is True
    assert diagnostics["awarded_categories_have_positive_winners"] is True
    assert diagnostics["pleno_vs_14_relationship"] == "not_assessed"
    assert diagnostics["aggregate_winner_count"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [("revenue_eur", 0), ("unit_prize_eur", 0)],
)
def test_jornada_19_prize_validation_rejects_zero_elige8_amounts(
    field: str,
    value: int,
) -> None:
    snapshot = _jornada_19_snapshot()
    snapshot["prize_distribution"]["elige8"][field] = value

    with pytest.raises(
        PrizeScoringError,
        match="Elige8 prize evidence must contain positive revenue, winners and unit prize",
    ):
        _validate_prize_distribution(snapshot, expected_draw_date="2020-12-06")


def test_prize_validation_rejects_boolean_fixture_position() -> None:
    snapshot = _jornada_19_snapshot()
    snapshot["fixtures"][0]["number"] = True

    with pytest.raises(PrizeScoringError, match="ordered from 1 to 14"):
        _validate_prize_distribution(snapshot, expected_draw_date="2020-12-06")


def test_prize_validation_rejects_non_integer_schema_version() -> None:
    snapshot = _jornada_19_snapshot()
    snapshot["schema_version"] = 1.0

    with pytest.raises(PrizeScoringError, match="unsupported official SELAE result snapshot schema"):
        _validate_prize_distribution(snapshot, expected_draw_date="2020-12-06")
