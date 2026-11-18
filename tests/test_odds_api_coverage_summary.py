from scripts.summarize_odds_api_coverage import aggregate_report, render_summary


def test_aggregate_report_counts_all_statuses_without_missing_counter_keys():
    report = {
        "results": [
            {
                "competition_id": "SP1",
                "requested_lead_hours": 24,
                "match_status": "exact",
                "coverage_status": "h2h_available",
            },
            {
                "competition_id": "SP1",
                "requested_lead_hours": 24,
                "match_status": "exact",
                "coverage_status": "event_found_without_h2h",
            },
            {
                "competition_id": "SP1",
                "requested_lead_hours": 24,
                "match_status": "kickoff_mismatch",
                "coverage_status": "kickoff_mismatch",
            },
            {
                "competition_id": "SP1",
                "requested_lead_hours": 24,
                "match_status": "ambiguous",
                "coverage_status": "ambiguous_exact_event_match",
            },
            {
                "competition_id": "SP2",
                "requested_lead_hours": 1,
                "match_status": "exact",
                "coverage_status": "snapshot_not_pre_kickoff",
            },
            {
                "competition_id": "SP2",
                "requested_lead_hours": 1,
                "match_status": "no_exact_match",
                "coverage_status": "no_exact_event_match",
            },
        ]
    }

    groups = aggregate_report(report)

    assert groups[("SP1", 24.0)] == {
        "fixtures": 4,
        "exact": 2,
        "h2h": 1,
        "without_h2h": 1,
        "unmatched": 0,
        "kickoff_mismatch": 1,
        "ambiguous": 1,
        "post_kickoff": 0,
    }
    assert groups[("SP2", 1.0)] == {
        "fixtures": 2,
        "exact": 1,
        "h2h": 0,
        "without_h2h": 0,
        "unmatched": 1,
        "kickoff_mismatch": 0,
        "ambiguous": 0,
        "post_kickoff": 1,
    }


def test_render_summary_includes_all_aggregate_columns():
    report = {
        "generated_at_utc": "2026-11-18T10:00:00Z",
        "fixture_probe_count": 2,
        "api_request_count": 3,
        "estimated_credits_upper_bound": 3,
        "reported_credits_last_sum": 3,
        "historical_odds_prices_requested": False,
        "production_dataset_modified": False,
        "eligible_for_model_input": False,
        "results": [
            {
                "competition_id": "SP1",
                "requested_lead_hours": 6,
                "match_status": "kickoff_mismatch",
                "coverage_status": "kickoff_mismatch",
            },
            {
                "competition_id": "SP1",
                "requested_lead_hours": 6,
                "match_status": "exact",
                "coverage_status": "snapshot_not_pre_kickoff",
            },
        ],
    }

    summary = render_summary(report)

    assert "| SP1 | 6 | 2 | 1 | 0 | 0 | 0 | 1 | 0 | 1 |" in summary
    assert (
        "Raw provider responses, event IDs and bookmaker-level records are not uploaded."
        in summary
    )
