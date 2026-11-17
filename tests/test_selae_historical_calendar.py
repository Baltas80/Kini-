from __future__ import annotations

from types import SimpleNamespace

import pytest
import xlrd
from xlrd import xldate

from scripts.inspect_selae_historical_calendar import (
    INDEX_URL,
    SAMPLE_RESULT_URL,
    XLS_SIGNATURE,
    SelaeSourceError,
    _cell_to_json,
    _download_calendar,
    _is_nonempty_row,
    _is_official_https_url,
    _validate_xls_payload,
)


def _cell(cell_type: int, value: object) -> SimpleNamespace:
    return SimpleNamespace(ctype=cell_type, value=value)


def test_cell_serialization_preserves_text_and_numeric_zero() -> None:
    assert _cell_to_json(_cell(xlrd.XL_CELL_TEXT, "Jornada"), 0) == {
        "type": "text",
        "value": "Jornada",
    }
    assert _cell_to_json(_cell(xlrd.XL_CELL_NUMBER, 0.0), 0) == {
        "type": "number",
        "value": 0,
    }


def test_cell_serialization_preserves_excel_date_and_datemode() -> None:
    serial = xldate.xldate_from_date_tuple((2026, 11, 15), 0)
    result = _cell_to_json(_cell(xlrd.XL_CELL_DATE, serial), 0)

    assert result["type"] == "date"
    assert result["value"].startswith("2026-11-15")
    assert result["excel_serial"] == serial


def test_cell_serialization_handles_boolean_error_and_blank() -> None:
    assert _cell_to_json(_cell(xlrd.XL_CELL_BOOLEAN, 1), 0) == {
        "type": "boolean",
        "value": True,
    }
    assert _cell_to_json(_cell(xlrd.XL_CELL_ERROR, 7), 0) == {
        "type": "error",
        "code": 7,
    }
    assert _cell_to_json(_cell(xlrd.XL_CELL_BLANK, ""), 0) == {
        "type": "empty",
        "value": None,
    }


def test_empty_row_detection_does_not_drop_zero_values() -> None:
    assert not _is_nonempty_row(
        [_cell(xlrd.XL_CELL_EMPTY, ""), _cell(xlrd.XL_CELL_BLANK, None)]
    )
    assert _is_nonempty_row(
        [_cell(xlrd.XL_CELL_NUMBER, 0), _cell(xlrd.XL_CELL_EMPTY, "")]
    )


def test_xls_validation_requires_ole_signature_and_minimum_size() -> None:
    _validate_xls_payload(XLS_SIGNATURE + bytes(504))

    try:
        _validate_xls_payload(b"<html>" + bytes(600))
    except ValueError as exc:
        assert "not an OLE/BIFF" in str(exc)
    else:
        raise AssertionError("HTML response must not be accepted as an XLS file")

    try:
        _validate_xls_payload(XLS_SIGNATURE + bytes(10))
    except ValueError as exc:
        assert "too small" in str(exc)
    else:
        raise AssertionError("Truncated XLS response must be rejected")


class _FakeResponse:
    def __init__(self, url: str, content: bytes, status_code: int = 200) -> None:
        self.url = url
        self.content = content
        self.status_code = status_code
        self.headers = {
            "Content-Type": "text/html",
            "Content-Length": str(len(content)),
        }
        self.text = content.decode("utf-8", errors="replace")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def iter_content(self, chunk_size: int):
        yield self.content


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)
        self.headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def mount(self, prefix: str, adapter: object) -> None:
        return None

    def get(self, url: str, **kwargs) -> _FakeResponse:
        return self.responses.pop(0)


def test_official_source_url_requires_https_and_exact_selae_host() -> None:
    assert _is_official_https_url(INDEX_URL)
    assert not _is_official_https_url(INDEX_URL.replace("https://", "http://"))
    assert not _is_official_https_url(
        "https://www.loteriasyapuestas.es.evil.example/file.xls"
    )
    assert not _is_official_https_url("https://user@www.loteriasyapuestas.es/file.xls")
    assert not _is_official_https_url("https://www.loteriasyapuestas.es:8443/file.xls")


def test_historical_calendar_download_rejects_non_official_redirect(
    tmp_path, monkeypatch
) -> None:
    session = _FakeSession(
        [
            _FakeResponse(INDEX_URL, b"<html>index</html>"),
            _FakeResponse(SAMPLE_RESULT_URL, b"<html>sample</html>"),
            _FakeResponse(
                "https://example.com/HistoricoQuiniela.xls", XLS_SIGNATURE + bytes(504)
            ),
        ]
    )
    monkeypatch.setattr(
        "scripts.inspect_selae_historical_calendar.requests.Session",
        lambda: session,
    )

    with pytest.raises(SelaeSourceError, match="non-official HTTPS URL"):
        _download_calendar(tmp_path)
