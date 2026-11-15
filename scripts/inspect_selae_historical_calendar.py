from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import xlrd
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SOURCE_URL = (
    "https://www.loteriasyapuestas.es/f/loterias/documentos/"
    "Quiniela/Calendarios/HistoricoQuiniela.xls"
)
XLS_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
CHUNK_SIZE = 64 * 1024
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; KiniEngine/0.2; "
        "+https://github.com/Baltas80/Kini-)"
    ),
    "Accept": "application/vnd.ms-excel,application/octet-stream;q=0.9,*/*;q=0.5",
    "Accept-Language": "es-ES,es;q=0.9",
}


def _finite_number(value: Any) -> int | float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Excel numeric cell is not finite")
    if number.is_integer():
        return int(number)
    return number


def _cell_to_json(cell: Any, datemode: int) -> dict[str, Any]:
    """Serialize an xlrd cell without discarding its original cell type."""
    value = cell.value
    cell_type = cell.ctype

    if cell_type in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return {"type": "empty", "value": None}
    if cell_type == xlrd.XL_CELL_TEXT:
        return {"type": "text", "value": str(value)}
    if cell_type == xlrd.XL_CELL_NUMBER:
        return {"type": "number", "value": _finite_number(value)}
    if cell_type == xlrd.XL_CELL_DATE:
        parsed = xlrd.xldate_as_datetime(value, datemode)
        return {
            "type": "date",
            "value": parsed.isoformat(),
            "excel_serial": _finite_number(value),
        }
    if cell_type == xlrd.XL_CELL_BOOLEAN:
        return {"type": "boolean", "value": bool(value)}
    if cell_type == xlrd.XL_CELL_ERROR:
        return {"type": "error", "code": int(value)}
    return {"type": f"unknown_{cell_type}", "value": str(value)}


def _is_nonempty_row(cells: list[Any]) -> bool:
    return any(
        cell.ctype not in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK)
        and cell.value not in (None, "")
        for cell in cells
    )


def _validate_xls_payload(payload: bytes) -> None:
    if len(payload) < 512:
        raise ValueError(f"SELAE XLS response is too small: {len(payload)} bytes")
    if len(payload) > MAX_DOWNLOAD_BYTES:
        raise ValueError(
            f"SELAE XLS response exceeds {MAX_DOWNLOAD_BYTES} bytes"
        )
    if not payload.startswith(XLS_SIGNATURE):
        preview = payload[:80].decode("utf-8", errors="replace")
        raise ValueError(
            "SELAE response is not an OLE/BIFF .xls file; "
            f"first bytes={payload[:16].hex()} preview={preview!r}"
        )


def _download_calendar() -> tuple[bytes, dict[str, Any]]:
    retry = Retry(
        total=3,
        connect=3,
        read=2,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    with requests.Session() as session:
        session.headers.update(HEADERS)
        session.mount("https://", HTTPAdapter(max_retries=retry))
        with session.get(
            SOURCE_URL,
            stream=True,
            timeout=(15, 60),
            allow_redirects=True,
        ) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_DOWNLOAD_BYTES:
                    raise ValueError(
                        f"SELAE XLS exceeds {MAX_DOWNLOAD_BYTES} bytes"
                    )
                chunks.append(chunk)
            payload = b"".join(chunks)
            _validate_xls_payload(payload)
            metadata = {
                "http_status": response.status_code,
                "content_type": response.headers.get("Content-Type"),
                "content_length_header": response.headers.get("Content-Length"),
                "downloaded_bytes": len(payload),
                "final_url": response.url,
            }
    return payload, metadata


def inspect_workbook(
    payload: bytes,
    output_dir: Path,
    response_metadata: dict[str, Any],
) -> dict[str, Any]:
    workbook = xlrd.open_workbook(file_contents=payload, on_demand=False)
    rows_path = output_dir / "historical_calendar_rows.jsonl"
    sheets: list[dict[str, Any]] = []
    total_nonempty_rows = 0
    total_date_cells = 0

    with rows_path.open("w", encoding="utf-8", newline="\n") as rows_file:
        for sheet in workbook.sheets():
            first_rows: list[dict[str, Any]] = []
            last_rows: deque[dict[str, Any]] = deque(maxlen=10)
            nonempty_rows = 0
            date_cells = 0
            date_rows = 0

            for row_index in range(sheet.nrows):
                cells = sheet.row(row_index)
                if not _is_nonempty_row(cells):
                    continue

                serialized_cells = [
                    _cell_to_json(cell, workbook.datemode) for cell in cells
                ]
                row_record = {
                    "sheet": sheet.name,
                    "row_index_1based": row_index + 1,
                    "cells": serialized_cells,
                }
                rows_file.write(
                    json.dumps(
                        row_record,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    + "\n"
                )

                row_date_cells = sum(
                    cell.ctype == xlrd.XL_CELL_DATE for cell in cells
                )
                date_cells += row_date_cells
                date_rows += int(row_date_cells > 0)
                nonempty_rows += 1
                if len(first_rows) < 20:
                    first_rows.append(row_record)
                last_rows.append(row_record)

            if nonempty_rows == 0:
                raise ValueError(f"SELAE workbook sheet {sheet.name!r} is empty")

            sheets.append(
                {
                    "name": sheet.name,
                    "nrows": sheet.nrows,
                    "ncols": sheet.ncols,
                    "nonempty_rows": nonempty_rows,
                    "date_cells": date_cells,
                    "rows_with_excel_dates": date_rows,
                    "first_nonempty_rows": first_rows,
                    "last_nonempty_rows": list(last_rows),
                }
            )
            total_nonempty_rows += nonempty_rows
            total_date_cells += date_cells

    if not sheets or total_nonempty_rows == 0:
        raise ValueError("SELAE workbook contains no non-empty sheets")

    return {
        "schema_version": 1,
        "source": SOURCE_URL,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "response": response_metadata,
        "file": {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "signature": payload[:8].hex(),
        },
        "workbook": {
            "sheet_count": len(sheets),
            "datemode": workbook.datemode,
            "total_nonempty_rows": total_nonempty_rows,
            "total_excel_date_cells": total_date_cells,
            "raw_rows_file": rows_path.name,
            "sheets": sheets,
        },
        "interpretation_status": (
            "raw_schema_inspected; draw identifiers and row semantics "
            "require explicit review before parsing"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Download and inspect the official SELAE historical Quiniela "
            "calendar XLS without inferring draw IDs or result rows."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/selae-historical-calendar"),
    )
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / "inspection.json"

    try:
        payload, response_metadata = _download_calendar()
        report = inspect_workbook(payload, args.output_dir, response_metadata)
        source_path = args.output_dir / "HistoricoQuiniela.xls"
        source_path.write_bytes(payload)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(
            "SELAE_CALENDAR_INSPECTION_OK "
            f"sheets={report['workbook']['sheet_count']} "
            f"rows={report['workbook']['total_nonempty_rows']} "
            f"date_cells={report['workbook']['total_excel_date_cells']} "
            f"sha256={report['file']['sha256']}"
        )
        print(f"Report: {report_path}")
        return 0
    except (
        OSError,
        requests.RequestException,
        ValueError,
        xlrd.XLRDError,
    ) as exc:
        failure = {
            "schema_version": 1,
            "source": SOURCE_URL,
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "success": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        report_path.write_text(
            json.dumps(failure, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"SELAE_CALENDAR_INSPECTION_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
