from scripts.diagnose_kinielagpt_details import (
    reconcile_fixture_order,
    summarize_payload,
)


def test_summary_distinguishes_timezone_aware_kickoff_from_local_date_and_time():
    payload = {
        "jornada": 22,
        "temporada": 2027,
        "detallePartidos": [
            {
                "idPartido": 123,
                "fechaHora": "2026-11-21T20:00:00+01:00",
                "fecha": "2026-11-21",
                "hora": "20:00",
                "dia": "21/11/2026",
                "orden": 1,
                "equipos": {"local": "Local FC", "visitante": "Visitante FC"},
            }
        ],
    }

    summary = summarize_payload(payload)
    fields = {
        field["path"]: field
        for field in summary["sample_records"][0]["candidate_fields"]
    }

    assert summary["details_record_count"] == 1
    root_fields = {field["path"]: field for field in summary["root_candidate_fields"]}
    assert root_fields["jornada"]["sample"] == 22
    assert root_fields["temporada"]["sample"] == 2027
    assert fields["idPartido"]["sample"] == 123
    assert fields["fechaHora"]["timezone_aware_iso"] is True
    assert fields["fecha"]["timezone_aware_iso"] is False
    assert fields["hora"]["timezone_aware_iso"] is False
    assert fields["dia"]["timezone_aware_iso"] is False


def test_summary_does_not_claim_a_missing_details_schema_is_valid():
    summary = summarize_payload({"partidos": [{"id": 1}]})

    assert summary["details_key_present"] is False
    assert summary["details_record_count"] is None
    assert summary["sample_records"] == []


def test_fixture_order_crosswalk_requires_exact_normalized_names_and_bijection():
    details = [
        {
            "orden": 1,
            "local": "BOSNÍA-HERZEGOVINA",
            "visitante": "Rumanía",
            "dia": "MAR",
            "hora": "20:45",
        },
        {"orden": 2, "local": "Francia", "visitante": "Alemania"},
    ]
    percentage_matches = [
        {"id": 1, "home": "Bosnia Herzegovina", "away": "Rumania"},
        {"id": 2, "home": "FRANCIA", "away": "Alemania"},
    ]

    report = reconcile_fixture_order(details, percentage_matches)

    assert report["status"] == "verified"
    assert report["verified_count"] == 2
    assert report["order_equals_percentage_num_for_all"] is True
    assert [item["matched_num"] for item in report["mapping"]] == [1, 2]
    assert report["unmatched_percentage_ids"] == []
    assert report["mapping"][0]["provider_day_label"] == "MAR"
    assert report["mapping"][0]["provider_clock_time"] == "20:45"
    assert report["mapping"][0]["timezone_aware_candidate_fields"] == []


def test_fixture_order_crosswalk_rejects_order_when_names_point_to_another_num():
    details = [{"orden": 1, "local": "Equipo B", "visitante": "Equipo A"}]
    percentage_matches = [
        {"id": 1, "home": "Equipo A", "away": "Equipo B"},
        {"id": 2, "home": "Equipo B", "away": "Equipo A"},
    ]

    report = reconcile_fixture_order(details, percentage_matches)

    assert report["status"] == "not_verified"
    assert report["mapping"][0]["name_match_count"] == 1
    assert report["mapping"][0]["matched_num"] == 2
    assert report["mapping"][0]["order_matches_num"] is False
    assert "order_does_not_match_percentage_num" in report["reasons"]


def test_fixture_order_crosswalk_rejects_ambiguous_duplicate_name_pairs():
    details = [{"orden": 1, "local": "Equipo A", "visitante": "Equipo B"}]
    percentage_matches = [
        {"id": 1, "home": "Equipo A", "away": "Equipo B"},
        {"id": 2, "home": "Equipo A", "away": "Equipo B"},
    ]

    report = reconcile_fixture_order(details, percentage_matches)

    assert report["status"] == "not_verified"
    assert report["mapping"][0]["name_match_count"] == 2
    assert "home_away_name_pair_not_unique_or_unmatched" in report["reasons"]


def test_fixture_crosswalk_exposes_timezone_aware_kickoff_candidates_without_inference():
    details = [
        {
            "orden": 1,
            "local": "Equipo A",
            "visitante": "Equipo B",
            "dia": "MAR",
            "hora": "20:45",
            "fechaHora": "2026-11-17T20:45:00+01:00",
        }
    ]
    percentage_matches = [{"id": 1, "home": "Equipo A", "away": "Equipo B"}]

    report = reconcile_fixture_order(details, percentage_matches)

    assert report["status"] == "verified"
    assert report["mapping"][0]["provider_day_label"] == "MAR"
    assert report["mapping"][0]["provider_clock_time"] == "20:45"
    assert report["mapping"][0]["timezone_aware_candidate_fields"] == ["fechaHora"]
