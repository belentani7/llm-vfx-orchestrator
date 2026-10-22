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
