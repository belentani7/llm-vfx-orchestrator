"""Tests for state machine, job store and templates."""

from __future__ import annotations

import json

import pytest

from orchestrator.state import PipelineState, StateMachine, StateTransition
from orchestrator.store import JobStore
from orchestrator.template import apply_template_defaults, available_templates, load_template


class TestStateMachine:
    def test_happy_path(self):
        machine = StateMachine()
        machine.transition(PipelineState.RUNNING, "go")
        machine.transition(PipelineState.QA, "render done")
        machine.transition(PipelineState.COMPLETED, "passed")
        assert machine.state is PipelineState.COMPLETED
        assert machine.is_terminal
        assert [t.to_state for t in machine.history] == [
            PipelineState.RUNNING,
            PipelineState.QA,
            PipelineState.COMPLETED,
        ]

    def test_invalid_transition_raises(self):
        machine = StateMachine()
        with pytest.raises(ValueError, match="Invalid transition"):
            machine.transition(PipelineState.QA)

    def test_completed_is_terminal(self):
        machine = StateMachine()
        machine.transition(PipelineState.RUNNING)
        machine.transition(PipelineState.COMPLETED)
        with pytest.raises(ValueError):
            machine.transition(PipelineState.RUNNING)
        assert not machine.can_transition(PipelineState.RUNNING)

    def test_escalation_is_reachable_from_qa(self):
        machine = StateMachine()
        machine.transition(PipelineState.RUNNING)
        machine.transition(PipelineState.QA)
        machine.transition(PipelineState.ESCALATED, "needs review")
        assert machine.state is PipelineState.ESCALATED
        assert machine.is_terminal

    def test_history_dicts_round_trip(self):
        machine = StateMachine()
        machine.transition(PipelineState.RUNNING, "a")
        machine.transition(PipelineState.FAILED, "b")
        records = machine.history_dicts()
        assert records[0]["from"] == "pending"
        restored = [StateTransition.from_dict(record) for record in records]
        assert restored[1].to_state is PipelineState.FAILED
        assert restored[1].reason == "b"

    def test_history_is_a_copy(self):
        machine = StateMachine()
        machine.transition(PipelineState.RUNNING)
        machine.history.clear()
        assert len(machine.history) == 1


class TestJobStore:
    def test_save_get_roundtrip(self, tmp_path):
        store = JobStore(tmp_path)
        assert store.save("abc123", {"status": "completed", "score": 0.9}) is True
        record = store.get("abc123")
        assert record["status"] == "completed"
        assert record["job_id"] == "abc123"
        assert record["schema_version"] == 1
        assert "updated_at" in record

    def test_get_missing_returns_none(self, tmp_path):
        assert JobStore(tmp_path).get("nope") is None

    def test_list_is_newest_first(self, tmp_path):
        store = JobStore(tmp_path)
        store.save("old", {"started_at": "2024-01-01T00:00:00+00:00"})
        store.save("new", {"started_at": "2025-01-01T00:00:00+00:00"})
        assert [record["job_id"] for record in store.list()] == ["new", "old"]

    def test_list_skips_corrupt_files(self, tmp_path):
        store = JobStore(tmp_path)
        store.save("good", {"started_at": "2025-01-01T00:00:00+00:00"})
        (tmp_path / "broken.json").write_text("{oops")
        assert [record["job_id"] for record in store.list()] == ["good"]

    def test_job_id_is_sanitized(self, tmp_path):
        store = JobStore(tmp_path)
        path = store.path_for("../../evil")
        assert path.parent == tmp_path
        assert ".." not in path.name

    def test_delete(self, tmp_path):
        store = JobStore(tmp_path)
        store.save("x", {"status": "completed"})
        assert store.delete("x") is True
        assert store.get("x") is None
        assert store.delete("x") is False

    def test_oversized_workflow_is_dropped(self, tmp_path, monkeypatch):
        import orchestrator.store as store_module

        monkeypatch.setattr(store_module, "_MAX_WORKFLOW_BYTES", 50)
        store = JobStore(tmp_path)
        store.save("big", {"workflow": {"3": {"class_type": "X", "inputs": {"a": "b" * 100}}}})
        record = store.get("big")
        assert record["workflow"] is None
        assert record["workflow_truncated"] is True

    def test_save_never_raises_on_unwritable_dir(self, tmp_path):
        store = JobStore(tmp_path / "sub")
        store.directory = tmp_path / "sub" / "file.txt"
        store.directory.write_text("not a dir")
        assert store.save("job", {"status": "completed"}) is False


class TestTemplates:
    def test_bundled_templates_present(self):
        names = available_templates()
        assert {"character_generation", "environment_generation", "product_render"} <= set(names)

    def test_load_by_name_merges_runtime_config(self):
        template = load_template("character_generation")
        assert template["name"] == "character_generation"
        assert template["default_steps"] == 30
        assert "negative_prompt" in template

    def test_load_missing_raises(self):
        with pytest.raises(FileNotFoundError):
            load_template("does-not-exist")

    def test_apply_defaults_fills_only_missing(self, sample_workflow):
        template = load_template("character_generation")
        workflow = json.loads(json.dumps(sample_workflow))
        workflow["3"]["inputs"]["steps"] = 99  # explicit value must survive
        apply_template_defaults(workflow, template)
        assert workflow["3"]["inputs"]["steps"] == 99
        assert workflow["3"]["inputs"]["cfg"] == 7.5
        assert workflow["7"]["inputs"]["text"] == template["negative_prompt"]

    def test_apply_defaults_without_template_is_noop(self, sample_workflow):
        before = json.dumps(sample_workflow, sort_keys=True)
        apply_template_defaults(sample_workflow, {})
        assert json.dumps(sample_workflow, sort_keys=True) == before
