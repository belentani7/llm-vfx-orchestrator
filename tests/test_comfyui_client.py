"""Tests for orchestrator.comfyui_client (HTTP via MockTransport, WS via fake socket)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from websockets.exceptions import ConnectionClosed

from orchestrator.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
    OutputImage,
    image_name,
    validate_workflow,
)
from orchestrator.config import ComfyUIConfig

WORKFLOW = {"3": {"class_type": "KSampler", "inputs": {"steps": 20}}}


def make_client(handler, **config_kwargs) -> ComfyUIClient:
    transport = httpx.MockTransport(handler)
    return ComfyUIClient(
        ComfyUIConfig(**config_kwargs),
        client=httpx.AsyncClient(base_url="http://comfy.test", transport=transport),
    )


class FakeSocket:
    def __init__(self, messages: list[dict]):
        self._messages = [json.dumps(message) for message in messages]

    async def recv(self):
        if not self._messages:
            raise ConnectionClosed(None, None)
        return self._messages.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class TestValidation:
    def test_rejects_non_mapping(self):
        with pytest.raises(ComfyUIError):
            validate_workflow([])

    def test_rejects_empty(self):
        with pytest.raises(ComfyUIError):
            validate_workflow({})

    def test_rejects_node_without_class_type(self):
        with pytest.raises(ComfyUIError, match="class_type"):
            validate_workflow({"3": {"inputs": {}}})

    def test_rejects_bad_inputs(self):
        with pytest.raises(ComfyUIError, match="inputs"):
            validate_workflow({"3": {"class_type": "X", "inputs": []}})

    def test_accepts_valid(self):
        assert validate_workflow(WORKFLOW) is WORKFLOW


class TestHttpEndpoints:
    @pytest.mark.asyncio
    async def test_queue_prompt_sends_client_id(self):
        seen: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"prompt_id": "abc"})

        client = make_client(handler)
        assert await client.queue_prompt(WORKFLOW) == "abc"
        assert seen[0]["client_id"] == client.client_id
        assert seen[0]["prompt"] == WORKFLOW

    @pytest.mark.asyncio
    async def test_http_error_is_reported_with_server_text(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text='{"error": "invalid prompt"}')

        client = make_client(handler)
        with pytest.raises(ComfyUIError, match="invalid prompt"):
            await client.queue_prompt(WORKFLOW)

    @pytest.mark.asyncio
    async def test_node_errors_are_reported(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"prompt_id": "abc", "node_errors": {"3": "missing model"}})

        client = make_client(handler)
        with pytest.raises(ComfyUIError, match="node errors"):
            await client.queue_prompt(WORKFLOW)

    @pytest.mark.asyncio
    async def test_missing_prompt_id_is_an_error(self):
        client = make_client(lambda request: httpx.Response(200, json={}))
        with pytest.raises(ComfyUIError, match="prompt_id"):
            await client.queue_prompt(WORKFLOW)

    @pytest.mark.asyncio
    async def test_get_result_missing_prompt(self):
        client = make_client(lambda request: httpx.Response(200, json={"other": {}}))
        with pytest.raises(ComfyUIError, match="not found in history"):
            await client.get_result("abc")

    @pytest.mark.asyncio
    async def test_get_output_images_collects_files_and_metadata(self):
        payload = {
            "abc": {
                "outputs": {
                    "9": {
                        "images": [
                            {"filename": "a.png", "subfolder": "sub", "type": "output"},
                            {"filename": "b.png"},
                        ],
                        "gifs": [{"filename": "anim.gif", "subfolder": "", "type": "temp"}],
                    },
                    "10": "not-a-dict",
                }
            }
        }
        client = make_client(lambda request: httpx.Response(200, json=payload))
        images = await client.get_output_images("abc")
        assert [image.filename for image in images] == ["a.png", "b.png", "anim.gif"]
        assert images[0].subfolder == "sub"
        assert images[0].node_id == "9"
        assert images[2].type == "temp"
        assert image_name(images[0]) == "a.png"

    @pytest.mark.asyncio
    async def test_output_image_as_dict(self):
        assert OutputImage("a.png", "sub").as_dict() == {
            "filename": "a.png",
            "subfolder": "sub",
            "type": "output",
            "node_id": "",
        }

    @pytest.mark.asyncio
    async def test_download_image_uses_subfolder_and_type(self):
        urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            urls.append(str(request.url))
            return httpx.Response(200, content=b"bytes")

        client = make_client(handler)
        data = await client.download_image(OutputImage("a.png", "sub", "temp"))
        assert data == b"bytes"
        assert "filename=a.png" in urls[0]
        assert "subfolder=sub" in urls[0]
        assert "type=temp" in urls[0]

    @pytest.mark.asyncio
    async def test_download_image_retries_then_succeeds(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] == 1:
                return httpx.Response(500, text="not ready")
            return httpx.Response(200, content=b"pngext")

        client = make_client(handler)
        assert await client.download_image("a.png") == b"pngext"
        assert attempts["n"] == 2

    @pytest.mark.asyncio
    async def test_download_image_failure_raises(self):
        client = make_client(lambda request: httpx.Response(404, text="gone"))
        with pytest.raises(ComfyUIError, match="could not download"):
            await client.download_image("a.png")

    @pytest.mark.asyncio
    async def test_upload_image_returns_subfolder_path(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert b"upload.png" in request.content
            return httpx.Response(200, json={"name": "upload.png", "subfolder": "in"})

        client = make_client(handler)
        assert await client.upload_image(b"data", "upload.png") == "in/upload.png"

    @pytest.mark.asyncio
    async def test_interrupt_is_best_effort(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no server")

        client = make_client(handler)
        await client.interrupt()  # must not raise

    @pytest.mark.asyncio
    async def test_ping(self):
        ok = make_client(lambda request: httpx.Response(200, json={"devices": []}))
        assert await ok.ping() is True

        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("nope")

        assert await make_client(boom).ping() is False

    @pytest.mark.asyncio
    async def test_system_stats(self):
        client = make_client(lambda request: httpx.Response(200, json={"devices": [{"name": "RTX"}]}))
        assert (await client.system_stats())["devices"][0]["name"] == "RTX"


class TestWebsocketMonitoring:
    @pytest.mark.asyncio
    async def test_monitor_stops_on_execution_success(self, monkeypatch):
        messages = [
            {"type": "status", "data": {"prompt_id": "p1"}},
            {"type": "execution_start", "data": {"prompt_id": "p1"}},
            {"type": "execution_success", "data": {"prompt_id": "p1"}},
            {"type": "progress", "data": {"prompt_id": "p1"}},
        ]
        monkeypatch.setattr(
            "orchestrator.comfyui_client.websockets.connect", lambda *a, **k: FakeSocket(messages)
        )
        client = make_client(lambda request: httpx.Response(200, json={}))
        seen = [message["type"] async for message in client.websocket_monitor("p1")]
        assert seen == ["status", "execution_start", "execution_success"]

    @pytest.mark.asyncio
    async def test_monitor_filters_other_prompts(self, monkeypatch):
        messages = [
            {"type": "progress", "data": {"prompt_id": "other"}},
            {"type": "execution_success", "data": {"prompt_id": "p1"}},
        ]
        monkeypatch.setattr(
            "orchestrator.comfyui_client.websockets.connect", lambda *a, **k: FakeSocket(messages)
        )
        client = make_client(lambda request: httpx.Response(200, json={}))
        assert [m["type"] async for m in client.websocket_monitor("p1")] == ["execution_success"]

    @pytest.mark.asyncio
    async def test_monitor_reconnects_and_gives_up(self, monkeypatch):
        attempts = {"n": 0}
        messages = [
            {"type": "progress", "data": {"prompt_id": "p1"}},
            {"type": "execution_success", "data": {"prompt_id": "p1"}},
        ]

        def fake_connect(*args, **kwargs):
            attempts["n"] += 1
            return FakeSocket(messages if attempts["n"] > 1 else [])

        monkeypatch.setattr("orchestrator.comfyui_client.websockets.connect", fake_connect)
        monkeypatch.setattr("orchestrator.comfyui_client.asyncio.sleep", _no_sleep)
        client = make_client(lambda request: httpx.Response(200, json={}), ws_reconnect_attempts=2)
        seen = [m["type"] async for m in client.websocket_monitor("p1")]
        assert seen == ["progress", "execution_success"]
        assert attempts["n"] == 2

    @pytest.mark.asyncio
    async def test_monitor_returns_when_attempts_exhausted(self, monkeypatch):
        monkeypatch.setattr(
            "orchestrator.comfyui_client.websockets.connect", lambda *a, **k: FakeSocket([])
        )
        monkeypatch.setattr("orchestrator.comfyui_client.asyncio.sleep", _no_sleep)
        client = make_client(lambda request: httpx.Response(200, json={}), ws_reconnect_attempts=2)
        assert [m async for m in client.websocket_monitor("p1")] == []

    @pytest.mark.asyncio
    async def test_monitor_ignores_non_json_frames(self, monkeypatch):
        class MixedSocket(FakeSocket):
            def __init__(self):
                super().__init__([{"type": "execution_success", "data": {"prompt_id": "p1"}}])

            async def recv(self):
                if not self._messages:
                    raise ConnectionClosed(None, None)
                if self._messages:
                    return "not json" if len(self._messages) > 1 else self._messages.pop(0)
                return "not json"

        monkeypatch.setattr(
            "orchestrator.comfyui_client.websockets.connect", lambda *a, **k: MixedSocket()
        )
        client = make_client(lambda request: httpx.Response(200, json={}))
        assert [m["type"] async for m in client.websocket_monitor("p1")] == ["execution_success"]


async def _no_sleep(_delay):
    return None


async def _empty_monitor(prompt_id, timeout=None):
    if False:  # pragma: no cover - makes this an async generator
        yield {}


class TestWaitForPrompt:
    @pytest.mark.asyncio
    async def test_success_via_executing_none(self, monkeypatch):
        client = make_client(lambda request: httpx.Response(200, json={}))

        async def monitor(prompt_id, timeout=None):
            yield {"type": "executing", "data": {"prompt_id": prompt_id, "node": "9"}}
            yield {"type": "executing", "data": {"prompt_id": prompt_id, "node": None}}

        monkeypatch.setattr(client, "websocket_monitor", monitor)
        outcome = await client.wait_for_prompt("p1")
        assert outcome.status == "success"
        assert outcome.ok is True
        assert outcome.messages == 2

    @pytest.mark.asyncio
    async def test_error_message_is_descriptive(self, monkeypatch):
        client = make_client(lambda request: httpx.Response(200, json={}))

        async def monitor(prompt_id, timeout=None):
            yield {
                "type": "execution_error",
                "data": {
                    "prompt_id": prompt_id,
                    "node_id": "4",
                    "exception_type": "RuntimeError",
                    "exception_message": "CUDA out of memory",
                    "traceback": ["line1\n", "line2\n"],
                },
            }

        monkeypatch.setattr(client, "websocket_monitor", monitor)
        outcome = await client.wait_for_prompt("p1")
        assert outcome.status == "error"
        assert "CUDA out of memory" in (outcome.error or "")
        assert "node=4" in (outcome.error or "")

    @pytest.mark.asyncio
    async def test_interrupted(self, monkeypatch):
        client = make_client(lambda request: httpx.Response(200, json={}))

        async def monitor(prompt_id, timeout=None):
            yield {"type": "execution_interrupted", "data": {"prompt_id": prompt_id}}

        monkeypatch.setattr(client, "websocket_monitor", monitor)
        outcome = await client.wait_for_prompt("p1")
        assert outcome.status == "interrupted"
        assert outcome.ok is False

    @pytest.mark.asyncio
    async def test_history_fallback_after_socket_loss(self, monkeypatch):
        payload = {"p1": {"status": {"status_str": "success"}, "outputs": {"9": {"images": []}}}}
        client = make_client(lambda request: httpx.Response(200, json=payload))
        monkeypatch.setattr(client, "websocket_monitor", _empty_monitor)
        outcome = await client.wait_for_prompt("p1")
        assert outcome.status == "success"

    @pytest.mark.asyncio
    async def test_history_fallback_reports_error(self, monkeypatch):
        payload = {
            "p1": {
                "status": {
                    "status_str": "error",
                    "messages": [
                        ["execution_error", {"exception_message": "model not found", "node_id": "4"}],
                    ],
                }
            }
        }
        client = make_client(lambda request: httpx.Response(200, json=payload))
        monkeypatch.setattr(client, "websocket_monitor", _empty_monitor)
        outcome = await client.wait_for_prompt("p1")
        assert outcome.status == "error"
        assert "model not found" in (outcome.error or "")

    @pytest.mark.asyncio
    async def test_unknown_when_nothing_is_known(self, monkeypatch):
        client = make_client(lambda request: httpx.Response(404, json={}))
        monkeypatch.setattr(client, "websocket_monitor", _empty_monitor)
        outcome = await client.wait_for_prompt("p1")
        assert outcome.status == "unknown"
        assert outcome.ok is False


class TestRenderSerialization:
    @pytest.mark.asyncio
    async def test_render_semaphore_limits_inflight_posts(self):
        inflight = 0
        peak = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal inflight, peak
            inflight += 1
            peak = max(peak, inflight)
            await asyncio.sleep(0.02)
            inflight -= 1
            return httpx.Response(200, json={"prompt_id": "x"})

        client = make_client(handler, max_concurrent_renders=2)
        async with asyncio.TaskGroup() as group:
            for _ in range(6):
                group.create_task(client.queue_prompt(WORKFLOW))
        assert peak == 2
