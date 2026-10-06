import json
from pathlib import Path

import pytest

from scripts.build_dataset_manifest import build_manifest
from kini_engine.validation import canonical_payload_hash


RELEASE = Path("data/historical/releases/demo-v1")
DATASET_ID = "demo-v1"
SOURCE_REVISION = "855c827cae3a48446fc118bf9c49d2fcb7d67db0"
GENERATED_AT = "2026-10-06T00:00:00Z"


def test_demo_release_manifest_matches_its_contents():
    stored_manifest = json.loads((RELEASE / "manifest.json").read_text(encoding="utf-8"))
    rebuilt_manifest = build_manifest(
        RELEASE,
        DATASET_ID,
        SOURCE_REVISION,
        stored_manifest["generated_at"],
    )

    assert stored_manifest == rebuilt_manifest
    assert stored_manifest["record_counts"] == {"matches": 12, "observations": 12}
    assert stored_manifest["immutable_release"] is True
    assert set(stored_manifest["files"]) == {"matches.csv", "observations.jsonl"}


def test_demo_observation_payload_hashes_are_canonical():
    with (RELEASE / "observations.jsonl").open(encoding="utf-8") as fh:
        observations = [json.loads(line) for line in fh if line.strip()]

    assert len(observations) == 12
    assert all(
        obs["payload_hash"] == canonical_payload_hash(obs["payload"])
        for obs in observations
    )


def test_reject_invalid_payload_hash(tmp_path):
    release = tmp_path / "release"
    release.mkdir()
    (release / "matches.csv").write_text(
        (RELEASE / "matches.csv").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    observation = json.loads(
        (RELEASE / "observations.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    observation["payload_hash"] = "0" * 64
    (release / "observations.jsonl").write_text(
        json.dumps(observation) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="payload_hash does not match payload"):
        build_manifest(release, DATASET_ID, SOURCE_REVISION, GENERATED_AT)
