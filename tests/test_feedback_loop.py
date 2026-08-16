"""Tests for orchestrator.feedback_loop."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from orchestrator.feedback_loop import FeedbackLoop, CorrectionPlan
from orchestrator.config import PipelineConfig


class TestFeedbackLoop:
    def test_should_retry_below_threshold(self, pipeline_config):
        loop = FeedbackLoop(pipeline_config)
        assert loop.should_retry({"score": 0.5}, attempt=0) is True

    def test_should_not_retry_at_max(self, pipeline_config):
        loop = FeedbackLoop(pipeline_config)
        assert loop.should_retry({"score": 0.5}, attempt=3) is False

    def test_should_not_retry_above_threshold(self, pipeline_config):
        loop = FeedbackLoop(pipeline_config)
        assert loop.should_retry({"score": 0.9}, attempt=0) is False

    def test_should_escalate_at_max(self, pipeline_config):
        loop = FeedbackLoop(pipeline_config)
        assert loop.should_escalate({"score": 0.4}, attempt=3) is True

    def test_should_not_escalate_below_max(self, pipeline_config):
        loop = FeedbackLoop(pipeline_config)
        assert loop.should_escalate({"score": 0.4}, attempt=2) is False

    def test_should_not_escalate_when_passing(self, pipeline_config):
        loop = FeedbackLoop(pipeline_config)
        assert loop.should_escalate({"score": 0.9}, attempt=3) is False

    def test_apply_correction_empty_patch(self, pipeline_config):
        loop = FeedbackLoop(pipeline_config)
        plan = CorrectionPlan(patch={}, reason="no issues")
        wf = {"3": {"class_type": "KSampler", "inputs": {"steps": 30}}}
        result = loop.apply_correction(plan, wf)
        assert result["3"]["inputs"]["steps"] == 30

    def test_apply_correction_with_patch(self, pipeline_config):
        loop = FeedbackLoop(pipeline_config)
        plan = CorrectionPlan(patch={"3": {"steps": 50}}, reason="too few steps")
        wf = {"3": {"class_type": "KSampler", "inputs": {"steps": 30}}}
        result = loop.apply_correction(plan, wf)
        assert result["3"]["inputs"]["steps"] == 50


class TestAnalyzeFailure:
    @pytest.mark.asyncio
    async def test_above_threshold(self, pipeline_config):
        loop = FeedbackLoop(pipeline_config)
        plan = await loop.analyze_failure({"score": 0.9, "summary": "good"})
        assert plan.patch == {}

    @pytest.mark.asyncio
    async def test_below_threshold(self, pipeline_config):
        loop = FeedbackLoop(pipeline_config)
        loop._agent.generate_fix = AsyncMock(return_value={"3": {"steps": 50}})
        plan = await loop.analyze_failure({"score": 0.3, "issues": ["artifacts"], "summary": "bad"})
        assert "3" in plan.patch
        assert plan.reason == "bad"
