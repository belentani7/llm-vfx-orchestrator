"""ComfyUI API client with async websocket monitoring."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import AsyncIterator

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from .config import ComfyUIConfig


class ComfyUIClient:
    def __init__(self, config: ComfyUIConfig | None = None) -> None:
        self._config = config or ComfyUIConfig()
        self._client = httpx.AsyncClient(
            base_url=self._config.base_url,
            timeout=self._config.timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def upload_image(self, image: bytes, filename: str = "input.png") -> str:
        resp = await self._client.post(
            "/upload/image",
            files={"image": (filename, image, "image/png")},
            data={"overwrite": "true"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["name"]

    async def queue_prompt(self, workflow: dict) -> str:
        payload = {
            "prompt": workflow,
            "client_id": str(uuid.uuid4()),
        }
        resp = await self._client.post("/prompt", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["prompt_id"]

    async def get_result(self, prompt_id: str) -> dict:
        resp = await self._client.get(f"/history/{prompt_id}")
        resp.raise_for_status()
        data = resp.json()
        if prompt_id not in data:
            raise ValueError(f"Prompt {prompt_id} not found in history")
        return data[prompt_id]

    async def websocket_monitor(self, prompt_id: str) -> AsyncIterator[dict]:
        ws_url = f"{self._config.ws_url}?clientId={uuid.uuid4()}"
        for attempt in range(self._config.ws_reconnect_attempts):
            try:
                async with websockets.connect(ws_url) as ws:
                    async for raw in ws:
                        msg = json.loads(raw)
                        msg_type = msg.get("type")
                        msg_data = msg.get("data", {})
                        if msg_data.get("prompt_id") == prompt_id:
                            yield msg
                            if msg_type in ("executed", "execution_error"):
                                return
            except (ConnectionClosed, OSError):
                if attempt < self._config.ws_reconnect_attempts - 1:
                    await asyncio.sleep(1 * (attempt + 1))
                    continue
                raise

    async def get_output_images(self, prompt_id: str) -> list[str]:
        result = await self.get_result(prompt_id)
        outputs = result.get("outputs", {})
        images: list[str] = []
        for node_output in outputs.values():
            for img in node_output.get("images", []):
                images.append(img["filename"])
        return images

    async def download_image(self, filename: str) -> bytes:
        resp = await self._client.get(f"/view?filename={filename}")
        resp.raise_for_status()
        return resp.content
