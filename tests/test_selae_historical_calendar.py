from __future__ import annotations

from types import SimpleNamespace

import xlrd

from scripts.inspect_selae_historical_calendar import (
    XLS_SIGNATURE,
    _cell_to_json,
    _is_nonempty_row,
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
    serial = xlrd.xldate_from_date_tuple((2026, 11, 15), 0)
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
