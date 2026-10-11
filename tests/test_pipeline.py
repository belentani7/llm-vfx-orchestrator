"""Tests for orchestrator.pipeline — the closed render/QA/correct loop."""

from __future__ import annotations

import asyncio
import json

import pytest

from orchestrator.comfyui_client import OutputImage, RenderOutcome
from orchestrator.config import PipelineConfig
from orchestrator.pipeline import (
    PipelineResult,
    PipelineStatus,
    VFPPipeline,
    _avg_score,
    guess_media_type,
)
from orchestrator.state import PipelineState
from orchestrator.store import JobStore
from tests.conftest import (
    PNG_BYTES,
    FakeComfyUI,
    StubAssets,
    StubCorrection,
    StubDirector,
    StubQA,
    build_pipeline,
)


class SlowQA:
    role = "qwen"

    def __init__(self, delay: float = 0.02, score: float = 0.95) -> None:
        self.delay = delay
        self.score = score
        self.inflight = 0
        self.peak = 0

    async def inspect(self, image_description="", criteria="", *, image=None, image_media_type="image/png",
                      extra_context="", client=None):
        self.inflight += 1
        self.peak = max(self.peak, self.inflight)
        try:
            await asyncio.sleep(self.delay)
            return {"score": self.score, "issues": [], "summary": "slow qa"}
        finally:
            self.inflight -= 1


class TestAvgScore:
    def test_empty(self):
        assert _avg_score([]) == 0.0

    def test_single(self):
        assert _avg_score([{"score": 0.7}]) == pytest.approx(0.7)

    def test_multiple(self):
        assert _avg_score([{"score": 0.8}, {"score": 0.6}, {"score": 1.0}]) == pytest.approx(0.8)

    def test_string_scores_are_coerced(self):
        assert _avg_score([{"score": "90%"}, {"score": "1/10"}]) == pytest.approx(0.5)

    def test_missing_scores_count_as_zero(self):
        assert _avg_score([{"issues": ["x"]}, {"score": 1.0}]) == pytest.approx(0.5)


class TestPipelineResult:
    def test_default_fields(self):
        result = PipelineResult(job_id="abc", status=PipelineState.PENDING)
        assert result.outputs == []
        assert result.iterations == 0
        assert result.qa_reports == []
        assert result.error is None
        assert result.corrections == []
        assert result.ok is False

    def test_as_dict_is_json_serializable(self):
        result = PipelineResult(job_id="abc", status=PipelineState.COMPLETED, score=0.9)
        payload = json.loads(json.dumps(result.as_dict()))
        assert payload["status"] == "completed"
        assert payload["ok"] is True


class TestExecuteHappyPath:
    @pytest.mark.asyncio
    async def test_execute_success(self, pipeline_config, sample_workflow, tmp_path):
        comfy = FakeComfyUI()
        qa = StubQA(scores=[0.9])
        pipeline = build_pipeline(pipeline_config, comfyui=comfy, qa=qa, store=JobStore(tmp_path / "jobs"))

        result = await pipeline.execute(sample_workflow)

        assert result.status is PipelineState.COMPLETED
        assert result.job_id
        assert result.outputs == ["output_001.png"]
        assert result.iterations == 1
        assert result.score == pytest.approx(0.9)
        assert result.ok is True
        assert comfy.queued[0] == sample_workflow
        assert result.metrics["renders"] == 1
        assert "total_s" in result.metrics

    @pytest.mark.asyncio
    async def test_job_is_persisted_and_readable(self, pipeline_config, sample_workflow, tmp_path):
        store = JobStore(tmp_path / "jobs")
        pipeline = build_pipeline(pipeline_config, store=store)
        result = await pipeline.execute(sample_workflow)
        record = store.get(result.job_id)
        assert record["status"] == "completed"
        assert record["workflow"]["3"]["class_type"] == "KSampler"
        assert record["outputs"] == ["output_001.png"]

    @pytest.mark.asyncio
    async def test_status_is_readable_from_another_process(self, pipeline_config, sample_workflow, tmp_path):
        store = JobStore(tmp_path / "jobs")
        first = build_pipeline(pipeline_config, store=store)
        result = await first.execute(sample_workflow)

        second = build_pipeline(pipeline_config, store=JobStore(tmp_path / "jobs"))
        status = second.get_status(result.job_id)
        assert isinstance(status, PipelineStatus)
        assert status.state is PipelineState.COMPLETED
        assert status.score == pytest.approx(0.92)
        assert [step[1] for step in status.transitions][-1] is PipelineState.COMPLETED

    @pytest.mark.asyncio
    async def test_unknown_status_is_none(self, pipeline_config, tmp_path):
        pipeline = build_pipeline(pipeline_config, store=JobStore(tmp_path / "empty"))
        assert pipeline.get_status("nonexistent") is None

    @pytest.mark.asyncio
    async def test_persist_false_skips_store(self, pipeline_config, sample_workflow, tmp_path):
        store = JobStore(tmp_path / "jobs")
        pipeline = build_pipeline(pipeline_config, store=store)
        result = await pipeline.execute(sample_workflow, persist=False)
        assert store.get(result.job_id) is None

    @pytest.mark.asyncio
    async def test_close_closes_comfyui(self, pipeline_config):
        comfy = FakeComfyUI()
        pipeline = build_pipeline(pipeline_config, comfyui=comfy)
        async with pipeline:
            pass
        assert comfy.closed is True

    @pytest.mark.asyncio
    async def test_list_jobs(self, pipeline_config, sample_workflow, tmp_path):
        pipeline = build_pipeline(pipeline_config, store=JobStore(tmp_path / "jobs"))
        await pipeline.execute(sample_workflow)
        await pipeline.execute(sample_workflow)
        records = pipeline.list_jobs()
        assert len(records) == 2


class TestCorrectionLoop:
    @pytest.mark.asyncio
    async def test_completes_after_correction(self, pipeline_config, sample_workflow, tmp_path):
        comfy = FakeComfyUI()
        qa = StubQA(scores=[0.4, 0.93])
        correction = StubCorrection(pipeline_config.llm, patches=[{"3": {"steps": 50}}])
        pipeline = build_pipeline(
            pipeline_config, comfyui=comfy, qa=qa, correction=correction, store=JobStore(tmp_path / "jobs")
        )

        result = await pipeline.execute(sample_workflow)

        assert result.status is PipelineState.COMPLETED
        assert result.iterations == 2
        assert len(result.corrections) == 1
        assert result.corrections[0]["changed"] is True
        assert comfy.queued[1]["3"]["inputs"]["steps"] == 50
        assert comfy.queued[0]["3"]["inputs"]["steps"] == 30  # original untouched
        assert correction.calls[0]["qa_report"]["score"] == pytest.approx(0.4)

    @pytest.mark.asyncio
    async def test_escalates_when_retries_exhausted(self, sample_workflow, tmp_path, llm_config):
        config = PipelineConfig(max_retries=1, qa_threshold=0.8, llm=llm_config, store_dir=str(tmp_path))
        pipeline = build_pipeline(config, qa=StubQA(scores=[0.3, 0.35]))
        result = await pipeline.execute(sample_workflow)
        assert result.status is PipelineState.ESCALATED
        assert result.needs_review is True
        assert result.iterations == 2
        assert "max_retries" in (result.escalation_reason or "")

    @pytest.mark.asyncio
    async def test_escalates_on_plateau(self, sample_workflow, tmp_path, llm_config):
        config = PipelineConfig(
            max_retries=5, qa_threshold=0.9, plateau_patience=2, llm=llm_config, store_dir=str(tmp_path)
        )
        correction = StubCorrection(llm_config, patches=[{"3": {"steps": 50}}, {"3": {"steps": 60}}])
        pipeline = build_pipeline(
            config, qa=StubQA(scores=[0.4, 0.4, 0.4, 0.95]), correction=correction
        )
        result = await pipeline.execute(sample_workflow)
        assert result.status is PipelineState.ESCALATED
        assert result.iterations == 3
        assert "no meaningful improvement" in (result.escalation_reason or "")

    @pytest.mark.asyncio
    async def test_empty_patch_escalates_instead_of_rerendering(self, sample_workflow, tmp_path, llm_config):
        config = PipelineConfig(max_retries=3, qa_threshold=0.9, llm=llm_config, store_dir=str(tmp_path))
        comfy = FakeComfyUI()
        correction = StubCorrection(llm_config, patches=[{}])
        pipeline = build_pipeline(config, comfyui=comfy, qa=StubQA(scores=[0.4]), correction=correction)
        result = await pipeline.execute(sample_workflow)
        assert result.status is PipelineState.ESCALATED
        assert result.iterations == 1  # no wasted re-render
        assert "no change" in (result.escalation_reason or "")

    @pytest.mark.asyncio
    async def test_broken_correction_agent_escalates(self, sample_workflow, tmp_path, llm_config):
        config = PipelineConfig(max_retries=2, qa_threshold=0.9, llm=llm_config, store_dir=str(tmp_path))
        correction = StubCorrection(llm_config, error=RuntimeError("llm down"))
        pipeline = build_pipeline(config, qa=StubQA(scores=[0.3]), correction=correction)
        result = await pipeline.execute(sample_workflow)
        assert result.status is PipelineState.ESCALATED
        assert "correction agent failed" in result.corrections[0]["reason"]

    @pytest.mark.asyncio
    async def test_correction_receives_prior_attempts(self, sample_workflow, tmp_path, llm_config):
        config = PipelineConfig(max_retries=3, qa_threshold=0.95, llm=llm_config, store_dir=str(tmp_path))
        correction = StubCorrection(
            llm_config, patches=[{"3": {"steps": 40}}, {"3": {"steps": 60}}]
        )
        pipeline = build_pipeline(config, qa=StubQA(scores=[0.4, 0.5, 0.99]), correction=correction)
        result = await pipeline.execute(sample_workflow)
        assert result.status is PipelineState.COMPLETED
        assert len(correction.calls[1]["prior_corrections"]) == 1


class TestRenderFailures:
    @pytest.mark.asyncio
    async def test_execution_error_is_corrected(self, pipeline_config, sample_workflow, tmp_path):
        comfy = FakeComfyUI(outcomes=[RenderOutcome("error", error="CUDA out of memory | node=4")])
        qa = StubQA(scores=[0.95])
        correction = StubCorrection(pipeline_config.llm, patches=[{"5": {"width": 512, "height": 512}}])
        pipeline = build_pipeline(
            pipeline_config, comfyui=comfy, qa=qa, correction=correction, store=JobStore(tmp_path / "jobs")
        )

        result = await pipeline.execute(sample_workflow)

        assert result.status is PipelineState.COMPLETED
        assert result.iterations == 2
        assert "CUDA out of memory" in correction.calls[0]["error_log"]
        assert comfy.queued[1]["5"]["inputs"]["width"] == 512

    @pytest.mark.asyncio
    async def test_execution_error_fails_when_correction_disabled(self, pipeline_config, sample_workflow, tmp_path):
        pipeline_config.correct_execution_errors = False
        comfy = FakeComfyUI(outcomes=[RenderOutcome("error", error="OOM")])
        pipeline = build_pipeline(pipeline_config, comfyui=comfy, store=JobStore(tmp_path / "jobs"))
        result = await pipeline.execute(sample_workflow)
        assert result.status is PipelineState.FAILED
        assert result.iterations == 1
        assert "OOM" in (result.error or "")

    @pytest.mark.asyncio
    async def test_execution_error_without_retries_fails(self, sample_workflow, tmp_path, llm_config):
        config = PipelineConfig(max_retries=0, llm=llm_config, store_dir=str(tmp_path))
        comfy = FakeComfyUI(outcomes=[RenderOutcome("error", error="OOM")])
        pipeline = build_pipeline(config, comfyui=comfy)
        result = await pipeline.execute(sample_workflow)
        assert result.status is PipelineState.FAILED
        assert "OOM" in (result.error or "")

    @pytest.mark.asyncio
    async def test_render_without_outputs_fails(self, sample_workflow, tmp_path, llm_config):
        config = PipelineConfig(max_retries=0, llm=llm_config, store_dir=str(tmp_path))
        comfy = FakeComfyUI(images=[])
        pipeline = build_pipeline(config, comfyui=comfy)
        result = await pipeline.execute(sample_workflow)
        assert result.status is PipelineState.FAILED
        assert "no output images" in (result.error or "")

    @pytest.mark.asyncio
    async def test_timeout_interrupts_the_queued_render(self, sample_workflow, tmp_path, llm_config):
        config = PipelineConfig(max_retries=0, llm=llm_config, store_dir=str(tmp_path))
        comfy = FakeComfyUI(outcomes=[RenderOutcome("timeout")])
        pipeline = build_pipeline(config, comfyui=comfy)
        result = await pipeline.execute(sample_workflow)
        assert result.status is PipelineState.FAILED
        assert comfy.interrupts == 1

    @pytest.mark.asyncio
    async def test_interrupted_render_is_reported(self, sample_workflow, tmp_path, llm_config):
        config = PipelineConfig(max_retries=0, llm=llm_config, store_dir=str(tmp_path))
        comfy = FakeComfyUI(outcomes=[RenderOutcome("interrupted", error="interrupted")])
        pipeline = build_pipeline(config, comfyui=comfy)
        result = await pipeline.execute(sample_workflow)
        assert result.status is PipelineState.FAILED
        assert "interrupted" in (result.error or "")


class TestQaHandling:
    @pytest.mark.asyncio
    async def test_pixels_are_sent_to_the_inspector(self, pipeline_config, sample_workflow, tmp_path):
        qa = StubQA(scores=[0.95])
        pipeline = build_pipeline(pipeline_config, qa=qa, store=JobStore(tmp_path / "jobs"))
        await pipeline.execute(sample_workflow)
        assert qa.calls[0]["image"] == PNG_BYTES
        assert qa.calls[0]["media_type"] == "image/png"

    @pytest.mark.asyncio
    async def test_media_type_follows_the_file_extension(self, pipeline_config, sample_workflow, tmp_path):
        comfy = FakeComfyUI(images=[OutputImage("shot.webp")])
        qa = StubQA(scores=[0.95])
        pipeline = build_pipeline(pipeline_config, comfyui=comfy, qa=qa, store=JobStore(tmp_path / "jobs"))
        await pipeline.execute(sample_workflow)
        assert qa.calls[0]["media_type"] == "image/webp"

    @pytest.mark.asyncio
    async def test_oversized_image_is_not_attached(self, pipeline_config, sample_workflow, tmp_path):
        pipeline_config.vision_max_bytes = 4
        qa = StubQA(scores=[0.95])
        pipeline = build_pipeline(pipeline_config, qa=qa, store=JobStore(tmp_path / "jobs"))
        await pipeline.execute(sample_workflow)
        assert qa.calls[0]["image"] is None
        assert "not attached" in qa.calls[0]["extra_context"]

    @pytest.mark.asyncio
    async def test_vision_disabled_provider_gets_text_only(self, pipeline_config, sample_workflow, tmp_path):
        pipeline_config.llm.qwen.vision = False
        qa = StubQA(scores=[0.95])
        pipeline = build_pipeline(pipeline_config, qa=qa, store=JobStore(tmp_path / "jobs"))
        await pipeline.execute(sample_workflow)
        assert qa.calls[0]["image"] is None

    @pytest.mark.asyncio
    async def test_qa_outage_escalates_instead_of_rerendering(self, pipeline_config, sample_workflow, tmp_path):
        comfy = FakeComfyUI()
        qa = StubQA(error=RuntimeError("dashscope 503"))
        pipeline = build_pipeline(pipeline_config, comfyui=comfy, qa=qa, store=JobStore(tmp_path / "jobs"))
        result = await pipeline.execute(sample_workflow)
        assert result.status is PipelineState.ESCALATED
        assert result.iterations == 1
        assert "QA unavailable" in (result.escalation_reason or "")

    @pytest.mark.asyncio
    async def test_download_failure_escalates(self, pipeline_config, sample_workflow, tmp_path):
        comfy = FakeComfyUI(download_error=RuntimeError("404 not found"))
        pipeline = build_pipeline(pipeline_config, comfyui=comfy, store=JobStore(tmp_path / "jobs"))
        result = await pipeline.execute(sample_workflow)
        assert result.status is PipelineState.ESCALATED
        assert "QA unavailable" in (result.escalation_reason or "")

    @pytest.mark.asyncio
    async def test_only_the_first_n_images_are_inspected(self, pipeline_config, sample_workflow, tmp_path):
        pipeline_config.max_qa_images = 2
        comfy = FakeComfyUI(images=[OutputImage(f"frame_{i}.png") for i in range(5)])
        qa = StubQA(scores=[0.95] * 5)
        pipeline = build_pipeline(pipeline_config, comfyui=comfy, qa=qa, store=JobStore(tmp_path / "jobs"))
        result = await pipeline.execute(sample_workflow)
        assert len(result.qa_reports) == 2
        assert len(result.outputs) == 5

    @pytest.mark.asyncio
    async def test_qa_runs_concurrently(self, pipeline_config, sample_workflow, tmp_path):
        pipeline_config.qa_concurrency = 4
        comfy = FakeComfyUI(images=[OutputImage(f"frame_{i}.png") for i in range(4)])
        qa = SlowQA(delay=0.02)
        pipeline = build_pipeline(pipeline_config, comfyui=comfy, qa=qa, store=JobStore(tmp_path / "jobs"))
        result = await pipeline.execute(sample_workflow)
        assert result.status is PipelineState.COMPLETED
        assert qa.peak == 4

    @pytest.mark.asyncio
    async def test_qa_criteria_from_template(self, pipeline_config, sample_workflow, tmp_path):
        pipeline_config.template = {"qa_criteria": "no extra fingers"}
        qa = StubQA(scores=[0.95])
        pipeline = build_pipeline(pipeline_config, qa=qa, store=JobStore(tmp_path / "jobs"))
        await pipeline.execute(sample_workflow)
        assert qa.calls[0]["criteria"] == "no extra fingers"


class TestPlanning:
    @pytest.mark.asyncio
    async def test_execute_prompt_applies_template_defaults(self, pipeline_config, tmp_path):
        director = StubDirector()
        comfy = FakeComfyUI()
        pipeline = build_pipeline(
            pipeline_config,
            comfyui=comfy,
            director=director,
            qa=StubQA(scores=[0.95]),
            store=JobStore(tmp_path / "jobs"),
        )

        result = await pipeline.execute_prompt("a hero in the rain", template="character_generation")

        assert result.status is PipelineState.COMPLETED
        assert result.prompt == "a hero in the rain"
        assert result.kind == "prompt"
        queued = comfy.queued[0]
        assert queued["3"]["inputs"]["steps"] == 30
        assert queued["3"]["inputs"]["cfg"] == 7.5
        assert queued["5"]["inputs"]["width"] == 1024
        assert "blurry" in queued["7"]["inputs"]["text"]
        assert director.calls[0]["template"]["name"] == "character_generation"

    @pytest.mark.asyncio
    async def test_plan_prompt_does_not_render(self, pipeline_config, tmp_path):
        comfy = FakeComfyUI()
        pipeline = build_pipeline(
            pipeline_config, comfyui=comfy, director=StubDirector(), store=JobStore(tmp_path / "jobs")
        )
        workflow = await pipeline.plan_prompt("a hero")
        assert "9" in workflow
        assert comfy.queued == []

    @pytest.mark.asyncio
    async def test_assets_are_used_when_enabled(self, pipeline_config, tmp_path):
        assets = StubAssets()
        director = StubDirector()
        pipeline = build_pipeline(
            pipeline_config,
            director=director,
            assets=assets,
            qa=StubQA(scores=[0.95]),
            store=JobStore(tmp_path / "jobs"),
        )
        await pipeline.execute_prompt(
            "a knight", template={"name": "t", "use_assets": True, "available_assets": ["knight.safetensors"]}
        )
        assert assets.calls[0]["available"] == ["knight.safetensors"]
        assert director.calls[0]["asset_hints"]["loras"][0]["name"] == "style_v1"

    @pytest.mark.asyncio
    async def test_asset_failure_is_tolerated(self, pipeline_config, tmp_path):
        assets = StubAssets(error=RuntimeError("glm down"))
        pipeline = build_pipeline(
            pipeline_config,
            assets=assets,
            qa=StubQA(scores=[0.95]),
            store=JobStore(tmp_path / "jobs"),
        )
        result = await pipeline.execute_prompt("a knight", template={"name": "t", "use_assets": True})
        assert result.status is PipelineState.COMPLETED

    @pytest.mark.asyncio
    async def test_assets_skipped_by_default(self, pipeline_config, tmp_path):
        assets = StubAssets()
        pipeline = build_pipeline(
            pipeline_config, assets=assets, qa=StubQA(), store=JobStore(tmp_path / "jobs")
        )
        await pipeline.execute_prompt("a knight")
        assert assets.calls == []

    @pytest.mark.asyncio
    async def test_execute_with_input_data_prompt(self, pipeline_config, tmp_path):
        director = StubDirector()
        pipeline = build_pipeline(
            pipeline_config, director=director, qa=StubQA(), store=JobStore(tmp_path / "jobs")
        )
        result = await pipeline.execute(None, {"prompt": "from input_data"})
        assert result.status is PipelineState.COMPLETED
        assert director.calls[0]["prompt"] == "from input_data"

    @pytest.mark.asyncio
    async def test_execute_without_anything_raises(self, pipeline_config, tmp_path):
        pipeline = build_pipeline(pipeline_config, store=JobStore(tmp_path / "jobs"))
        with pytest.raises(ValueError):
            await pipeline.execute()


class TestBatch:
    @pytest.mark.asyncio
    async def test_batch_runs_jobs_concurrently(self, pipeline_config, sample_workflow, tmp_path):
        comfy = FakeComfyUI(render_delay=0.02)
        pipeline = build_pipeline(
            pipeline_config,
            comfyui=comfy,
            qa=StubQA(scores=[0.95] * 10),
            store=JobStore(tmp_path / "jobs"),
        )
        results = await pipeline.run_batch([sample_workflow] * 6, concurrency=3)
        assert len(results) == 6
        assert all(result.status is PipelineState.COMPLETED for result in results)
        assert comfy.max_inflight == 3
        assert len({result.job_id for result in results}) == 6

    @pytest.mark.asyncio
    async def test_batch_accepts_workflow_files_and_prompts(self, pipeline_config, sample_workflow, tmp_path):
        workflow_file = tmp_path / "wf.json"
        workflow_file.write_text(json.dumps(sample_workflow))
        pipeline = build_pipeline(
            pipeline_config,
            director=StubDirector(),
            qa=StubQA(scores=[0.95] * 10),
            store=JobStore(tmp_path / "jobs"),
        )
        results = await pipeline.run_batch([str(workflow_file), "a rainy street"])
        assert [result.status for result in results] == [PipelineState.COMPLETED] * 2
        assert results[1].kind == "prompt"

    @pytest.mark.asyncio
    async def test_batch_isolates_bad_specs(self, pipeline_config, sample_workflow, tmp_path):
        pipeline = build_pipeline(
            pipeline_config, qa=StubQA(scores=[0.95]), store=JobStore(tmp_path / "jobs")
        )
        results = await pipeline.run_batch([sample_workflow, {"nothing": True}])
        assert results[0].status is PipelineState.COMPLETED
        assert results[1].status is PipelineState.FAILED
        assert "workflow" in (results[1].error or "")

    @pytest.mark.asyncio
    async def test_batch_respects_per_job_retries(self, pipeline_config, sample_workflow, tmp_path):
        pipeline = build_pipeline(
            pipeline_config, qa=StubQA(scores=[0.1]), store=JobStore(tmp_path / "jobs")
        )
        results = await pipeline.run_batch([{"workflow": sample_workflow, "max_retries": 0}])
        assert results[0].iterations == 1
        assert results[0].status is PipelineState.ESCALATED


class TestRetry:
    @pytest.mark.asyncio
    async def test_retry_uses_the_stored_workflow(self, pipeline_config, sample_workflow, tmp_path):
        store = JobStore(tmp_path / "jobs")
        comfy = FakeComfyUI()
        pipeline = build_pipeline(pipeline_config, comfyui=comfy, qa=StubQA(scores=[0.95] * 4), store=store)
        first = await pipeline.execute(sample_workflow)
        retried = await pipeline.run_retry(first.job_id)
        assert retried.status is PipelineState.COMPLETED
        assert retried.job_id != first.job_id
        assert comfy.queued[1] == sample_workflow

    @pytest.mark.asyncio
    async def test_retry_unknown_job_raises(self, pipeline_config, tmp_path):
        pipeline = build_pipeline(pipeline_config, store=JobStore(tmp_path / "jobs"))
        with pytest.raises(KeyError):
            await pipeline.run_retry("nope")

    @pytest.mark.asyncio
    async def test_retry_with_corrections_shim(self, pipeline_config, sample_workflow, tmp_path):
        pipeline = build_pipeline(
            pipeline_config, qa=StubQA(scores=[0.95]), store=JobStore(tmp_path / "jobs")
        )
        result = await pipeline.retry_with_corrections(sample_workflow, [{"score": 0.4}])
        assert result.status is PipelineState.COMPLETED
        assert result.best_score == pytest.approx(0.95)

    @pytest.mark.asyncio
    async def test_retry_reuses_stored_workflow_without_replanning(self, pipeline_config, tmp_path):
        store = JobStore(tmp_path / "jobs")
        director = StubDirector()
        pipeline = build_pipeline(
            pipeline_config, director=director, qa=StubQA(scores=[0.95] * 4), store=store
        )
        first = await pipeline.execute_prompt("a prompt job")
        retried = await pipeline.run_retry(first.job_id)
        assert retried.status is PipelineState.COMPLETED
        assert retried.kind == "retry"
        assert len(director.calls) == 1  # the planned graph was reused, not re-billed


class TestHelpers:
    def test_guess_media_type(self):
        assert guess_media_type("a.png") == "image/png"
        assert guess_media_type("a.JPG") == "image/jpeg"
        assert guess_media_type("a.webp") == "image/webp"
        assert guess_media_type("a.mp4") == "video/mp4"
        assert guess_media_type("a.unknown") == "image/png"

    def test_pipeline_uses_default_store_when_not_injected(self, tmp_path, llm_config):
        config = PipelineConfig(llm=llm_config, store_dir=str(tmp_path / "default"))
        pipeline = VFPPipeline(config, comfyui=FakeComfyUI())
        assert pipeline._store.directory == tmp_path / "default" / "jobs"
