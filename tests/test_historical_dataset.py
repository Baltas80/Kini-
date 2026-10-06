from pathlib import Path

from scripts.build_dataset_manifest import build_manifest


def test_demo_release_is_structurally_reproducible():
    release = Path("data/historical/releases/demo-v1")
    manifest = build_manifest(
        release,
        "demo-v1",
        "855c827cae3a48446fc118bf9c49d2fcb7d67db0",
        "2026-10-06T00:00:00Z",
    )
    assert manifest["record_counts"] == {"matches": 12, "observations": 12}
    assert manifest["immutable_release"] is True
    assert set(manifest["files"]) == {"matches.csv", "observations.jsonl"}
