from scripts.diagnose_kinielagpt_details import summarize_payload


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
        ]
    }

    summary = summarize_payload(payload)
    fields = {
        field["path"]: field
        for field in summary["sample_records"][0]["candidate_fields"]
    }

    assert summary["details_record_count"] == 1
    root_fields = {
        field["path"]: field for field in summary["root_candidate_fields"]
    }
    assert root_fields["jornada"]["sample"] == 22
    assert root_fields["temporada"]["sample"] == 2027
    assert fields["idPartido"]["sample"] == 123
    assert fields["fechaHora"]["timezone_aware_iso"] is True
    assert fields["fecha"]["timezone_aware_iso"] is False
    assert fields["hora"]["timezone_aware_iso"] is False


def test_summary_does_not_claim_a_missing_details_schema_is_valid():
    summary = summarize_payload({"partidos": [{"id": 1}]})

    assert summary["details_key_present"] is False
    assert summary["details_record_count"] is None
    assert summary["sample_records"] == []
