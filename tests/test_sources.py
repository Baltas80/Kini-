from datetime import UTC, datetime

import pytest

import kini_engine.sources as source_module
from kini_engine.core import SIGNS
from kini_engine.sources import KinielaGPTSource


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
