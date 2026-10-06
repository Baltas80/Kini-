from datetime import datetime, timezone

import pytest

from kini_engine.snapshots import SnapshotObservation, build_snapshot, load_observations_jsonl, snapshot_id_for


def observation(observation_id, match_id, source_id, captured_at, payload_value):
    return SnapshotObservation.from_dict({
        "observation_id": observation_id,
        "match_id": match_id,
        "source_id": source_id,
        "source_record_id": f"record-{observation_id}",
        "captured_at": captured_at,
        "payload_hash": f"{payload_value:064x}",
        "payload": {"value": payload_value},
    })


def test_snapshot_selects_latest_observation_per_source_and_match():
    observations = [
        observation("old", "m1", "source-a", "2025-01-01T10:00:00Z", 1),
        observation("new", "m1", "source-a", "2025-01-01T11:00:00Z", 2),
        observation("other", "m1", "source-b", "2025-01-01T10:30:00Z", 3),
        observation("future", "m1", "source-a", "2025-01-01T12:00:00Z", 4),
    ]
    snapshot = build_snapshot(observations, information_at="2025-01-01T11:30:00Z")
    assert snapshot.observation_count == 2
    assert [(x.source_id, x.observation_id) for x in snapshot.observations] == [("source-a", "new"), ("source-b", "other")]
    assert all(observation.captured_at <= snapshot.information_at for observation in snapshot.observations)


def test_snapshot_keeps_distinct_sources_for_same_match():
    observations = [
        observation("a", "m1", "source-a", "2025-01-01T10:00:00Z", 1),
        observation("b", "m1", "source-b", "2025-01-01T10:00:00Z", 2),
    ]
    snapshot = build_snapshot(observations, information_at="2025-01-01T10:00:00Z")
    assert len(snapshot.for_match("m1")) == 2
    assert len(snapshot.for_match("m1", "source-a")) == 1


def test_snapshot_id_is_deterministic():
    a = observation("a", "m1", "source-a", "2025-01-01T10:00:00Z", 1)
    b = observation("b", "m2", "source-a", "2025-01-01T10:00:00Z", 2)
    left = build_snapshot([a, b], information_at="2025-01-01T12:00:00Z")
    right = build_snapshot([b, a], information_at="2025-01-01T12:00:00Z")
    assert left.snapshot_id == right.snapshot_id
    assert left.snapshot_id == snapshot_id_for(left.information_at, left.observations)


def test_snapshot_rejects_ambiguous_duplicate_capture_time():
    observations = [
        observation("a", "m1", "source-a", "2025-01-01T10:00:00Z", 1),
        observation("b", "m1", "source-a", "2025-01-01T10:00:00Z", 2),
    ]
    with pytest.raises(ValueError, match="same source, match and captured_at"):
        build_snapshot(observations, information_at="2025-01-01T11:00:00Z")


def test_snapshot_export_is_replayable_and_utc():
    item = SnapshotObservation.from_dict({
        "observation_id": "a",
        "match_id": "m1",
        "source_id": "source-a",
        "source_record_id": "record-a",
        "captured_at": "2025-01-01T12:00:00+01:00",
        "payload_hash": "1" * 64,
        "payload": {"status": "scheduled"},
    })
    snapshot = build_snapshot([item], information_at="2025-01-01T12:30:00+01:00")
    assert snapshot.observations[0].to_dict()["captured_at"] == "2025-01-01T11:00:00Z"
    assert snapshot.to_dict()["information_at"] == "2025-01-01T11:30:00Z"


def test_load_observations_jsonl(tmp_path):
    path = tmp_path / "observations.jsonl"
    path.write_text(
        '{"observation_id":"a","match_id":"m1","source_id":"s","source_record_id":"r","captured_at":"2025-01-01T10:00:00Z","payload_hash":"' + "0" * 64 + '","payload":{}}\n',
        encoding="utf-8",
    )
    loaded = load_observations_jsonl(path)
    assert len(loaded) == 1
    assert loaded[0].observation_id == "a"
