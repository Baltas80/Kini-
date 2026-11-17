import scripts.diagnose_kinielagpt_details as diagnostic_module
from kini_engine.sources import KinielaGPTAuthorizationRequired

from scripts.diagnose_kinielagpt_details import (
    _http_error_evidence,
    reconcile_fixture_order,
    summarize_kickoff_attachment,
    summarize_payload,
    summarize_probability_payload,
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


def test_kickoff_attachment_summary_requires_verified_identity_and_temporal_order():
    valid = {
        "id": 1,
        "fixture_identity_status": "verified",
        "kickoff_at": "2026-11-17T20:45:00+01:00",
        "kickoff_evidence_checked_at_utc": "2026-11-15T19:00:00+00:00",
        "lae_captured_at": "2026-11-15T19:30:00+00:00",
        "kickoff_evidence_url": "https://www.uefa.com/test-schedule/",
        "lae_source": "official-lae",
        "lae": {"1": 0.5, "X": 0.25, "2": 0.25},
    }
    identity_mismatch = {
        **valid,
        "id": 2,
        "fixture_identity_status": "source_name_mismatch",
    }
    evidence_after_capture = {
        **valid,
        "id": 3,
        "kickoff_evidence_checked_at_utc": "2026-11-15T19:40:00+00:00",
    }
    stale_evidence = {
        **valid,
        "id": 4,
        "kickoff_evidence_checked_at_utc": "2026-11-14T18:00:00+00:00",
    }
    invalid_vector = {
        **valid,
        "id": 5,
        "lae": {"1": 1.2, "X": 0.0, "2": 0.0},
    }

    summary = summarize_kickoff_attachment(
        [
            valid,
            identity_mismatch,
            evidence_after_capture,
            stale_evidence,
            invalid_vector,
        ],
        "official-lae",
    )

    assert summary["rows_count"] == 5
    assert summary["kickoff_mapped_count"] == 5
    assert summary["lae_source_rows_count"] == 5
    assert summary["valid_lae_vector_count"] == 4
    assert summary["temporally_eligible_lae_count"] == 1
    assert summary["fixtures"][0]["temporally_eligible_lae"] is True
    assert summary["fixtures"][0]["evidence_fresh_at_capture"] is True
    assert summary["fixtures"][0]["lae_captured_at"] == valid["lae_captured_at"]
    assert summary["fixtures"][0]["evidence_age_seconds"] == 1800
    assert summary["fixtures"][0]["minutes_until_kickoff"] == 2895
    assert summary["fixtures"][0]["eligibility_reasons"] == []
    assert summary["fixtures"][1]["eligibility_reasons"] == [
        "fixture_identity_not_verified"
    ]
    assert (
        "kickoff_evidence_stale_or_missing"
        in summary["fixtures"][3]["eligibility_reasons"]
    )
    assert summary["fixtures"][3]["evidence_fresh_at_capture"] is False
    assert all(
        fixture["temporally_eligible_lae"] is False
        for fixture in summary["fixtures"][1:]
    )


def test_probability_payload_summary_reports_expected_fields_and_valid_vectors():
    payload = {
        "quinielista": {
            "porcentajes": {
                "partido": [
                    {
                        "num": "1",
                        "local": "Local FC",
                        "visitante": "Visitante FC",
                        "porc_1": "52.5",
                        "porc_X": "26.0",
                        "porc_2": "21.5",
                    }
                ]
            }
        }
    }

    summary = summarize_probability_payload(payload)

    assert summary["record_count"] == 1
    assert summary["expected_parser_fields_present"] == {
        "num": True,
        "local": True,
        "visitante": True,
        "porc_1": True,
        "porc_X": True,
        "porc_2": True,
    }
    assert summary["parsed_match_count"] == 1
    assert summary["valid_probability_vector_count"] == 1
    assert summary["probability_field_samples"] == {
        "porc_1": ["52.5"],
        "porc_2": ["21.5"],
        "porc_X": ["26.0"],
    }


def test_probability_payload_summary_exposes_parser_schema_mismatch():
    payload = {
        "quinielista": {
            "porcentajes": {
                "partido": [
                    {
                        "num": "1",
                        "local": "Local FC",
                        "visitante": "Visitante FC",
                        "porcentaje_1": "52.5",
                        "porcentaje_x": "26.0",
                        "porcentaje_2": "21.5",
                    }
                ]
            }
        }
    }

    summary = summarize_probability_payload(payload)

    assert summary["expected_parser_fields_present"]["porc_1"] is False
    assert summary["parsed_match_count"] == 1
    assert summary["valid_probability_vector_count"] == 0
    assert summary["probability_field_samples"]["porcentaje_1"] == ["52.5"]


def test_http_error_evidence_is_bounded_and_does_not_expose_response_headers():
    class FakeResponse:
        def __init__(self):
            self.status_code = 400
            self.headers = {
                "content-type": "application/json",
                "set-cookie": "sensitive-cookie-value",
            }
            self.text = '{"error":"invalid request"} ' + ("x" * 1000)

    class FakeHTTPError(Exception):
        def __init__(self, message):
            super().__init__(message)
            self.response = FakeResponse()

    evidence = _http_error_evidence(FakeHTTPError("upstream rejected request"))

    assert evidence["http_status"] == 400
    assert evidence["response_content_type"] == "application/json"
    assert len(evidence["response_body_preview"]) == 400
    assert "sensitive-cookie-value" not in str(evidence)
    assert "set-cookie" not in evidence


def test_collect_live_diagnostic_preserves_jornada_on_http_error(monkeypatch):
    class FakeResponse:
        def __init__(self):
            self.status_code = 400
            self.headers = {"content-type": "application/json"}
            self.text = '{"error":"invalid jornada"}'

    class FakeHTTPError(Exception):
        def __init__(self, message):
            super().__init__(message)
            self.response = FakeResponse()

    class FakeSource:
        authorization = "Bearer test-token"

        def __init__(self, timeout):
            self.timeout = timeout

        def last(self):
            return 23, 2027, []

        def details_payload(self, jornada, temporada):
            raise FakeHTTPError("400 Client Error: Bad Request")

    monkeypatch.setattr(diagnostic_module, "KinielaGPTSource", FakeSource)
    report = diagnostic_module.collect_live_diagnostic()

    assert report["status"] == "error"
    assert report["jornada"] == 23
    assert report["temporada"] == 2027
    assert report["http_status"] == 400
    assert report["response_body_preview"] == '{"error":"invalid jornada"}'


def test_collect_live_diagnostic_continues_when_details_authorization_is_missing(
    monkeypatch,
):
    class FakeSource:
        authorization = None
        LAE = "https://example.com/lae/{}/{}"
        LAE_SOURCE = "test:lae"

        def __init__(self, timeout):
            self.timeout = timeout

        def last(self):
            return 23, 2027, []

        def details_payload(self, jornada, temporada):
            raise KinielaGPTAuthorizationRequired(
                "configure KINIELAGPT_AUTHORIZATION"
            )

        def _xml_snapshot(self, url):
            return {"quinielista": {"porcentajes": {"partido": []}}}, (
                "2026-11-17T00:00:00+00:00"
            )

        def probabilities(self, jornada, temporada):
            return []

    monkeypatch.setattr(diagnostic_module, "KinielaGPTSource", FakeSource)
    report = diagnostic_module.collect_live_diagnostic()

    assert report["status"] == "blocked_missing_authorization"
    assert report["authorization_configured"] is False
    assert report["jornada"] == 23
    assert report["temporada"] == 2027
    assert report["details_status"] == "blocked_missing_authorization"
    assert report["lae_probability_schema"]["record_count"] == 0
    assert report["kickoff_attachment"]["rows_count"] == 0
