"""Tests for orchestrator.cli."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from orchestrator import __version__, cli
from orchestrator.config import PipelineConfig
from orchestrator.pipeline import PipelineResult
from orchestrator.state import PipelineState


class StubPipeline:
    """Records calls and returns scripted results."""

    def __init__(self, results: list[PipelineResult] | None = None, workflow: dict | None = None) -> None:
        self.results = results or [
            PipelineResult(job_id="job1", status=PipelineState.COMPLETED, iterations=1, score=0.91,
                           outputs=["a.png"])
        ]
        self.workflow = workflow or {"3": {"class_type": "KSampler", "inputs": {}}}
        self.batches: list[list] = []
        self.concurrencies: list[int | None] = []
        self.closed = False
        self.status_calls: list[str] = []
        self.retried: list[str] = []

    async def run_batch(self, jobs, *, concurrency=None, persist=True):
        self.batches.append(list(jobs))
        self.concurrencies.append(concurrency)
        return self.results

    async def plan_prompt(self, prompt, *, template=None, use_assets=None):
        self.batches.append([{"prompt": prompt, "template": template, "use_assets": use_assets}])
        return self.workflow

    async def run_retry(self, job_id, *, persist=True):
        self.retried.append(job_id)
        if job_id == "missing":
            raise KeyError(f"job {job_id} not found")
        return self.results[0]

    def get_status(self, job_id):
        self.status_calls.append(job_id)
        if job_id != "job1":
            return None

        class _Status:
            state = PipelineState.COMPLETED
            transitions = [(PipelineState.RUNNING, PipelineState.QA, "render done")]

            def __init__(self):
                self.job_id = job_id

        return _Status()

    def get_job(self, job_id):
        if job_id != "job1":
            return None
        return {"job_id": "job1", "status": "completed", "score": 0.91, "iterations": 1, "outputs": ["a.png"]}

    def list_jobs(self, limit: int = 20):
        return [{"job_id": "job1", "status": "completed", "score": 0.91, "iterations": 1,
                 "started_at": "2025-01-01T00:00:00+00:00"}]

    async def close(self):
        self.closed = True


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def stub_pipeline(monkeypatch, tmp_path):
    pipeline = StubPipeline()
    configs: list[PipelineConfig] = []

    def factory(config: PipelineConfig):
        configs.append(config)
        return pipeline

    monkeypatch.setattr(cli, "_make_pipeline", factory)
    pipeline.configs = configs  # type: ignore[attr-defined]
    pipeline.tmp_path = tmp_path  # type: ignore[attr-defined]
    return pipeline


class TestGroup:
    def test_version(self, runner):
        result = runner.invoke(cli.main, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_help_lists_commands(self, runner):
        result = runner.invoke(cli.main, ["--help"])
        assert result.exit_code == 0
        for command in ("run", "plan", "status", "jobs", "retry", "doctor", "templates"):
            assert command in result.output


class TestRun:
    def test_requires_input(self, runner):
        result = runner.invoke(cli.main, ["run"])
        assert result.exit_code == 2
        assert "provide a WORKFLOW file" in result.output

    def test_run_prompt(self, runner, stub_pipeline):
        result = runner.invoke(cli.main, ["run", "--prompt", "a hero", "-j", "3"])
        assert result.exit_code == 0
        assert "Job: job1" in result.output
        assert "Status: completed" in result.output
        assert stub_pipeline.batches[0][0]["prompt"] == "a hero"
        assert stub_pipeline.concurrencies[0] == 3
        assert stub_pipeline.closed is True

    def test_run_workflow_file(self, runner, stub_pipeline, sample_workflow, tmp_path):
        path = tmp_path / "wf.json"
        path.write_text(json.dumps(sample_workflow))
        result = runner.invoke(cli.main, ["run", str(path)])
        assert result.exit_code == 0
        assert stub_pipeline.batches[0][0] == sample_workflow

    def test_run_batch_file(self, runner, stub_pipeline, sample_workflow, tmp_path):
        path = tmp_path / "batch.json"
        path.write_text(json.dumps([{"workflow": sample_workflow}, {"prompt": "another"}]))
        result = runner.invoke(cli.main, ["run", "--batch", str(path)])
        assert result.exit_code == 0
        assert len(stub_pipeline.batches[0]) == 2

    def test_run_json_output(self, runner, stub_pipeline):
        result = runner.invoke(cli.main, ["run", "--prompt", "x", "--json"])
        payload = json.loads(result.output)
        assert payload[0]["status"] == "completed"

    def test_failed_job_exits_nonzero(self, runner, stub_pipeline):
        stub_pipeline.results = [
            PipelineResult(job_id="bad", status=PipelineState.FAILED, error="OOM")
        ]
        result = runner.invoke(cli.main, ["run", "--prompt", "x"])
        assert result.exit_code == 1
        assert "Error: OOM" in result.output

    def test_escalated_job_reports_reason(self, runner, stub_pipeline):
        stub_pipeline.results = [
            PipelineResult(job_id="esc", status=PipelineState.ESCALATED, escalation_reason="plateau")
        ]
        result = runner.invoke(cli.main, ["run", "--prompt", "x"])
        assert result.exit_code == 1
        assert "Escalated: plateau" in result.output

    def test_overrides_reach_config(self, runner, stub_pipeline):
        result = runner.invoke(cli.main, ["run", "--prompt", "x", "--set", "qa_threshold=0.55"])
        assert result.exit_code == 0
        assert stub_pipeline.configs[0].qa_threshold == pytest.approx(0.55)

    def test_max_retries_flag(self, runner, stub_pipeline):
        runner.invoke(cli.main, ["run", "--prompt", "x", "--max-retries", "1"])
        assert stub_pipeline.configs[0].max_retries == 1

    def test_config_file_is_loaded(self, runner, stub_pipeline, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("pipeline:\n  qa_threshold: 0.62\n")
        runner.invoke(cli.main, ["run", "--prompt", "x", "-c", str(config_path)])
        assert stub_pipeline.configs[0].qa_threshold == pytest.approx(0.62)

    def test_template_flag_applied_to_prompt_job(self, runner, stub_pipeline):
        runner.invoke(cli.main, ["run", "--prompt", "x", "--template", "product_render"])
        assert stub_pipeline.batches[0][0]["template"] == "product_render"

    def test_template_flag_does_not_pollute_raw_graphs(self, runner, stub_pipeline, sample_workflow, tmp_path):
        batch_path = tmp_path / "raw.json"
        batch_path.write_text(json.dumps(sample_workflow))
        runner.invoke(
            cli.main,
            ["run", "--prompt", "a", "--template", "product_render", "--batch", str(batch_path)],
        )
        jobs = stub_pipeline.batches[0]
        assert "template" not in jobs[0]  # raw workflow untouched
        assert jobs[1]["template"] == "product_render"

    def test_pipeline_errors_become_clean_messages(self, runner, stub_pipeline):
        async def boom(jobs, *, concurrency=None, persist=True):
            raise RuntimeError("no LLM provider configured")

        stub_pipeline.run_batch = boom
        result = runner.invoke(cli.main, ["run", "--prompt", "x"])
        assert result.exit_code == 1
        assert "Error: RuntimeError: no LLM provider configured" in result.output
        assert "Traceback" not in result.output

    def test_invalid_override_reports_cleanly(self, runner, stub_pipeline):
        result = runner.invoke(cli.main, ["run", "--prompt", "x", "--set", "not_a_config_key=1"])
        assert result.exit_code == 1
        assert "invalid configuration" in result.output
        assert "Traceback" not in result.output

    def test_invalid_config_reports_cleanly(self, runner, stub_pipeline, tmp_path):
        config_path = tmp_path / "bad.yaml"
        config_path.write_text("qa_threshold: 4\n")
        result = runner.invoke(cli.main, ["run", "--prompt", "x", "-c", str(config_path)])
        assert result.exit_code == 1
        assert "invalid configuration" in result.output


class TestPlan:
    def test_plan_prints_workflow(self, runner, stub_pipeline):
        result = runner.invoke(cli.main, ["plan", "--prompt", "a hero"])
        assert result.exit_code == 0
        assert json.loads(result.output)["3"]["class_type"] == "KSampler"
        assert stub_pipeline.closed is True

    def test_plan_writes_file(self, runner, stub_pipeline, tmp_path):
        out = tmp_path / "planned.json"
        result = runner.invoke(cli.main, ["plan", "--prompt", "a hero", "-o", str(out)])
        assert result.exit_code == 0
        assert json.loads(out.read_text())["3"]["class_type"] == "KSampler"
        assert "nodes" in result.output


class TestStatus:
    def test_unknown_job_exits_one(self, runner, stub_pipeline):
        result = runner.invoke(cli.main, ["status", "nope"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_known_job(self, runner, stub_pipeline):
        result = runner.invoke(cli.main, ["status", "job1"])
        assert result.exit_code == 0
        assert "State: completed" in result.output
        assert "Score: 0.91" in result.output
        assert "History:" in result.output

    def test_json_output(self, runner, stub_pipeline):
        result = runner.invoke(cli.main, ["status", "job1", "--json"])
        payload = json.loads(result.output)
        assert payload["state"] == "completed"
        assert payload["transitions"][0]["to"] == "qa"


class TestJobs:
    def test_table(self, runner, stub_pipeline):
        result = runner.invoke(cli.main, ["jobs"])
        assert result.exit_code == 0
        assert "job1" in result.output
        assert "0.910" in result.output

    def test_empty(self, runner, stub_pipeline):
        stub_pipeline.list_jobs = lambda limit=20: []
        result = runner.invoke(cli.main, ["jobs"])
        assert "No jobs" in result.output

    def test_json(self, runner, stub_pipeline):
        result = runner.invoke(cli.main, ["jobs", "--json"])
        assert json.loads(result.output)[0]["job_id"] == "job1"


class TestRetry:
    def test_unknown_job_exits_one(self, runner, stub_pipeline):
        result = runner.invoke(cli.main, ["retry", "missing"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_retry_ok(self, runner, stub_pipeline):
        result = runner.invoke(cli.main, ["retry", "job1"])
        assert result.exit_code == 0
        assert stub_pipeline.retried == ["job1"]
        assert stub_pipeline.closed is True


class FakeComfyClient:
    def __init__(self, config, ping: bool = True):
        self.config = config
        self._ping = ping

    async def ping(self) -> bool:
        return self._ping

    async def system_stats(self) -> dict:
        return {"devices": [{"name": "RTX 4090", "vram_total": 24 * 10**9}]}

    async def close(self) -> None:
        return None


@pytest.fixture
def doctor_config(tmp_path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        "llm:\n"
        "  claude:\n    model: claude-sonnet-4-20250514\n    api_key: test-key\n"
        "  qwen:\n    model: qwen-vl-max\n    api_key: test-key\n"
        "  glm:\n    model: glm-4v-plus\n    api_key: test-key\n"
    )
    return path


class TestDoctor:
    def test_ok(self, runner, monkeypatch, doctor_config):
        monkeypatch.setattr(cli, "ComfyUIClient", lambda config: FakeComfyClient(config))
        result = runner.invoke(cli.main, ["doctor", "-c", str(doctor_config)])
        assert result.exit_code == 0
        assert "ComfyUI   OK" in result.output
        assert "RTX 4090" in result.output

    def test_json(self, runner, monkeypatch, doctor_config):
        monkeypatch.setattr(cli, "ComfyUIClient", lambda config: FakeComfyClient(config))
        result = runner.invoke(cli.main, ["doctor", "-c", str(doctor_config), "--json"])
        payload = json.loads(result.output)
        assert payload["comfyui"]["ok"] is True
        assert payload["llm"]["providers"] == ["claude", "qwen", "glm"]

    def test_unreachable_comfyui_exits_one(self, runner, monkeypatch, doctor_config):
        monkeypatch.setattr(cli, "ComfyUIClient", lambda config: FakeComfyClient(config, ping=False))
        result = runner.invoke(cli.main, ["doctor", "-c", str(doctor_config)])
        assert result.exit_code == 1
        assert "FAIL" in result.output

    def test_no_providers_exits_one(self, runner, monkeypatch):
        monkeypatch.setattr(cli, "ComfyUIClient", lambda config: FakeComfyClient(config))
        result = runner.invoke(cli.main, ["doctor"])
        assert result.exit_code == 1
        assert "none configured" in result.output


def test_templates_command_lists_bundled(runner):
    result = runner.invoke(cli.main, ["templates"])
    assert result.exit_code == 0
    assert "character_generation" in result.output
    assert "product_render" in result.output
