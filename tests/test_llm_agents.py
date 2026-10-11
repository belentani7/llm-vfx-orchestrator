"""Tests for orchestrator.llm_agents — HTTP layer exercised with MockTransport."""

from __future__ import annotations

import asyncio
import base64
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from orchestrator.config import LLMConfig, LLMProviderConfig
from orchestrator.llm_agents import (
    KIND_ANTHROPIC,
    KIND_DASHSCOPE,
    KIND_OPENAI,
    AssetManagerAgent,
    CorrectionAgent,
    DirectorAgent,
    LLMError,
    QAInspectorAgent,
    _call_llm,
    aclose_clients,
    build_payload,
    call_provider_chain,
    detect_kind,
    normalize_qa_report,
    parse_response,
    resolve_endpoint,
)

IMG = b"\x89PNG-fake"


def transport(responses, calls=None):
    """MockTransport that pops responses and records requests."""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            body = json.loads(request.content.decode() or "{}")
            calls.append({"url": str(request.url), "headers": dict(request.headers), "body": body})
        item = queue.pop(0) if queue else httpx.Response(200, json={"ok": True})
        if isinstance(item, httpx.Response):
            return item
        status, payload = item
        headers = {}
        if isinstance(payload, tuple):  # (payload, headers)
            payload, headers = payload
        return httpx.Response(status, json=payload, headers=headers)

    return httpx.MockTransport(handler)


def client_for(responses, calls=None) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport(responses, calls))


def anthropic_response(text: str = "ok") -> tuple[int, dict]:
    return 200, {"content": [{"type": "text", "text": text}]}


def openai_response(text: str = "ok") -> tuple[int, dict]:
    return 200, {"choices": [{"message": {"role": "assistant", "content": text}}]}


def dashscope_response(text: str = "ok") -> tuple[int, dict]:
    return 200, {"output": {"choices": [{"message": {"content": [{"text": text}]}}]}}


class TestProtocolDetection:
    @pytest.mark.parametrize(
        ("provider", "expected"),
        [
            (LLMProviderConfig(model="claude-sonnet-4-20250514"), KIND_ANTHROPIC),
            (LLMProviderConfig(model="qwen-vl-max"), KIND_DASHSCOPE),
            (LLMProviderConfig(model="glm-4v-plus"), KIND_OPENAI),
            (LLMProviderConfig(model="anything", base_url="https://api.anthropic.com"), KIND_ANTHROPIC),
            (
                LLMProviderConfig(model="qwen-vl-max", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"),
                KIND_OPENAI,
            ),
            (LLMProviderConfig(model="llama3", base_url="http://127.0.0.1:11434"), KIND_OPENAI),
            (LLMProviderConfig(model="custom", kind="anthropic", base_url="https://proxy"), KIND_ANTHROPIC),
            (LLMProviderConfig(model="custom", kind="glm"), KIND_OPENAI),
        ],
    )
    def test_detect_kind(self, provider, expected):
        assert detect_kind(provider) == expected

    def test_anthropic_endpoint_default(self):
        endpoint = resolve_endpoint(LLMProviderConfig(model="claude-sonnet-4-20250514", api_key="k"))
        assert endpoint.url == "https://api.anthropic.com/v1/messages"
        assert endpoint.headers["x-api-key"] == "k"
        assert endpoint.headers["anthropic-version"] == "2023-06-01"

    def test_dashscope_native_endpoint(self):
        endpoint = resolve_endpoint(LLMProviderConfig(model="qwen-vl-max", api_key="k"))
        assert endpoint.url.endswith("/services/aigc/multimodal-generation/generation")

    def test_glm_endpoint_default(self):
        endpoint = resolve_endpoint(LLMProviderConfig(model="glm-4v-plus", api_key="k"))
        assert endpoint.url == "https://open.bigmodel.cn/api/paas/v4/chat/completions"

    def test_openai_endpoint_gets_version(self):
        endpoint = resolve_endpoint(LLMProviderConfig(model="gpt-4o", base_url="https://api.openai.com", api_key="k"))
        assert endpoint.url == "https://api.openai.com/v1/chat/completions"

    def test_explicit_chat_completions_url_is_kept(self):
        provider = LLMProviderConfig(
            model="local", base_url="http://host:8000/v1/chat/completions", api_key="k"
        )
        assert resolve_endpoint(provider).url == "http://host:8000/v1/chat/completions"

    def test_dashscope_compatible_mode_uses_chat_completions(self):
        provider = LLMProviderConfig(
            model="qwen-vl-plus",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="k",
        )
        assert resolve_endpoint(provider).url.endswith("/compatible-mode/v1/chat/completions")


class TestPayloadsAndParsing:
    def test_anthropic_payload_with_image(self):
        endpoint = resolve_endpoint(LLMProviderConfig(model="claude-sonnet-4-20250514", api_key="k"))
        payload = build_payload(endpoint, "sys", "hello", 128, image=IMG, image_media_type="image/png")
        assert payload["system"] == "sys"
        assert payload["max_tokens"] == 128
        blocks = payload["messages"][0]["content"]
        assert blocks[0] == {"type": "text", "text": "hello"}
        assert blocks[1]["type"] == "image"
        assert blocks[1]["source"]["media_type"] == "image/png"
        assert base64.b64decode(blocks[1]["source"]["data"]) == IMG

    def test_openai_payload_with_image(self):
        endpoint = resolve_endpoint(LLMProviderConfig(model="glm-4v-plus", api_key="k"))
        payload = build_payload(endpoint, "sys", "hello", 128, image=IMG)
        assert payload["messages"][0] == {"role": "system", "content": "sys"}
        content = payload["messages"][1]["content"]
        assert content[0]["type"] == "text"
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")

    def test_dashscope_payload_with_image(self):
        endpoint = resolve_endpoint(LLMProviderConfig(model="qwen-vl-max", api_key="k"))
        payload = build_payload(endpoint, "sys", "hello", 128, image=IMG)
        content = payload["input"]["messages"][0]["content"]
        assert content[0]["image"].startswith("data:image/png;base64,")
        assert content[1] == {"text": "hello"}
        assert payload["parameters"]["max_tokens"] == 128

    def test_openai_payload_text_only(self):
        endpoint = resolve_endpoint(LLMProviderConfig(model="glm-4v-plus", api_key="k"))
        payload = build_payload(endpoint, "sys", "hello", 10)
        assert payload["messages"][1]["content"] == "hello"

    def test_parse_response_anthropic_string_content(self):
        assert parse_response(KIND_ANTHROPIC, {"content": "plain"}) == "plain"

    def test_parse_response_openai_list_content(self):
        body = {"choices": [{"message": {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}}]}
        assert parse_response(KIND_OPENAI, body) == "a\nb"

    def test_parse_response_unknown_shape_raises(self):
        with pytest.raises(LLMError):
            parse_response(KIND_OPENAI, {"nope": 1})


class TestCallLLM:
    @pytest.mark.asyncio
    async def test_anthropic_happy_path(self):
        calls: list[dict] = []
        provider = LLMProviderConfig(model="claude-sonnet-4-20250514", api_key="key")
        async with client_for([anthropic_response("hello")], calls) as client:
            text = await _call_llm(provider, "sys", "user msg", 256, image=IMG, client=client)
        assert text == "hello"
        assert calls[0]["url"] == "https://api.anthropic.com/v1/messages"
        assert calls[0]["headers"]["x-api-key"] == "key"
        assert calls[0]["body"]["max_tokens"] == 256

    @pytest.mark.asyncio
    async def test_openai_happy_path(self):
        calls: list[dict] = []
        provider = LLMProviderConfig(model="glm-4v-plus", api_key="key")
        async with client_for([openai_response("hi")], calls) as client:
            text = await _call_llm(provider, "sys", "user msg", client=client)
        assert text == "hi"
        assert calls[0]["body"]["messages"][0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_dashscope_happy_path(self):
        calls: list[dict] = []
        provider = LLMProviderConfig(model="qwen-vl-max", api_key="key")
        async with client_for([dashscope_response("saw it")], calls) as client:
            text = await _call_llm(provider, "sys", "user msg", image=IMG, client=client)
        assert text == "saw it"
        assert calls[0]["body"]["input"]["messages"][0]["content"][0]["image"]

    @pytest.mark.asyncio
    async def test_retries_on_429_honoring_retry_after(self):
        calls: list[dict] = []
        provider = LLMProviderConfig(model="glm-4v-plus", api_key="key", max_retries=1)
        responses = [(429, ({"error": "rate limited"}, {"retry-after": "0"})), openai_response("second try")]
        async with client_for(responses, calls) as client:
            text = await _call_llm(provider, "sys", "user", client=client)
        assert text == "second try"
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_retries_on_5xx_with_backoff(self):
        calls: list[dict] = []
        provider = LLMProviderConfig(model="glm-4v-plus", api_key="key", max_retries=2)
        responses = [(503, {"error": "down"}), (503, {"error": "down"}), openai_response("recovered")]
        with patch("orchestrator.llm_agents.asyncio.sleep", new_callable=AsyncMock) as sleep:
            async with client_for(responses, calls) as client:
                text = await _call_llm(provider, "sys", "user", client=client)
        assert text == "recovered"
        assert sleep.await_count == 2

    @pytest.mark.asyncio
    async def test_retry_exhaustion_raises_llm_error(self):
        provider = LLMProviderConfig(model="glm-4v-plus", api_key="key", max_retries=1)
        with patch("orchestrator.llm_agents.asyncio.sleep", new_callable=AsyncMock):
            async with client_for([(500, {"error": "boom"}), (500, {"error": "boom"})]) as client:
                with pytest.raises(LLMError, match="failed after 2 attempt"):
                    await _call_llm(provider, "sys", "user", client=client)

    @pytest.mark.asyncio
    async def test_client_error_is_not_retried(self):
        calls: list[dict] = []
        provider = LLMProviderConfig(model="glm-4v-plus", api_key="key", max_retries=3)
        async with client_for([(400, {"error": "bad request"})], calls) as client:
            with pytest.raises(LLMError, match="HTTP 400"):
                await _call_llm(provider, "sys", "user", client=client)
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_transport_errors_are_retried(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise httpx.ConnectTimeout("timed out")
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        provider = LLMProviderConfig(model="glm-4v-plus", api_key="key", max_retries=1)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await _call_llm(provider, "sys", "user", client=client) == "ok"
        assert attempts["n"] == 2

    @pytest.mark.asyncio
    async def test_invalid_json_body_raises(self):
        provider = LLMProviderConfig(model="glm-4v-plus", api_key="key", max_retries=0)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"<html>"))
        ) as client:
            with pytest.raises(LLMError):
                await _call_llm(provider, "sys", "user", client=client)


class TestProviderChain:
    @pytest.mark.asyncio
    async def test_falls_back_to_second_provider(self):
        calls: list[dict] = []
        chain = [
            ("claude", LLMProviderConfig(model="glm-4v-plus", api_key="a", max_retries=0)),
            ("glm", LLMProviderConfig(model="glm-4v-plus", api_key="b", max_retries=0)),
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append({"url": str(request.url), "auth": request.headers.get("authorization")})
            if len(calls) == 1:
                return httpx.Response(500, json={"error": "down"})
            return httpx.Response(200, json={"choices": [{"message": {"content": "from fallback"}}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            text = await call_provider_chain(chain, "sys", "user", client=client)
        assert text == "from fallback"
        assert calls[1]["auth"] == "Bearer b"

    @pytest.mark.asyncio
    async def test_all_providers_failing_reports_each(self):
        chain = [
            ("claude", LLMProviderConfig(model="glm-4v-plus", api_key="a", max_retries=0)),
            ("glm", LLMProviderConfig(model="glm-4v-plus", api_key="b", max_retries=0)),
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "down"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(LLMError, match="claude: .*glm: ") as excinfo:
                await call_provider_chain(chain, "sys", "user", client=client)
        assert "all providers failed" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_empty_chain_raises(self):
        with pytest.raises(LLMError, match="no LLM provider configured"):
            await call_provider_chain([], "sys", "user")

    @pytest.mark.asyncio
    async def test_vision_disabled_provider_is_skipped(self):
        chain = [
            ("qwen", LLMProviderConfig(model="qwen-vl-max", api_key="a", vision=False)),
        ]
        with pytest.raises(LLMError, match="no vision-capable provider"):
            await call_provider_chain(chain, "sys", "user", image=IMG)

    @pytest.mark.asyncio
    async def test_aclose_clients_is_idempotent(self):
        await aclose_clients()
        await aclose_clients()

    @pytest.mark.asyncio
    async def test_provider_concurrency_is_capped(self):
        inflight = 0
        peak = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal inflight, peak
            inflight += 1
            peak = max(peak, inflight)
            try:
                await asyncio.sleep(0.02)
                return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
            finally:
                inflight -= 1

        provider = LLMProviderConfig(
            model="glm-4v-plus", api_key="k", max_concurrency=2, base_url="http://burst.test"
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await asyncio.gather(
                *[_call_llm(provider, "s", f"m{i}", client=client) for i in range(8)]
            )
        assert peak <= 2


class TestAgentPrompts:
    @pytest.mark.asyncio
    @patch("orchestrator.llm_agents._call_llm", new_callable=AsyncMock)
    async def test_director_plan(self, mock_llm, llm_config):
        mock_llm.return_value = '{"3": {"class_type": "KSampler", "inputs": {}}}'
        agent = DirectorAgent(llm_config)
        result = await agent.plan("Generate a character")
        assert "3" in result
        mock_llm.assert_awaited_once()
        assert "Generate a character" in mock_llm.await_args.args[2]

    @pytest.mark.asyncio
    @patch("orchestrator.llm_agents._call_llm", new_callable=AsyncMock)
    async def test_director_includes_template_and_assets(self, mock_llm, llm_config):
        mock_llm.return_value = '{"3": {"class_type": "KSampler", "inputs": {}}}'
        agent = DirectorAgent(llm_config)
        await agent.plan("brief", template={"name": "character", "default_steps": 30}, asset_hints={"loras": []})
        user_message = mock_llm.await_args.args[2]
        assert "default_steps" in user_message
        assert "Available assets" in user_message

    @pytest.mark.asyncio
    @patch("orchestrator.llm_agents._call_llm", new_callable=AsyncMock)
    async def test_director_rejects_empty_workflow(self, mock_llm, llm_config):
        mock_llm.return_value = "{}"
        with pytest.raises(LLMError):
            await DirectorAgent(llm_config).plan("brief")

    @pytest.mark.asyncio
    @patch("orchestrator.llm_agents._call_llm", new_callable=AsyncMock)
    async def test_json_repair_retry(self, mock_llm, llm_config):
        mock_llm.side_effect = ["Sure! Here is your JSON: not really", '{"score": 0.75}']
        agent = QAInspectorAgent(llm_config)
        report = await agent.inspect("an image")
        assert report["score"] == pytest.approx(0.75)
        assert mock_llm.await_count == 2
        assert "ONLY the JSON" in mock_llm.await_args.args[2]

    @pytest.mark.asyncio
    @patch("orchestrator.llm_agents._call_llm", new_callable=AsyncMock)
    async def test_qa_inspector(self, mock_llm, llm_config):
        mock_llm.return_value = '{"score": 0.85, "issues": [], "summary": "Good"}'
        agent = QAInspectorAgent(llm_config)
        result = await agent.inspect("A rendered character image")
        assert result["score"] == pytest.approx(0.85)
        mock_llm.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("orchestrator.llm_agents._call_llm", new_callable=AsyncMock)
    async def test_qa_inspector_attaches_image(self, mock_llm, llm_config):
        mock_llm.return_value = '{"score": 0.5, "issues": ["blur"], "summary": "meh"}'
        agent = QAInspectorAgent(llm_config)
        result = await agent.inspect("desc", "criteria", image=IMG, image_media_type="image/webp")
        assert mock_llm.await_args.kwargs["image"] == IMG
        assert mock_llm.await_args.kwargs["image_media_type"] == "image/webp"
        assert result["issues"] == ["blur"]

    @pytest.mark.asyncio
    @patch("orchestrator.llm_agents._call_llm", new_callable=AsyncMock)
    async def test_qa_inspector_normalizes_odd_scores(self, mock_llm, llm_config):
        mock_llm.return_value = '{"score": "85%", "issues": "one problem", "summary": "ok"}'
        report = await QAInspectorAgent(llm_config).inspect("desc")
        assert report["score"] == pytest.approx(0.85)
        assert report["issues"] == ["one problem"]

    @pytest.mark.asyncio
    @patch("orchestrator.llm_agents._call_llm", new_callable=AsyncMock)
    async def test_asset_manager(self, mock_llm, llm_config):
        mock_llm.return_value = (
            '{"loras": [{"name": "style_v1", "strength": 0.7}], "models": [], "textures": []}'
        )
        agent = AssetManagerAgent(llm_config)
        result = await agent.find_assets("A cyberpunk scene")
        assert len(result["loras"]) == 1
        mock_llm.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("orchestrator.llm_agents._call_llm", new_callable=AsyncMock)
    async def test_asset_manager_uses_inventory(self, mock_llm, llm_config):
        mock_llm.return_value = '{"loras": [], "models": [], "textures": []}'
        agent = AssetManagerAgent(llm_config)
        await agent.find_assets("scene", available=["a.safetensors", "b.safetensors"])
        assert "a.safetensors" in mock_llm.await_args.args[2]

    @pytest.mark.asyncio
    @patch("orchestrator.llm_agents._call_llm", new_callable=AsyncMock)
    async def test_asset_manager_without_inventory(self, mock_llm, llm_config):
        mock_llm.return_value = '{"loras": [], "models": [], "textures": []}'
        agent = AssetManagerAgent(llm_config)
        await agent.find_assets("scene")
        assert "instead of guessing" in mock_llm.await_args.args[2]

    @pytest.mark.asyncio
    @patch("orchestrator.llm_agents._call_llm", new_callable=AsyncMock)
    async def test_correction_agent_generate_fix(self, mock_llm, llm_config):
        mock_llm.return_value = '{"3": {"steps": 50}}'
        agent = CorrectionAgent(llm_config)
        result = await agent.generate_fix(
            workflow={"3": {"class_type": "KSampler", "inputs": {"steps": 30}}},
            qa_report={"score": 0.3, "issues": ["artifacts"]},
            error_log="CUDA OOM",
            prior_corrections=[{"attempt": 1, "reason": "x"}],
        )
        assert "3" in result
        user_message = mock_llm.await_args.args[2]
        assert "CUDA OOM" in user_message
        assert "do not repeat" in user_message.lower()

    @pytest.mark.asyncio
    @patch("orchestrator.llm_agents._call_llm", new_callable=AsyncMock)
    async def test_correction_agent_rejects_non_object(self, mock_llm, llm_config):
        mock_llm.return_value = "[1, 2, 3]"
        with pytest.raises(LLMError):
            await CorrectionAgent(llm_config).generate_fix({"3": {}}, {"score": 0.1})


class TestApplyPatch:
    def test_input_override(self, llm_config):
        agent = CorrectionAgent(llm_config)
        workflow = {"3": {"class_type": "KSampler", "inputs": {"steps": 30, "cfg": 7.5}}}
        patched = agent.apply_patch(workflow, {"3": {"steps": 50}})
        assert patched["3"]["inputs"]["steps"] == 50
        assert patched["3"]["inputs"]["cfg"] == 7.5
        assert workflow["3"]["inputs"]["steps"] == 30  # original untouched

    def test_adds_new_nodes(self, llm_config):
        agent = CorrectionAgent(llm_config)
        patched = agent.apply_patch(
            {"3": {"class_type": "KSampler", "inputs": {}}},
            {"__new_nodes__": {"20": {"class_type": "Upscale", "inputs": {}}}},
        )
        assert patched["20"]["class_type"] == "Upscale"

    def test_removes_nodes(self, llm_config):
        agent = CorrectionAgent(llm_config)
        patched = agent.apply_patch(
            {"3": {"class_type": "A", "inputs": {}}, "4": {"class_type": "B", "inputs": {}}},
            {"__remove_nodes__": ["4"]},
        )
        assert set(patched) == {"3"}

    def test_unknown_node_is_ignored(self, llm_config):
        agent = CorrectionAgent(llm_config)
        patched = agent.apply_patch({"3": {"class_type": "A", "inputs": {}}}, {"99": {"steps": 1}})
        assert set(patched) == {"3"}

    def test_non_object_override_is_ignored(self, llm_config):
        agent = CorrectionAgent(llm_config)
        patched = agent.apply_patch({"3": {"class_type": "A", "inputs": {"steps": 5}}}, {"3": [1, 2]})
        assert patched["3"]["inputs"]["steps"] == 5

    def test_node_without_inputs_gets_them(self, llm_config):
        agent = CorrectionAgent(llm_config)
        patched = agent.apply_patch({"3": {"class_type": "A"}}, {"3": {"steps": 2}})
        assert patched["3"]["inputs"] == {"steps": 2}


class TestNormalizeQaReport:
    def test_missing_score_defaults_to_zero(self):
        assert normalize_qa_report({"issues": ["x"]})["score"] == 0.0

    def test_alternative_keys(self):
        report = normalize_qa_report({"quality": "7/10", "problems": "noise", "reason": "meh"})
        assert report["score"] == pytest.approx(0.7)
        assert report["issues"] == ["noise"]
        assert report["summary"] == "meh"

    def test_non_dict(self):
        report = normalize_qa_report("looks fine")
        assert report["score"] == 0.0
        assert report["issues"]


def test_llm_config_chain_skips_missing_keys():
    config = LLMConfig(claude=LLMProviderConfig(), fallbacks=["glm"])
    assert config.chain_for("claude") == []
