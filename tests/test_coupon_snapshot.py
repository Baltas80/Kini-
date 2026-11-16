from __future__ import annotations

import json
from pathlib import Path

import pytest

from kini_engine.coupon_snapshot import (
    load_official_coupon_snapshot,
    verify_coupon_against_selae_snapshot,
)
from scripts.import_historical_coupons import (
    load_official_snapshot_for_journey,
)


def _records():
    fixtures = []
    official = []
    for number in range(1, 15):
        home = f"Home {number}"
        away = f"Away {number}"
        fixtures.append(
            {
                "number": number,
                "home": home,
                "away": away,
                "home_goals": 1,
                "away_goals": 0,
                "result": "1",
            }
        )
        official.append(dict(fixtures[-1]))
    pleno = {
        "number": 15,
        "home": "Celta",
        "away": "Cádiz",
        "home_goals": 4,
        "away_goals": 0,
        "pleno_home_category": "M",
        "pleno_away_category": "0",
    }
    coupon = {
        "coupon_id": "2020-2021:21",
        "source_date": "2020-12-13",
        "source_date_label_at": "2020-12-13T22:57:00+01:00",
        "fixtures": fixtures + [pleno],
    }
    snapshot = {
        "schema_version": 1,
        "source": "SELAE",
        "draw_date": "2020-12-13",
        "source_url": "https://www.loteriasyapuestas.es/es/la-quiniela/resultados/la-quiniela-resultados-del-13-de-diciembre-de-2020",
        "verified_at": "2026-11-16",
        "verification_method": "manual official page review",
        "snapshot_type": "normalized_json_extract_not_raw_html",
        "fixtures": official,
        "pleno": {
            "number": 15,
            "home": "Celta",
            "away": "Cádiz",
            "home_goals": 4,
            "away_goals": 0,
            "home_category": "M",
            "away_category": "0",
        },
    }
    return coupon, snapshot


def test_official_snapshot_verifies_all_main_matches_and_pleno() -> None:
    coupon, snapshot = _records()
    verified = verify_coupon_against_selae_snapshot(
        coupon, snapshot, snapshot_sha256="a" * 64
    )
    assert verified["official_main_matches_verified"] is True
    assert verified["official_pleno_verified"] is True
    assert (
        verified["official_result_snapshot_type"]
        == "normalized_json_extract_not_raw_html"
    )
    assert verified["official_result_sha256"] == "a" * 64


def test_official_snapshot_rejects_result_mismatch() -> None:
    coupon, snapshot = _records()
    snapshot["fixtures"][0]["home_goals"] = 0
    with pytest.raises(ValueError, match="snapshot reconciliation failed"):
        verify_coupon_against_selae_snapshot(coupon, snapshot, snapshot_sha256="a" * 64)


def test_snapshot_loader_hashes_exact_json_bytes(tmp_path: Path) -> None:
    _, snapshot = _records()
    path = tmp_path / "official.json"
    raw = json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(raw)
    loaded, digest = load_official_coupon_snapshot(path)
    assert loaded["source"] == "SELAE"
    import hashlib

    assert digest == hashlib.sha256(raw).hexdigest()


def test_official_snapshot_rejects_mismatched_source_draw_date() -> None:
    coupon, snapshot = _records()
    snapshot["draw_date"] = "2020-12-14"
    with pytest.raises(ValueError, match="does not match coupon source date"):
        verify_coupon_against_selae_snapshot(coupon, snapshot, snapshot_sha256="a" * 64)

def test_snapshot_directory_loads_exact_season_journey_file(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    snapshot = {"source": "SELAE", "draw_date": "2020-12-13"}
    raw = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
    expected = snapshot_dir / "2020-2021-21.json"
    expected.write_bytes(raw)
    (snapshot_dir / "2020-2021-22.json").write_text(
        json.dumps({"source": "SELAE", "draw_date": "2020-12-20"}),
        encoding="utf-8",
    )

    loaded, digest, path = load_official_snapshot_for_journey(
        snapshot_dir,
        "2020-2021",
        21,
    )

    import hashlib

    assert loaded == snapshot
    assert path == expected
    assert digest == hashlib.sha256(raw).hexdigest()


def test_snapshot_directory_rejects_missing_journey_snapshot(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="2020-2021 journey 22"):
        load_official_snapshot_for_journey(tmp_path, "2020-2021", 22)


def test_snapshot_directory_rejects_invalid_journey_number(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        load_official_snapshot_for_journey(tmp_path, "2020-2021", 0)

def test_snapshot_loader_rejects_non_object_json(tmp_path: Path) -> None:
    path = tmp_path / "official.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_official_coupon_snapshot(path)

def test_snapshot_directory_rejects_unsafe_season_slug(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="YYYY-YYYY"):
        load_official_snapshot_for_journey(tmp_path, "../2020-2021", 21)
