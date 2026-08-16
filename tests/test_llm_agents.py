"""Tests for orchestrator.llm_agents — all LLM calls mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from orchestrator.llm_agents import (
    AssetManagerAgent,
    CorrectionAgent,
    DirectorAgent,
    QAInspectorAgent,
    _call_llm,
)


@pytest.mark.asyncio
@patch("orchestrator.llm_agents._call_llm", new_callable=AsyncMock)
async def test_director_plan(mock_llm, llm_config):
    mock_llm.return_value = '{"3": {"class_type": "KSampler", "inputs": {}}}'
    agent = DirectorAgent(llm_config)
    result = await agent.plan("Generate a character")
    assert "3" in result
    mock_llm.assert_awaited_once()


@pytest.mark.asyncio
@patch("orchestrator.llm_agents._call_llm", new_callable=AsyncMock)
async def test_qa_inspector(mock_llm, llm_config):
    mock_llm.return_value = '{"score": 0.85, "issues": [], "summary": "Good"}'
    agent = QAInspectorAgent(llm_config)
    result = await agent.inspect("A rendered character image")
    assert result["score"] == 0.85
    mock_llm.assert_awaited_once()


@pytest.mark.asyncio
@patch("orchestrator.llm_agents._call_llm", new_callable=AsyncMock)
async def test_asset_manager(mock_llm, llm_config):
    mock_llm.return_value = '{"loras": [{"name": "style_v1", "strength": 0.7}], "models": [], "textures": []}'
    agent = AssetManagerAgent(llm_config)
    result = await agent.find_assets("A cyberpunk scene")
    assert len(result["loras"]) == 1
    mock_llm.assert_awaited_once()


@pytest.mark.asyncio
@patch("orchestrator.llm_agents._call_llm", new_callable=AsyncMock)
async def test_correction_agent_generate_fix(mock_llm, llm_config):
    mock_llm.return_value = '{"3": {"steps": 50}}'
    agent = CorrectionAgent(llm_config)
    result = await agent.generate_fix(
        workflow={"3": {"class_type": "KSampler", "inputs": {"steps": 30}}},
        qa_report={"score": 0.3, "issues": ["artifacts"]},
    )
    assert "3" in result
    mock_llm.assert_awaited_once()


def test_correction_agent_apply_patch(llm_config):
    agent = CorrectionAgent(llm_config)
    workflow = {"3": {"class_type": "KSampler", "inputs": {"steps": 30, "cfg": 7.5}}}
    patch_data = {"3": {"steps": 50}}
    patched = agent.apply_patch(workflow, patch_data)
    assert patched["3"]["inputs"]["steps"] == 50
    assert patched["3"]["inputs"]["cfg"] == 7.5


class TestResolveApi:
    def test_anthropic(self):
        from orchestrator.llm_agents import _resolve_api
        from orchestrator.config import LLMProviderConfig

        cfg = LLMProviderConfig(model="claude-sonnet-4-20250514", api_key="key")
        url, headers = _resolve_api(cfg)
        assert "anthropic-version" in headers
        assert headers["x-api-key"] == "key"

    def test_other(self):
        from orchestrator.llm_agents import _resolve_api
        from orchestrator.config import LLMProviderConfig

        cfg = LLMProviderConfig(model="glm-4v-plus", api_key="key")
        url, headers = _resolve_api(cfg)
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer key"
