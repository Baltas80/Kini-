from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from .team_identity import normalize_team_name

SELAE_HOSTS = {"loteriasyapuestas.es", "www.loteriasyapuestas.es"}
PRIZE_CATEGORIES = ("pleno_al_15", "14", "13", "12", "11", "10")
CENT = Decimal("0.01")


class PrizeScoringError(ValueError):
    """Raised when official SELAE prize evidence is incomplete or inconsistent."""


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PrizeScoringError(f"{field} must be a non-empty string")
    return value.strip()


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PrizeScoringError(f"{field} must be a non-negative integer")
    return value


def _money(value: object, field: str, *, allow_none: bool = False) -> Decimal | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise PrizeScoringError(f"{field} must be a non-negative EUR amount")
    try:
        amount = Decimal(str(value))
        rounded = amount.quantize(CENT)
    except InvalidOperation as exc:
        raise PrizeScoringError(f"{field} must be a valid EUR amount") from exc
    if not amount.is_finite() or amount < 0 or amount != rounded:
        raise PrizeScoringError(
            f"{field} must be a non-negative amount with at most two decimals"
        )
    return rounded


def _https_url(value: object, field: str, *, pdf: bool = False) -> str:
    raw = _required_text(value, field)
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise PrizeScoringError(f"{field} must be a valid HTTPS URL") from exc
    if (
        parsed.scheme != "https"
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise PrizeScoringError(f"{field} must use HTTPS without embedded credentials")
    if pdf and not parsed.path.lower().endswith(".pdf"):
        raise PrizeScoringError(f"{field} must point to a PDF")
    return raw


def _official_url(value: object, field: str, *, pdf: bool = False) -> str:
    raw = _https_url(value, field, pdf=pdf)
    if urlsplit(raw).hostname not in SELAE_HOSTS:
        raise PrizeScoringError(f"{field} must use an official SELAE HTTPS host")
    return raw


def _category(goals: int) -> str:
    return str(goals) if goals <= 2 else "M"


def _same_team(left: object, right: object, field: str) -> None:
    left_name = _required_text(left, f"{field} source")
    right_name = _required_text(right, f"{field} ticket")
    if normalize_team_name(left_name) != normalize_team_name(right_name):
        raise PrizeScoringError(f"{field} does not match the stored coupon plan")


def _validate_prize_distribution(
    snapshot: dict[str, Any],
    *,
    expected_draw_date: str,
) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise PrizeScoringError("official SELAE result snapshot must be an object")
    version = snapshot.get("schema_version")
    if type(version) is not int or version != 1:
        raise PrizeScoringError("unsupported official SELAE result snapshot schema")
    if snapshot.get("source") != "SELAE":
        raise PrizeScoringError("official result snapshot provider must be SELAE")
    try:
        draw_date = date.fromisoformat(
            _required_text(snapshot.get("draw_date"), "draw_date")
        ).isoformat()
        date.fromisoformat(_required_text(snapshot.get("verified_at"), "verified_at"))
    except ValueError as exc:
        raise PrizeScoringError(
            "snapshot draw_date and verified_at must be ISO dates"
        ) from exc
    if draw_date != expected_draw_date:
        raise PrizeScoringError(
            "official result snapshot draw date does not match ticket"
        )
    if snapshot.get("snapshot_type") != "normalized_json_extract_not_raw_html":
        raise PrizeScoringError("unsupported SELAE snapshot evidence type")
    _required_text(snapshot.get("verification_method"), "verification_method")
    result_url = _official_url(snapshot.get("source_url"), "source_url")

    sources = snapshot.get("supporting_sources")
    if not isinstance(sources, list) or any(
        not isinstance(item, dict) for item in sources
    ):
        raise PrizeScoringError("supporting_sources must be a list of source objects")
    source_urls: dict[str, str] = {}
    for item in sources:
        role = _required_text(item.get("role"), "supporting source role")
        if role in {
            "official_selae_result_page",
            "official_selae_press_release_pdf",
        }:
            url = _official_url(
                item.get("url"),
                f"supporting_sources.{role}",
                pdf=role == "official_selae_press_release_pdf",
            )
        else:
            url = _https_url(item.get("url"), f"supporting_sources.{role}")
        if role in source_urls:
            raise PrizeScoringError(f"duplicate supporting source role {role!r}")
        source_urls[role] = url
    if source_urls.get("official_selae_result_page") != result_url:
        raise PrizeScoringError(
            "official result page is not bound to supporting-source evidence"
        )

    fixtures = snapshot.get("fixtures")
    if not isinstance(fixtures, list) or len(fixtures) != 14:
        raise PrizeScoringError(
            "official result snapshot must contain exactly 14 main fixtures"
        )
    for position, fixture in enumerate(fixtures, start=1):
        if not isinstance(fixture, dict) or set(fixture) != {
            "number",
            "home",
            "away",
            "home_goals",
            "away_goals",
            "result",
        }:
            raise PrizeScoringError(
                f"official fixture {position} has an invalid schema"
            )
        if type(fixture.get("number")) is not int or fixture["number"] != position:
            raise PrizeScoringError("official fixtures must be ordered from 1 to 14")
        _required_text(fixture.get("home"), f"fixture {position} home")
        _required_text(fixture.get("away"), f"fixture {position} away")
        home_goals = _nonnegative_int(
            fixture.get("home_goals"), f"fixture {position} home_goals"
        )
        away_goals = _nonnegative_int(
            fixture.get("away_goals"), f"fixture {position} away_goals"
        )
        expected_sign = (
            "1" if home_goals > away_goals else "2" if away_goals > home_goals else "X"
        )
        if fixture.get("result") != expected_sign:
            raise PrizeScoringError(
                f"official fixture {position} result conflicts with its score"
            )

    pleno = snapshot.get("pleno")
    if not isinstance(pleno, dict) or set(pleno) != {
        "number",
        "home",
        "away",
        "home_goals",
        "away_goals",
        "home_category",
        "away_category",
    }:
        raise PrizeScoringError("official Pleno al 15 snapshot has an invalid schema")
    if type(pleno.get("number")) is not int or pleno["number"] != 15:
        raise PrizeScoringError("official Pleno al 15 fixture number must be 15")
    _required_text(pleno.get("home"), "Pleno home")
    _required_text(pleno.get("away"), "Pleno away")
    pleno_home_goals = _nonnegative_int(pleno.get("home_goals"), "Pleno home_goals")
    pleno_away_goals = _nonnegative_int(pleno.get("away_goals"), "Pleno away_goals")
    if pleno.get("home_category") != _category(pleno_home_goals) or pleno.get(
        "away_category"
    ) != _category(pleno_away_goals):
        raise PrizeScoringError("Pleno categories conflict with official goal counts")

    distribution = snapshot.get("prize_distribution")
    if not isinstance(distribution, dict):
        raise PrizeScoringError("official prize_distribution is missing")
    allowed_distribution_fields = {
        frozenset({"source_type", "source_url", "revenue_eur", "categories"}),
        frozenset({"source_type", "source_url", "revenue_eur", "categories", "elige8"}),
    }
    if frozenset(distribution) not in allowed_distribution_fields:
        raise PrizeScoringError("official prize_distribution has an invalid schema")
    expected_source_type = (
        "official_selae_press_release_pdf_transcribed_to_normalized_extract"
    )
    if distribution.get("source_type") != expected_source_type:
        raise PrizeScoringError("unsupported prize-distribution source type")
    prize_url = _official_url(
        distribution.get("source_url"),
        "prize_distribution.source_url",
        pdf=True,
    )
    if source_urls.get("official_selae_press_release_pdf") != prize_url:
        raise PrizeScoringError(
            "prize PDF URL is not bound to supporting-source evidence"
        )
    revenue = _money(distribution.get("revenue_eur"), "prize_distribution.revenue_eur")
    if revenue is None or revenue <= 0:
        raise PrizeScoringError("prize-distribution revenue must be positive")

    raw_categories = distribution.get("categories")
    if not isinstance(raw_categories, list) or len(raw_categories) != len(
        PRIZE_CATEGORIES
    ):
        raise PrizeScoringError(
            "prize distribution must contain all six Quiniela categories"
        )
    categories: dict[str, dict[str, Any]] = {}
    for item in raw_categories:
        if not isinstance(item, dict) or set(item) != {
            "category",
            "winner_count",
            "unit_prize_eur",
            "status",
        }:
            raise PrizeScoringError("prize category has an invalid schema")
        name = _required_text(item.get("category"), "prize category")
        if name not in PRIZE_CATEGORIES or name in categories:
            raise PrizeScoringError(f"unknown or duplicate prize category {name!r}")
        winners = _nonnegative_int(item.get("winner_count"), f"{name}.winner_count")
        status = item.get("status")
        unit_prize = _money(
            item.get("unit_prize_eur"),
            f"{name}.unit_prize_eur",
            allow_none=True,
        )
        if status == "rollover":
            if winners != 0 or unit_prize is not None:
                raise PrizeScoringError(
                    f"{name}: rollover requires zero winners and a null unit prize"
                )
        elif status == "awarded":
            if winners == 0 or unit_prize is None:
                raise PrizeScoringError(
                    f"{name}: awarded requires winners and a published unit prize"
                )
        else:
            raise PrizeScoringError(f"{name}: unsupported prize status")
        categories[name] = {
            "winner_count": winners,
            "unit_prize_eur": unit_prize,
            "status": status,
        }
    if set(categories) != set(PRIZE_CATEGORIES):
        raise PrizeScoringError("prize distribution is missing a required category")

    # Keep official counts separate by category. In particular, do not infer
    # whether SELAE includes Pleno al 15 winners in the published 14 category.
    winner_count_diagnostics = {
        "status": "validated_per_category_only",
        "counts_by_category": {
            name: categories[name]["winner_count"] for name in PRIZE_CATEGORIES
        },
        "rollover_categories_have_zero_winners": all(
            item["winner_count"] == 0
            for item in categories.values()
            if item["status"] == "rollover"
        ),
        "awarded_categories_have_positive_winners": all(
            item["winner_count"] > 0
            for item in categories.values()
            if item["status"] == "awarded"
        ),
        "pleno_vs_14_relationship": "not_assessed",
        "aggregate_winner_count": None,
        "interpretation_note": (
            "Counts are retained independently by published category. The source "
            "does not establish whether Pleno al 15 winners are included in or "
            "excluded from the 14 category; no overlap or aggregate is inferred."
        ),
    }

    if "elige8" in distribution:
        elige8 = distribution["elige8"]
        if not isinstance(elige8, dict) or set(elige8) != {
            "revenue_eur",
            "winner_count",
            "unit_prize_eur",
        }:
            raise PrizeScoringError("Elige8 prize evidence has an invalid schema")
        elige8_revenue = _money(elige8.get("revenue_eur"), "elige8.revenue_eur")
        elige8_winners = _nonnegative_int(
            elige8.get("winner_count"), "elige8.winner_count"
        )
        elige8_prize = _money(elige8.get("unit_prize_eur"), "elige8.unit_prize_eur")
        if (
            elige8_revenue is None
            or elige8_revenue <= 0
            or elige8_prize is None
            or elige8_prize <= 0
            or elige8_winners < 1
        ):
            raise PrizeScoringError(
                "Elige8 prize evidence must contain positive revenue, winners and unit prize"
            )

    return {
        "draw_date": draw_date,
        "result_url": result_url,
        "prize_pdf_url": prize_url,
        "revenue_eur": revenue,
        "categories": categories,
        "winner_count_diagnostics": winner_count_diagnostics,
        "fixtures": fixtures,
        "pleno": pleno,
    }


def evaluate_official_prize_snapshot(
    snapshot: dict[str, Any],
    *,
    snapshot_sha256: str,
    expected_draw_date: str,
    expected_main_results: Sequence[str],
    expected_fixtures: Sequence[dict[str, Any]],
    expected_pleno_home: str,
    expected_pleno_away: str,
    validated_pleno15: dict[str, Any],
    columns: Sequence[Sequence[str]],
    pleno15_combinations: Sequence[dict[str, str]],
) -> dict[str, Any]:
    """Classify direct bets and attach a conditional reference to official unit prizes.

    This is not an actual payout or counterfactual ROI calculation. It assumes the
    stored bets were included in SELAE's published winner counts; no sales receipt
    is verified and adding hypothetical bets would change prize-sharing counts.
    """
    if (
        not isinstance(snapshot_sha256, str)
        or len(snapshot_sha256) != 64
        or any(character not in "0123456789abcdef" for character in snapshot_sha256)
    ):
        raise PrizeScoringError("snapshot_sha256 must be a lowercase SHA-256 digest")
    if len(expected_main_results) != 14 or len(expected_fixtures) != 14:
        raise PrizeScoringError(
            "ticket must provide 14 expected main fixtures and results"
        )

    validated = _validate_prize_distribution(
        snapshot, expected_draw_date=expected_draw_date
    )
    for position, (fixture, expected, plan_fixture) in enumerate(
        zip(
            validated["fixtures"],
            expected_main_results,
            expected_fixtures,
            strict=True,
        ),
        start=1,
    ):
        if fixture["result"] != expected:
            raise PrizeScoringError(
                f"official fixture {position} result conflicts with reconciliation"
            )
        if (
            not isinstance(plan_fixture, dict)
            or plan_fixture.get("position") != position
        ):
            raise PrizeScoringError(f"ticket coupon plan fixture {position} is invalid")
        _same_team(
            fixture["home"], plan_fixture.get("home"), f"fixture {position} home"
        )
        _same_team(
            fixture["away"], plan_fixture.get("away"), f"fixture {position} away"
        )

    pleno = validated["pleno"]
    _same_team(pleno["home"], expected_pleno_home, "Pleno home")
    _same_team(pleno["away"], expected_pleno_away, "Pleno away")
    actual_pair = (
        validated_pleno15.get("home_category"),
        validated_pleno15.get("away_category"),
    )
    snapshot_pair = (pleno["home_category"], pleno["away_category"])
    if actual_pair != snapshot_pair:
        raise PrizeScoringError(
            "official Pleno categories conflict with the Pleno result report"
        )
    if validated_pleno15.get("home_goals") is not None and (
        validated_pleno15.get("home_goals") != pleno["home_goals"]
        or validated_pleno15.get("away_goals") != pleno["away_goals"]
    ):
        raise PrizeScoringError(
            "official Pleno goals conflict with the Pleno result report"
        )

    tier_counts = {name: 0 for name in PRIZE_CATEGORIES}
    for column in columns:
        if len(column) != 14:
            raise PrizeScoringError("each direct column must contain 14 signs")
        hits = sum(
            sign == expected_main_results[index] for index, sign in enumerate(column)
        )
        for pair in pleno15_combinations:
            if hits >= 10:
                tier_counts[str(hits)] += 1
            if (
                hits == 14
                and (
                    pair.get("home_goals"),
                    pair.get("away_goals"),
                )
                == actual_pair
            ):
                tier_counts["pleno_al_15"] += 1

    total_bets = len(columns) * len(pleno15_combinations)
    main_tier_bets = sum(tier_counts[name] for name in ("14", "13", "12", "11", "10"))
    if (
        total_bets < 1
        or main_tier_bets > total_bets
        or tier_counts["pleno_al_15"] > tier_counts["14"]
    ):
        raise PrizeScoringError(
            "prize tier counts exceed the expanded direct-bet count"
        )

    tier_details: dict[str, dict[str, Any]] = {}
    reference_total = Decimal("0.00")
    reference_complete = True
    for name in PRIZE_CATEGORIES:
        evidence = validated["categories"][name]
        qualifying = tier_counts[name]
        unit_prize = evidence["unit_prize_eur"]
        conditional_reference = None
        if qualifying:
            if unit_prize is None:
                reference_complete = False
            else:
                conditional_reference = (unit_prize * qualifying).quantize(CENT)
                reference_total += conditional_reference
        tier_details[name] = {
            "qualifying_ticket_bets": qualifying,
            "official_winner_count": evidence["winner_count"],
            "official_status": evidence["status"],
            "published_unit_prize_eur": (
                f"{unit_prize:.2f}" if unit_prize is not None else None
            ),
            "conditional_reference_eur": (
                f"{conditional_reference:.2f}"
                if conditional_reference is not None
                else None
            ),
        }

    return {
        "prize_tiers_evaluated": True,
        "official_result_snapshot_sha256": snapshot_sha256,
        "prize_distribution_source_url": validated["prize_pdf_url"],
        "prize_distribution_revenue_eur": f"{validated['revenue_eur']:.2f}",
        "prize_tier_counts": tier_counts,
        "prize_tier_details": tier_details,
        "official_winner_count_diagnostics": validated["winner_count_diagnostics"],
        "conditional_published_prize_reference_eur": (
            f"{reference_total:.2f}" if reference_complete else None
        ),
        "conditional_prize_reference_complete": reference_complete,
        "conditional_prize_reference_basis": (
            "Published unit prizes are multiplied by qualifying ticket bets. "
            "This is conditional on the stored bets being included in SELAE's "
            "official winner counts; it is not an actual payout or a counterfactual "
            "estimate for an unsubmitted model-generated ticket."
        ),
        "payout_evaluated": False,
        "profitability_evaluated": False,
    }
