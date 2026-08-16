"""Tests for orchestrator.pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.pipeline import VFPPipeline, PipelineResult, _avg_score
from orchestrator.state import PipelineState


class TestAvgScore:
    def test_empty(self):
        assert _avg_score([]) == 0.0

    def test_single(self):
        assert _avg_score([{"score": 0.7}]) == pytest.approx(0.7)

    def test_multiple(self):
        reports = [{"score": 0.8}, {"score": 0.6}, {"score": 1.0}]
        assert _avg_score(reports) == pytest.approx(0.8)


class TestVFPPipeline:
    @pytest.mark.asyncio
    async def test_execute_success(self, pipeline_config, sample_workflow, mock_comfyui_client):
        pipeline = VFPPipeline(pipeline_config)
        pipeline._comfyui = mock_comfyui_client
        pipeline._comfyui.websocket_monitor = MagicMock()

        async def _mock_ws_iter(pid):
            yield {"type": "executed", "data": {"prompt_id": pid}}

        pipeline._comfyui.websocket_monitor.return_value = _mock_ws_iter("test")

        with patch.object(
            pipeline._qa,
            "inspect",
            new_callable=AsyncMock,
            return_value={"score": 0.9, "issues": [], "summary": "Good"},
        ):
            result = await pipeline.execute(sample_workflow)

        assert result.status == PipelineState.COMPLETED
        assert result.job_id
        assert result.outputs == ["output_001.png"]
        assert result.iterations == 1
        mock_comfyui_client.queue_prompt.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_execution_error(self, pipeline_config, sample_workflow):
        pipeline = VFPPipeline(pipeline_config)

        async def _mock_ws(pid):
            yield {"type": "execution_error", "data": {"prompt_id": pid, "exception_message": "OOM"}}

        pipeline._comfyui = MagicMock()
        pipeline._comfyui.queue_prompt = AsyncMock(return_value="p1")
        pipeline._comfyui.websocket_monitor = MagicMock(return_value=_mock_ws("p1"))

        result = await pipeline.execute(sample_workflow)
        assert result.status == PipelineState.FAILED
        assert "OOM" in (result.error or "")

    @pytest.mark.asyncio
    async def test_get_status(self, pipeline_config):
        pipeline = VFPPipeline(pipeline_config)
        assert pipeline.get_status("nonexistent") is None


class TestPipelineResult:
    def test_default_fields(self):
        r = PipelineResult(job_id="abc", status=PipelineState.PENDING)
        assert r.outputs == []
        assert r.iterations == 0
        assert r.qa_reports == []
        assert r.error is None
