"""Aggregate-only rendering for the read-only The Odds API coverage report."""

from __future__ import annotations

import collections
import json
import os
import pathlib
import typing

COUNTERS = (
    "fixtures",
    "exact",
    "h2h",
    "without_h2h",
    "unmatched",
    "kickoff_mismatch",
    "ambiguous",
    "post_kickoff",
)


def aggregate_report(report: dict[str, typing.Any]) -> dict[tuple[str, float], dict[str, int]]:
    """Aggregate rows by competition and lead horizon without retaining event detail."""
    groups: dict[tuple[str, float], dict[str, int]] = collections.defaultdict(
        lambda: dict.fromkeys(COUNTERS, 0)
    )
    rows = report.get("results", [])
    if not isinstance(rows, list):
        raise TypeError("Coverage report results must be a list")

    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Coverage report result rows must be objects")
        competition = row.get("competition_id")
        lead = row.get("requested_lead_hours")
        if not isinstance(competition, str) or not competition:
            raise ValueError("Coverage row is missing competition_id")
        if isinstance(lead, bool) or not isinstance(lead, (int, float)):
            raise TypeError("Coverage row has an invalid requested lead horizon")
        key = (competition, float(lead))
        item = groups[key]
        item["fixtures"] += 1
        item["exact"] += row.get("match_status") == "exact"
        item["h2h"] += row.get("coverage_status") == "h2h_available"
        item["without_h2h"] += row.get("coverage_status") == "event_found_without_h2h"
        item["unmatched"] += row.get("match_status") == "no_exact_match"
        item["kickoff_mismatch"] += row.get("match_status") == "kickoff_mismatch"
        item["ambiguous"] += row.get("match_status") == "ambiguous"
        item["post_kickoff"] += row.get("coverage_status") == "snapshot_not_pre_kickoff"
    return dict(groups)


def render_summary(report: dict[str, typing.Any]) -> str:
    """Return a markdown summary using aggregate counters only."""
    groups = aggregate_report(report)
    lines = [
        "# The Odds API — aggregate coverage probe",
        "",
        f"- Generated (UTC): {report.get('generated_at_utc', 'unknown')}",
        f"- Fixture/horizon checks: {report.get('fixture_probe_count', len(report.get('results', [])))}",
        f"- API requests: {report.get('api_request_count', 'unknown')}",
        f"- Maximum credit estimate: {report.get('estimated_credits_upper_bound', 'unknown')}",
        f"- Provider-reported credits: {report.get('reported_credits_last_sum', 'unknown')}",
        f"- Historical prices requested: {report.get('historical_odds_prices_requested', 'unknown')}",
        f"- Production dataset modified: {report.get('production_dataset_modified', 'unknown')}",
        f"- Eligible for model input: {report.get('eligible_for_model_input', 'unknown')}",
        "",
        "| Competition | Lead (h) | Fixtures | Exact event | h2h | Event without h2h | Unmatched | Kickoff mismatch | Ambiguous | Post-kickoff snapshot |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for (competition, lead), item in sorted(groups.items()):
        lines.append(
            f"| {competition} | {lead:g} | {item['fixtures']} | {item['exact']} | "
            f"{item['h2h']} | {item['without_h2h']} | {item['unmatched']} | "
            f"{item['kickoff_mismatch']} | {item['ambiguous']} | {item['post_kickoff']} |"
        )
    lines.extend(
        [
            "",
            (
                "Only aggregate counts are retained in this workflow summary. "
                "Raw provider responses, event IDs and bookmaker-level records are not uploaded."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    report_path = pathlib.Path("artifacts/the_odds_api_coverage.json")
    if not report_path.exists():
        print("No coverage report was produced.")
        return 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = render_summary(report)
    summary_path_value = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path_value:
        print(summary, end="")
        return 0

    summary_path = pathlib.Path(summary_path_value)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("a", encoding="utf-8") as handle:
        handle.write(summary)
    report_path.unlink(missing_ok=True)
    try:
        report_path.parent.rmdir()
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
