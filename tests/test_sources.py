import json
from datetime import UTC, datetime

import pytest

import kini_engine.mcp_server as mcp_server
import kini_engine.sources as source_module
from kini_engine.core import SIGNS
from kini_engine.sources import (
    KinielaGPTAuthorizationRequired,
    KinielaGPTSource,
)


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses

    def get(self, url: str, **kwargs):
        for marker, content in self.responses.items():
            if marker in url:
                return FakeResponse(content)
        raise AssertionError(f"Unexpected URL: {url}")


def xml_fixture(home: str, away: str, values: tuple[int, int, int]) -> bytes:
    return (
        "<quinielista><porcentajes><partido>"
        "<num>1</num>"
        f"<local>{home}</local><visitante>{away}</visitante>"
        f"<porc_1>{values[0]}</porc_1>"
        f"<porc_X>{values[1]}</porc_X>"
        f"<porc_2>{values[2]}</porc_2>"
        "</partido></porcentajes></quinielista>"
    ).encode()


def test_probabilities_preserve_separate_source_vectors_and_capture_times(monkeypatch):
    fixed = datetime(2026, 11, 15, 16, 0, tzinfo=UTC)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(source_module, "datetime", FrozenDateTime)
    source = KinielaGPTSource()
    source.session = FakeSession(
        {
            "porcentajes_lae.asp": xml_fixture("Local", "Visitante", (60, 20, 20)),
            "porcentajes.asp?": xml_fixture("Local", "Visitante", (20, 30, 50)),
        }
    )

    rows = source.probabilities(12, 2026)

    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == 1
    assert row["lae"] == pytest.approx({"1": 0.6, "X": 0.2, "2": 0.2})
    assert row["quinielista"] == pytest.approx({"1": 0.2, "X": 0.3, "2": 0.5})
    assert {sign: row[sign] for sign in SIGNS} == pytest.approx(
        {"1": 0.4, "X": 0.25, "2": 0.35}
    )
    assert row["lae_source"] == KinielaGPTSource.LAE_SOURCE
    assert row["quinielista_source"] == KinielaGPTSource.QUINIELISTA_SOURCE
    assert row["lae_captured_at"] == "2026-11-15T16:00:00+00:00"
    assert row["quinielista_captured_at"] == "2026-11-15T16:00:00+00:00"
    assert row["probability_method"] == "equal_weight_mean_of_available_source_vectors"


def test_invalid_source_vector_is_not_normalized_or_used_in_blended_output(monkeypatch):
    fixed = datetime(2026, 11, 15, 16, 0, tzinfo=UTC)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(source_module, "datetime", FrozenDateTime)
    source = KinielaGPTSource()
    source.session = FakeSession(
        {
            "porcentajes_lae.asp": xml_fixture("Local", "Visitante", (0, 0, 0)),
            "porcentajes.asp?": xml_fixture("Local", "Visitante", (20, 30, 50)),
        }
    )

    row = source.probabilities(12, 2026)[0]

    assert row["lae"] is None
    assert row["lae_source"] == KinielaGPTSource.LAE_SOURCE
    assert row["lae_captured_at"] == "2026-11-15T16:00:00+00:00"
    assert row["quinielista"] == pytest.approx({"1": 0.2, "X": 0.3, "2": 0.5})
    assert {sign: row[sign] for sign in SIGNS} == pytest.approx(
        {"1": 0.2, "X": 0.3, "2": 0.5}
    )


class FakeJsonResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeDetailsSession:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.home_call = None
        self.details_call = None

    def get(self, url: str, **kwargs):
        if url == KinielaGPTSource.HOME:
            self.home_call = kwargs
            return FakeResponse(b"home")
        if url == KinielaGPTSource.DETAILS:
            self.details_call = kwargs
            return FakeJsonResponse(self.payload)
        raise AssertionError(f"Unexpected URL: {url}")


def test_details_payload_preserves_provider_schema_and_receipt_timestamp(monkeypatch):
    fixed = datetime(2026, 11, 15, 18, 0, tzinfo=UTC)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(source_module, "datetime", FrozenDateTime)
    payload = {
        "detallePartidos": [
            {
                "idPartido": 123,
                "fechaHora": "2026-11-21T20:00:00+01:00",
            }
        ],
        "metadata": {"season": 2026},
    }
    source = KinielaGPTSource(authorization="Bearer test-token")
    fake_session = FakeDetailsSession(payload)
    source.session = fake_session

    actual, captured_at = source.details_payload(12, 2026)

    assert actual == payload
    assert captured_at == "2026-11-15T18:00:00+00:00"
    assert fake_session.details_call["params"]["jornada"] == 12
    assert fake_session.details_call["params"]["temporada"] == 2026
    assert "uts" in fake_session.details_call["params"]
    assert fake_session.home_call["headers"] == KinielaGPTSource.DETAILS_HOME_HEADERS
    assert fake_session.details_call["headers"] == {
        **KinielaGPTSource.DETAILS_REQUEST_HEADERS,
        "Authorization": "Bearer test-token",
    }
    assert fake_session.details_call["headers"]["origin"] == (
        "https://www.eduardolosilla.es"
    )
    assert fake_session.details_call["headers"]["referer"] == (
        "https://www.eduardolosilla.es/"
    )


def test_details_returns_provider_records_without_changing_the_schema():
    payload = {"detallePartidos": [{"idPartido": 123, "hora": "20:00"}]}
    source = KinielaGPTSource(authorization="Bearer test-token")
    source.session = FakeDetailsSession(payload)

    assert source.details(12, 2026) == payload["detallePartidos"]


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"metadata": {}}, ValueError),
        ({"detallePartidos": {"idPartido": 123}}, TypeError),
        ({"detallePartidos": [None]}, TypeError),
    ],
)
def test_details_rejects_unknown_or_malformed_provider_schema(payload, error):
    source = KinielaGPTSource(authorization="Bearer test-token")
    source.session = FakeDetailsSession(payload)

    with pytest.raises(error, match="KinielaGPT"):
        source.details(12, 2026)


def _kickoff_crosswalk_payload(
    *, schedule_checked_at: str = "2026-11-15T19:00:00Z"
) -> dict:
    return {
        "schema_version": 1,
        "jornada": 12,
        "temporada": 2026,
        "timezone": "CET",
        "crosswalk_evidence": {
            "status": "verified",
            "details_count": 1,
            "percentage_matches_count": 1,
            "verified_count": 1,
            "checked_at_utc": "2026-11-15T18:00:00Z",
        },
        "schedule_evidence_checked_at_utc": schedule_checked_at,
        "schedule_sources": [
            {
                "id": "official",
                "competition": "UEFA test schedule",
                "url": "https://www.uefa.com/test-schedule/",
                "published_date": "2026-11-15",
                "timezone": "CET",
            }
        ],
        "fixtures": [
            {
                "num": 1,
                "home_provider_name": "Local",
                "away_provider_name": "Visitante",
                "provider_day_label": "MAR",
                "provider_clock_time": "20:45",
                "kickoff_at": "2026-11-17T20:45:00+01:00",
                "schedule_source_id": "official",
            }
        ],
    }


def _freeze_source_clock(monkeypatch, fixed: datetime) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(source_module, "datetime", FrozenDateTime)


def test_probabilities_attach_official_kickoff_after_verified_identity_and_evidence(
    monkeypatch, tmp_path
):
    fixed = datetime(2026, 11, 15, 19, 30, tzinfo=UTC)
    _freeze_source_clock(monkeypatch, fixed)
    path = tmp_path / "kinielagpt_fixture_kickoffs.json"
    path.write_text(json.dumps(_kickoff_crosswalk_payload()), encoding="utf-8")
    monkeypatch.setattr(KinielaGPTSource, "KICKOFF_CROSSWALK_PATH", path)

    source = KinielaGPTSource()
    source.session = FakeSession(
        {
            "porcentajes_lae.asp": xml_fixture("Local", "Visitante", (60, 20, 20)),
            "porcentajes.asp?": xml_fixture("Local", "Visitante", (20, 30, 50)),
        }
    )

    row = source.probabilities(12, 2026)[0]

    assert row["fixture_identity_status"] == "verified"
    assert row["kickoff_at"] == "2026-11-17T20:45:00+01:00"
    assert row["kickoff_source"] == "UEFA test schedule"
    assert row["kickoff_evidence_url"] == "https://www.uefa.com/test-schedule/"
    assert row["kickoff_evidence_checked_at_utc"] == "2026-11-15T19:00:00+00:00"
    assert row["kickoff_timezone"] == "CET"


def test_probabilities_attach_official_kickoff_with_cest_schedule_source(
    monkeypatch, tmp_path
):
    fixed = datetime(2026, 7, 15, 19, 30, tzinfo=UTC)
    _freeze_source_clock(monkeypatch, fixed)
    payload = _kickoff_crosswalk_payload(schedule_checked_at="2026-07-15T19:00:00Z")
    payload["timezone"] = "CEST"
    payload["crosswalk_evidence"]["checked_at_utc"] = "2026-07-15T18:00:00Z"
    payload["schedule_sources"][0]["published_date"] = "2026-07-15"
    payload["schedule_sources"][0]["timezone"] = "CEST"
    payload["fixtures"][0]["provider_day_label"] = "VIE"
    payload["fixtures"][0]["kickoff_at"] = "2026-07-17T20:45:00+02:00"
    path = tmp_path / "kinielagpt_fixture_kickoffs.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(KinielaGPTSource, "KICKOFF_CROSSWALK_PATH", path)

    source = KinielaGPTSource()
    source.session = FakeSession(
        {
            "porcentajes_lae.asp": xml_fixture("Local", "Visitante", (60, 20, 20)),
            "porcentajes.asp?": xml_fixture("Local", "Visitante", (20, 30, 50)),
        }
    )

    row = source.probabilities(12, 2026)[0]

    assert row["fixture_identity_status"] == "verified"
    assert row["kickoff_at"] == "2026-07-17T20:45:00+02:00"
    assert row["kickoff_timezone"] == "CEST"


def test_kickoff_crosswalk_rejects_mismatched_cest_utc_offset(tmp_path, monkeypatch):
    payload = _kickoff_crosswalk_payload()
    payload["schedule_sources"][0]["timezone"] = "CEST"
    path = tmp_path / "kinielagpt_fixture_kickoffs.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(KinielaGPTSource, "KICKOFF_CROSSWALK_PATH", path)

    assert KinielaGPTSource._load_kickoff_crosswalk(12, 2026) == {}


def test_probabilities_do_not_attach_kickoff_when_lae_fixture_names_disagree(
    monkeypatch, tmp_path
):
    fixed = datetime(2026, 11, 15, 19, 30, tzinfo=UTC)
    _freeze_source_clock(monkeypatch, fixed)
    path = tmp_path / "kinielagpt_fixture_kickoffs.json"
    path.write_text(json.dumps(_kickoff_crosswalk_payload()), encoding="utf-8")
    monkeypatch.setattr(KinielaGPTSource, "KICKOFF_CROSSWALK_PATH", path)

    source = KinielaGPTSource()
    source.session = FakeSession(
        {
            "porcentajes_lae.asp": xml_fixture("Other", "Visitante", (60, 20, 20)),
            "porcentajes.asp?": xml_fixture("Local", "Visitante", (20, 30, 50)),
        }
    )

    row = source.probabilities(12, 2026)[0]

    assert row["fixture_identity_status"] == "source_name_mismatch"
    assert row["kickoff_at"] is None
    assert row["lae"] == pytest.approx({"1": 0.6, "X": 0.2, "2": 0.2})


def test_probabilities_do_not_use_schedule_evidence_checked_after_lae_capture(
    monkeypatch, tmp_path
):
    fixed = datetime(2026, 11, 15, 19, 0, tzinfo=UTC)
    _freeze_source_clock(monkeypatch, fixed)
    path = tmp_path / "kinielagpt_fixture_kickoffs.json"
    path.write_text(
        json.dumps(
            _kickoff_crosswalk_payload(schedule_checked_at="2026-11-15T19:30:00Z")
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(KinielaGPTSource, "KICKOFF_CROSSWALK_PATH", path)

    source = KinielaGPTSource()
    source.session = FakeSession(
        {
            "porcentajes_lae.asp": xml_fixture("Local", "Visitante", (60, 20, 20)),
            "porcentajes.asp?": xml_fixture("Local", "Visitante", (20, 30, 50)),
        }
    )

    row = source.probabilities(12, 2026)[0]

    assert row["fixture_identity_status"] == "schedule_evidence_after_lae_capture"
    assert row["kickoff_at"] is None


def test_probabilities_do_not_attach_kickoff_when_schedule_evidence_is_stale(
    monkeypatch, tmp_path
):
    fixed = datetime(2026, 11, 16, 20, 1, tzinfo=UTC)
    _freeze_source_clock(monkeypatch, fixed)
    path = tmp_path / "kinielagpt_fixture_kickoffs.json"
    path.write_text(json.dumps(_kickoff_crosswalk_payload()), encoding="utf-8")
    monkeypatch.setattr(KinielaGPTSource, "KICKOFF_CROSSWALK_PATH", path)

    source = KinielaGPTSource()
    source.session = FakeSession(
        {
            "porcentajes_lae.asp": xml_fixture("Local", "Visitante", (60, 20, 20)),
            "porcentajes.asp?": xml_fixture("Local", "Visitante", (20, 30, 50)),
        }
    )

    row = source.probabilities(12, 2026)[0]

    assert row["fixture_identity_status"] == "schedule_evidence_stale"
    assert row["kickoff_at"] is None
    assert row["lae"] == pytest.approx({"1": 0.6, "X": 0.2, "2": 0.2})


def test_curated_jornada_22_kickoff_crosswalk_loads_all_fifteen_verified_fixtures():
    mapping = KinielaGPTSource._load_kickoff_crosswalk(22, 2027)

    assert len(mapping) == 15
    assert mapping[(1, "bosnia herzegovina", "rumania")]["kickoff_at"] == (
        "2026-11-17T20:45:00+01:00"
    )
    assert mapping[(7, "r madrid f", "inter f")]["kickoff_at"] == (
        "2026-11-18T18:45:00+01:00"
    )
    assert mapping[(11, "austria wien f", "b munich f")]["kickoff_at"] == (
        "2026-11-19T18:45:00+01:00"
    )
    assert KinielaGPTSource._load_kickoff_crosswalk(21, 2027) == {}


def test_details_payload_requires_authorization_before_network_request():
    source = KinielaGPTSource()
    fake_session = FakeDetailsSession({})
    source.session = fake_session

    with pytest.raises(
        KinielaGPTAuthorizationRequired, match="KINIELAGPT_AUTHORIZATION"
    ):
        source.details_payload(12, 2026)

    assert fake_session.home_call is None
    assert fake_session.details_call is None


def test_details_payload_reads_authorization_from_environment(monkeypatch):
    monkeypatch.setenv("KINIELAGPT_AUTHORIZATION", "Bearer env-token")
    source = KinielaGPTSource()
    fake_session = FakeDetailsSession({"detallePartidos": []})
    source.session = fake_session

    source.details_payload(12, 2026)

    assert fake_session.details_call["headers"]["Authorization"] == "Bearer env-token"


def test_mcp_quiniela_keeps_public_probabilities_when_details_auth_is_missing(
    monkeypatch,
):
    class FakeFastMCP:
        def __init__(self, name):
            self.name = name
            self.tools = {}

        def tool(self):
            def register(function):
                self.tools[function.__name__] = function
                return function

            return register

    class FakeSource:
        def probabilities(self, jornada, temporada):
            return [{"id": 1, "local": "Home", "visitante": "Away"}]

        def details(self, jornada, temporada):
            raise KinielaGPTAuthorizationRequired(
                "configure KINIELAGPT_AUTHORIZATION"
            )

    monkeypatch.setattr(mcp_server, "FastMCP", FakeFastMCP)
    monkeypatch.setattr(mcp_server, "KinielaGPTSource", FakeSource)
    server = mcp_server.create_server(engine=object())

    result = server.tools["get_quiniela"](22, 2027)

    assert result["matches"] == [{"id": 1, "local": "Home", "visitante": "Away"}]
    assert result["details"] == []
    assert result["details_status"] == "blocked_missing_authorization"
    assert "KINIELAGPT_AUTHORIZATION" in result["details_error"]
