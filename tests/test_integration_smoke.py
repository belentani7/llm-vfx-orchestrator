"""End-to-end smoke test against a real HTTP + websocket server (ComfyUI stand-in).

No mocking of the network stack: the real ComfyUIClient talks to a real HTTP server and a
real websocket server over localhost, so URL building, payload shape, websocket framing and
the /history + /view fallbacks are exercised for real.
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import httpx
import pytest
import websockets

from orchestrator.comfyui_client import ComfyUIClient
from orchestrator.config import ComfyUIConfig, LLMConfig, LLMProviderConfig, PipelineConfig
from orchestrator.pipeline import VFPPipeline
from orchestrator.state import PipelineState
from orchestrator.store import JobStore

PROMPT_ID = "p1"
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)


class _State:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, bytes]] = []


STATE = _State()


class FakeComfyHandler(BaseHTTPRequestHandler):
    """Minimal ComfyUI HTTP surface: /prompt, /history, /view, /system_stats, /interrupt."""

    def log_message(self, *args) -> None:  # keep pytest output clean
        return None

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        STATE.requests.append(("POST", self.path, body))
        if self.path == "/prompt":
            self._send_json({"prompt_id": PROMPT_ID})
        elif self.path == "/interrupt":
            self._send_json({})
        else:
            self._send_json({"error": "unknown"}, status=404)

    def do_GET(self) -> None:  # noqa: N802
        STATE.requests.append(("GET", self.path, b""))
        if self.path.startswith("/history/"):
            self._send_json(
                {
                    PROMPT_ID: {
                        "status": {"status_str": "success", "completed": True, "messages": []},
                        "outputs": {
                            "9": {
                                "images": [
                                    {"filename": "out_001.png", "subfolder": "shots", "type": "output"}
                                ]
                            }
                        },
                    }
                }
            )
        elif self.path.startswith("/view"):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(PNG_BYTES)))
            self.end_headers()
            self.wfile.write(PNG_BYTES)
        elif self.path == "/system_stats":
            self._send_json({"devices": [{"name": "FakeGPU", "vram_total": 1024, "vram_free": 512}]})
        elif self.path == "/queue":
            self._send_json({"queue_running": [], "queue_pending": []})
        else:
            self._send_json({}, status=404)


async def _ws_handler(socket) -> None:
    """Push the real ComfyUI event sequence for one prompt."""
    await socket.send(json.dumps({"type": "status", "data": {"prompt_id": PROMPT_ID, "status": {}}}))
    await socket.send(
        json.dumps({"type": "executing", "data": {"prompt_id": PROMPT_ID, "node": "9"}})
    )
    await asyncio.sleep(0.01)
    await socket.send(json.dumps({"type": "execution_success", "data": {"prompt_id": PROMPT_ID}}))
    await asyncio.sleep(0.2)  # give the client time to close cleanly


@pytest.mark.asyncio
async def test_full_pipeline_against_real_servers(tmp_path, monkeypatch, sample_workflow):
    STATE.requests = []

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeComfyHandler)
    http_port = httpd.server_address[1]
    http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    http_thread.start()

    ws_server = await websockets.serve(_ws_handler, "127.0.0.1", 0)
    ws_port = ws_server.sockets[0].getsockname()[1]

    # Only the websocket URI is remapped to the port the async test server uses.
    def remap(url, **kwargs):
        return websockets.connect(f"ws://127.0.0.1:{ws_port}/ws", **kwargs)

    monkeypatch.setattr("orchestrator.comfyui_client.websockets.connect", remap)

    config = PipelineConfig(
        qa_threshold=0.8,
        llm=LLMConfig(
            claude=LLMProviderConfig(model="claude-sonnet-4-20250514", api_key="k"),
            qwen=LLMProviderConfig(model="qwen-vl-max", api_key="k"),
            glm=LLMProviderConfig(model="glm-4v-plus", api_key="k"),
        ),
        comfyui=ComfyUIConfig(host="127.0.0.1", port=http_port, ws_timeout=15),
        store_dir=str(tmp_path / "store"),
    )

    llm_calls: list[dict] = []

    async def fake_llm(provider, system, user_message, max_tokens=None, **kwargs):
        llm_calls.append({"model": provider.model, "image": kwargs.get("image"), "prompt": user_message})
        return json.dumps({"score": 0.93, "issues": [], "summary": "looks good"})

    client = ComfyUIClient(config.comfyui)
    try:
        with patch("orchestrator.llm_agents._call_llm", new=fake_llm):
            pipeline = VFPPipeline(config, comfyui=client, store=JobStore(tmp_path / "store" / "jobs"))
            result = await pipeline.execute(sample_workflow)
    finally:
        await client.close()
        ws_server.close()
        await ws_server.wait_closed()
        httpd.shutdown()

    # --- job outcome ---------------------------------------------------------
    assert result.status is PipelineState.COMPLETED
    assert result.outputs == ["out_001.png"]
    assert result.score == pytest.approx(0.93)
    assert result.iterations == 1

    # --- the QA model really received the rendered pixels ---------------------
    assert len(llm_calls) == 1
    assert llm_calls[0]["image"] == PNG_BYTES
    assert "out_001.png" in llm_calls[0]["prompt"]

    # --- the render was queued with the workflow we asked for ----------------
    posts = [request for request in STATE.requests if request[0] == "POST" and request[1] == "/prompt"]
    assert len(posts) == 1
    assert json.loads(posts[0][2].decode())["prompt"] == sample_workflow

    # --- subfolder/type were forwarded to /view ------------------------------
    views = [request for request in STATE.requests if request[0] == "GET" and request[1].startswith("/view")]
    assert views, "the pipeline must download the render via /view"
    assert "filename=out_001.png" in views[0][1]
    assert "subfolder=shots" in views[0][1]
    assert "type=output" in views[0][1]

    # --- persisted for status/retry -----------------------------------------
    record = JobStore(tmp_path / "store" / "jobs").get(result.job_id)
    assert record["status"] == "completed"
    assert record["transitions"][-1]["to"] == "completed"


@pytest.mark.asyncio
async def test_doctor_style_ping_against_real_server(tmp_path):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeComfyHandler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    client = ComfyUIClient(ComfyUIConfig(host="127.0.0.1", port=port))
    try:
        assert await client.ping() is True
        stats = await client.system_stats()
        assert stats["devices"][0]["name"] == "FakeGPU"
        assert (await client.get_queue())["queue_running"] == []
    finally:
        await client.close()
        httpd.shutdown()


@pytest.mark.asyncio
async def test_unreachable_server_reports_cleanly():
    client = ComfyUIClient(ComfyUIConfig(host="127.0.0.1", port=1, timeout=1))
    try:
        assert await client.ping() is False
        with pytest.raises(httpx.TransportError):
            await client.queue_prompt({"3": {"class_type": "X", "inputs": {}}})
    finally:
        await client.close()
