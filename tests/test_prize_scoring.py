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


def test_prize_validation_rejects_verification_before_draw_date() -> None:
    snapshot = _jornada_19_snapshot()
    snapshot["verified_at"] = "2020-12-05"

    with pytest.raises(
        PrizeScoringError,
        match="verified_at cannot precede draw_date",
    ):
        _validate_prize_distribution(snapshot, expected_draw_date="2020-12-06")


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

    with pytest.raises(
        PrizeScoringError, match="unsupported official SELAE result snapshot schema"
    ):
        _validate_prize_distribution(snapshot, expected_draw_date="2020-12-06")


def test_jornada_22_official_prize_distribution_passes_strict_validation() -> None:
    snapshot = json.loads(
        (
            Path(__file__).parents[1]
            / "kini_engine"
            / "data"
            / "selae_official_coupon_results"
            / "2020-2021-22.json"
        ).read_text(encoding="utf-8")
    )
    validated = _validate_prize_distribution(
        snapshot,
        expected_draw_date="2020-12-20",
    )

    assert validated["revenue_eur"] == Decimal("3973360.50")
    assert validated["categories"]["pleno_al_15"]["winner_count"] == 1
    assert validated["categories"]["pleno_al_15"]["unit_prize_eur"] == Decimal(
        "1677247.92"
    )
    assert validated["categories"]["14"]["winner_count"] == 3
    assert validated["categories"]["14"]["unit_prize_eur"] == Decimal("211912.56")
    assert validated["categories"]["13"]["winner_count"] == 71
    assert validated["categories"]["13"]["unit_prize_eur"] == Decimal("4197.21")
    assert validated["categories"]["12"]["winner_count"] == 970
    assert validated["categories"]["11"]["winner_count"] == 7954
    assert validated["categories"]["10"]["winner_count"] == 44645
    assert (
        validated["winner_count_diagnostics"]["pleno_vs_14_relationship"]
        == "not_assessed"
    )
    assert snapshot["prize_distribution"]["elige8"] == {
        "revenue_eur": 95926.00,
        "winner_count": 26,
        "unit_prize_eur": 2029.20,
    }
    assert Decimal("1677247.92") + Decimal("211912.56") == Decimal("1889160.48")


def test_jornada_25_official_prize_distribution_passes_strict_validation() -> None:
    snapshot = json.loads(
        (
            Path(__file__).parents[1]
            / "kini_engine"
            / "data"
            / "selae_official_coupon_results"
            / "2020-2021-25.json"
        ).read_text(encoding="utf-8")
    )
    validated = _validate_prize_distribution(
        snapshot,
        expected_draw_date="2021-01-03",
    )

    assert validated["revenue_eur"] == Decimal("2669930.25")
    assert validated["categories"]["pleno_al_15"]["winner_count"] == 1
    assert validated["categories"]["pleno_al_15"]["unit_prize_eur"] == Decimal(
        "200244.77"
    )
    assert validated["categories"]["14"]["winner_count"] == 14
    assert validated["categories"]["14"]["unit_prize_eur"] == Decimal("30513.49")
    assert validated["categories"]["13"]["winner_count"] == 275
    assert validated["categories"]["13"]["unit_prize_eur"] == Decimal("728.16")
    assert validated["categories"]["12"]["winner_count"] == 3660
    assert validated["categories"]["12"]["unit_prize_eur"] == Decimal("54.71")
    assert validated["categories"]["11"]["winner_count"] == 30768
    assert validated["categories"]["11"]["unit_prize_eur"] == Decimal("6.51")
    assert validated["categories"]["10"]["winner_count"] == 143371
    assert validated["categories"]["10"]["unit_prize_eur"] == Decimal("1.68")
    assert Decimal("200244.77") + Decimal("30513.49") == Decimal("230758.26")
    assert snapshot["prize_distribution"]["elige8"] == {
        "revenue_eur": 73222.50,
        "winner_count": 286,
        "unit_prize_eur": 140.81,
    }


def test_jornada_29_official_prize_distribution_passes_strict_validation() -> None:
    snapshot = json.loads(
        (
            Path(__file__).parents[1]
            / "kini_engine"
            / "data"
            / "selae_official_coupon_results"
            / "2020-2021-29.json"
        ).read_text(encoding="utf-8")
    )
    validated = _validate_prize_distribution(
        snapshot,
        expected_draw_date="2021-01-24",
    )

    assert validated["revenue_eur"] == Decimal("3149695.50")
    assert validated["categories"]["pleno_al_15"]["status"] == "rollover"
    assert validated["categories"]["14"]["status"] == "rollover"
    assert validated["categories"]["13"]["winner_count"] == 40
    assert validated["categories"]["13"]["unit_prize_eur"] == Decimal("5905.68")
    assert validated["categories"]["12"]["winner_count"] == 609
    assert validated["categories"]["12"]["unit_prize_eur"] == Decimal("387.89")
    assert validated["categories"]["11"]["winner_count"] == 4756
    assert validated["categories"]["11"]["unit_prize_eur"] == Decimal("49.67")
    assert validated["categories"]["10"]["winner_count"] == 25968
    assert validated["categories"]["10"]["unit_prize_eur"] == Decimal("10.92")
    assert snapshot["prize_distribution"]["elige8"] == {
        "revenue_eur": 83271.50,
        "winner_count": 66,
        "unit_prize_eur": 693.93,
    }


def test_jornada_1_2021_2022_official_prize_distribution_passes_strict_validation() -> (
    None
):
    snapshot = json.loads(
        (
            Path(__file__).parents[1]
            / "kini_engine"
            / "data"
            / "selae_official_coupon_results"
            / "2021-2022-1.json"
        ).read_text(encoding="utf-8")
    )
    validated = _validate_prize_distribution(
        snapshot,
        expected_draw_date="2021-08-15",
    )

    assert validated["revenue_eur"] == Decimal("2417637.75")
    assert validated["categories"]["pleno_al_15"]["winner_count"] == 1
    assert validated["categories"]["pleno_al_15"]["unit_prize_eur"] == Decimal(
        "479523.55"
    )
    assert validated["categories"]["14"]["winner_count"] == 16
    assert validated["categories"]["14"]["unit_prize_eur"] == Decimal("24176.38")
    assert validated["categories"]["13"]["winner_count"] == 384
    assert validated["categories"]["12"]["winner_count"] == 4507
    assert validated["categories"]["11"]["winner_count"] == 26651
    assert validated["categories"]["10"]["winner_count"] == 103695
    assert Decimal("479523.55") + Decimal("24176.38") == Decimal("503699.93")
    assert snapshot["prize_distribution"]["elige8"] == {
        "revenue_eur": 66307.50,
        "winner_count": 413,
        "unit_prize_eur": 88.30,
    }


def test_jornada_1_2022_2023_official_prize_distribution_passes_strict_validation() -> (
    None
):
    snapshot = json.loads(
        (
            Path(__file__).parents[1]
            / "kini_engine"
            / "data"
            / "selae_official_coupon_results"
            / "2022-2023-1.json"
        ).read_text(encoding="utf-8")
    )
    validated = _validate_prize_distribution(
        snapshot,
        expected_draw_date="2022-08-14",
    )

    assert validated["revenue_eur"] == Decimal("2633274.00")
    assert validated["categories"]["pleno_al_15"]["status"] == "rollover"
    assert validated["categories"]["14"]["status"] == "rollover"
    assert validated["categories"]["13"]["winner_count"] == 90
    assert validated["categories"]["13"]["unit_prize_eur"] == Decimal("2194.40")
    assert validated["categories"]["12"]["winner_count"] == 1591
    assert validated["categories"]["11"]["winner_count"] == 14042
    assert validated["categories"]["10"]["winner_count"] == 71640
    assert validated["winner_count_diagnostics"]["pleno_vs_14_relationship"] == (
        "not_assessed"
    )
    assert snapshot["prize_distribution"]["elige8"] == {
        "revenue_eur": 68687.50,
        "winner_count": 25,
        "unit_prize_eur": 1511.13,
    }


def test_prize_validation_rejects_selae_lookalike_hosts() -> None:
    snapshot = json.loads(
        (
            Path(__file__).parents[1]
            / "kini_engine"
            / "data"
            / "selae_official_coupon_results"
            / "2022-2023-1.json"
        ).read_text(encoding="utf-8")
    )
    snapshot["supporting_sources"] = [
        {
            **source,
            "url": (
                "https://www.selae.es.evil.example/forged.pdf"
                if source["role"] == "official_selae_press_release_pdf"
                else source["url"]
            ),
        }
        for source in snapshot["supporting_sources"]
    ]

    with pytest.raises(PrizeScoringError, match="official SELAE HTTPS host"):
        _validate_prize_distribution(
            snapshot,
            expected_draw_date="2022-08-14",
        )
