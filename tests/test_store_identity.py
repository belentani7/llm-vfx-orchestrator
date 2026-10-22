"""Regression tests: job IDs must be unique filesystem keys without aliasing."""

import pytest

from orchestrator.store import JobStore


def test_path_preserves_legitimate_ids(tmp_path):
    store = JobStore(tmp_path / "jobs")
    for job_id in ("job1", "a-b_12", "f01ad32a"):
        assert store.path_for(job_id) == tmp_path / "jobs" / (job_id + ".json")


@pytest.mark.parametrize("job_id", [
    "", "..", ".", "../job", "../../job", "a/b", "a\\b", "/tmp/job",
    "a b", "ñ", "a" * 121, None, 123, ".hidden",
])
def test_invalid_or_colliding_ids_are_rejected(tmp_path, job_id):
    store = JobStore(tmp_path / "jobs")
    with pytest.raises(ValueError, match="job_id"):
        store.path_for(job_id)
    assert not list((tmp_path / "jobs").glob("*.json"))


def test_save_and_retrieve_do_not_alias_distinct_ids(tmp_path):
    store = JobStore(tmp_path / "jobs")
    assert store.save("job", {"status": "completed"})
    assert store.save("job_", {"status": "running"})
    assert store.get("job")["status"] == "completed"
    assert store.get("job_")["status"] == "running"
    with pytest.raises(ValueError):
        store.get("../job")
    assert len(list((tmp_path / "jobs").glob("*.json"))) == 2


def test_workflow_limit_uses_actual_utf8_and_matching_disk_format(tmp_path, monkeypatch):
    import json
    import orchestrator.store as store_module

    workflow = {"3": {"inputs": {"prompt": "🎬" * 10}}}
    wire_size = len(json.dumps(workflow, indent=2, ensure_ascii=False, default=str).encode("utf-8"))
    escaped_size = len(json.dumps(workflow))
    assert wire_size < escaped_size
    monkeypatch.setattr(store_module, "_MAX_WORKFLOW_BYTES", wire_size)
    store = JobStore(tmp_path / "jobs")
    assert store.save("unicode", {"workflow": workflow})
    assert store.get("unicode")["workflow"] == workflow
    assert "workflow_truncated" not in store.get("unicode")


def test_oversized_utf8_payload_is_omitted_explicitly(tmp_path, monkeypatch):
    import orchestrator.store as store_module

    monkeypatch.setattr(store_module, "_MAX_WORKFLOW_BYTES", 60)
    store = JobStore(tmp_path / "jobs")
    assert store.save("big", {"workflow": {"prompt": "🎬" * 50}, "status": "pending"})
    data = store.get("big")
    assert data["workflow"] is None
    assert data["workflow_truncated"] is True
    assert data["status"] == "pending"


def test_circular_workflow_does_not_crash_job_persistence(tmp_path):
    store = JobStore(tmp_path / "jobs")
    cycle = {}
    cycle["loop"] = cycle
    assert store.save("invalid", {"workflow": cycle, "status": "escalated"})
    saved = store.get("invalid")
    assert saved["workflow"] is None
    assert saved["workflow_omitted_reason"] == "invalid_serialization"
    assert saved["status"] == "escalated"
