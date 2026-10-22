"""ComfyUI API client: queue, websocket monitoring, history and result download."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

from .config import ComfyUIConfig
from .utils import truncate

logger = logging.getLogger(__name__)

TERMINAL_MESSAGE_TYPES = frozenset(
    {"execution_success", "execution_error", "execution_interrupted", "execution_cancelled"}
)


class ComfyUIError(RuntimeError):
    """Raised for transport, validation and server-side ComfyUI errors."""


@dataclass(frozen=True)
class OutputImage:
    """One produced artifact, addressed exactly the way ``/view`` expects it."""

    filename: str
    subfolder: str = ""
    type: str = "output"
    node_id: str = ""

    @property
    def name(self) -> str:
        return self.filename

    def as_dict(self) -> dict[str, str]:
        return {
            "filename": self.filename,
            "subfolder": self.subfolder,
            "type": self.type,
            "node_id": self.node_id,
        }

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.filename


@dataclass
class RenderOutcome:
    """Result of waiting for one queued prompt to finish."""

    status: str  # "success" | "error" | "interrupted" | "timeout" | "unknown"
    prompt_id: str = ""
    error: str | None = None
    duration_s: float = 0.0
    messages: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "success"


def image_name(image: OutputImage | str | dict[str, Any]) -> str:
    """Normalize any artifact reference to its filename."""
    if isinstance(image, OutputImage):
        return image.filename
    if isinstance(image, dict):
        return str(image.get("filename", ""))
    return str(image)


def validate_workflow(workflow: Any) -> dict[str, Any]:
    """Reject obviously broken graphs before wasting a queue round-trip."""
    if not isinstance(workflow, dict) or not workflow:
        raise ComfyUIError("workflow must be a non-empty JSON object")
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            raise ComfyUIError(f"node {node_id} must be an object")
        if not node.get("class_type"):
            raise ComfyUIError(f"node {node_id} is missing 'class_type'")
        if not isinstance(node.get("inputs", {}), dict):
            raise ComfyUIError(f"node {node_id} has non-object 'inputs'")
    return workflow


class ComfyUIClient:
    """Async ComfyUI client with pooled HTTP, bounded concurrency and reconnecting WS."""

    def __init__(self, config: ComfyUIConfig | None = None, *, client: httpx.AsyncClient | None = None) -> None:
        self._config = config or ComfyUIConfig()
        self._client_id = self._config.client_id or str(uuid.uuid4())
        self._client = client or httpx.AsyncClient(
            base_url=self._config.base_url,
            timeout=self._config.timeout,
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
            # A corporate HTTP_PROXY must not hijack traffic to a local ComfyUI.
            trust_env=self._config.use_proxy,
            follow_redirects=self._config.follow_redirects,
        )
        self._owns_client = client is None
        self._render_semaphore = asyncio.Semaphore(self._config.max_concurrent_renders)

    # ------------------------------------------------------------------ plumbing
    @property
    def config(self) -> ComfyUIConfig:
        return self._config

    @property
    def client_id(self) -> str:
        return self._client_id

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> ComfyUIClient:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        if not params:
            return path
        return f"{path}?{urlencode({k: v for k, v in params.items() if v not in (None, '')})}"

    # ------------------------------------------------------------------ endpoints
    async def ping(self) -> bool:
        """True when ``/system_stats`` answers (used by ``vfp doctor``)."""
        try:
            response = await self._client.get("/system_stats")
            return response.status_code < 400
        except httpx.HTTPError:
            return False

    async def system_stats(self) -> dict[str, Any]:
        response = await self._client.get("/system_stats")
        response.raise_for_status()
        return response.json()

    async def upload_image(self, image: bytes, filename: str = "input.png", subfolder: str = "") -> str:
        # ComfyUI adds a unique suffix if a filename is already present.
        # Do not clobber previous takes or an unrelated artist's file.
        data: dict[str, str] = {"overwrite": "false"}
        if subfolder:
            data["subfolder"] = subfolder
        response = await self._client.post(
            "/upload/image",
            files={"image": (filename, image, "image/png")},
            data=data,
        )
        response.raise_for_status()
        payload = response.json()
        name = payload.get("name", filename)
        if payload.get("subfolder"):
            return f"{payload['subfolder']}/{name}"
        return str(name)

    async def queue_prompt(self, workflow: dict[str, Any], extra_data: dict[str, Any] | None = None) -> str:
        """Queue a workflow and return the prompt id (raises on validation errors)."""
        validate_workflow(workflow)
        payload: dict[str, Any] = {"prompt": workflow, "client_id": self._client_id}
        if extra_data:
            payload["extra_data"] = extra_data
        async with self._render_semaphore:
            response = await self._client.post("/prompt", json=payload)
        if response.status_code >= 400:
            raise ComfyUIError(
                f"ComfyUI rejected the workflow (HTTP {response.status_code}): "
                f"{truncate(response.text, 400)}"
            )
        try:
            data = response.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise ComfyUIError(f"non-JSON /prompt response: {truncate(response.text, 200)}") from exc
        if data.get("node_errors"):
            raise ComfyUIError(f"workflow node errors: {truncate(json.dumps(data['node_errors']), 400)}")
        if data.get("error"):
            detail = data.get("error")
            raise ComfyUIError(f"ComfyUI error: {truncate(json.dumps(detail) if not isinstance(detail, str) else detail, 400)}")
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(f"/prompt returned no prompt_id: {truncate(json.dumps(data), 300)}")
        return str(prompt_id)

    async def interrupt(self) -> None:
        try:
            await self._client.post("/interrupt")
        except httpx.HTTPError as exc:  # pragma: no cover - best effort
            logger.warning("interrupt failed: %s", exc)

    async def get_history(self, prompt_id: str | None = None) -> dict[str, Any]:
        path = f"/history/{prompt_id}" if prompt_id else "/history"
        response = await self._client.get(path)
        response.raise_for_status()
        return response.json()

    async def get_result(self, prompt_id: str) -> dict[str, Any]:
        data = await self.get_history(prompt_id)
        if prompt_id not in data:
            raise ComfyUIError(f"Prompt {prompt_id} not found in history")
        return data[prompt_id]

    async def history_exists(self, prompt_id: str) -> bool:
        try:
            data = await self.get_history(prompt_id)
        except (httpx.HTTPError, ValueError):
            return False
        return prompt_id in data

    async def websocket_monitor(self, prompt_id: str, timeout: float | None = None) -> AsyncIterator[dict[str, Any]]:
        """Yield websocket messages for ``prompt_id`` until a terminal event.

        Reconnects up to ``ws_reconnect_attempts`` times, keeping a single overall
        deadline so a stuck render can never hang the pipeline forever.
        """
        deadline = time.monotonic() + (timeout if timeout is not None else self._config.ws_timeout)
        ws_url = f"{self._config.ws_url}?clientId={self._client_id}"
        attempts = self._config.ws_reconnect_attempts

        for attempt in range(attempts):
            try:
                async with websockets.connect(
                    ws_url,
                    open_timeout=min(30.0, max(1.0, deadline - time.monotonic())),
                    ping_interval=20,
                    ping_timeout=20,
                    proxy=True if self._config.use_proxy else None,
                ) as socket:
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            logger.warning("websocket monitor timed out for %s", prompt_id)
                            return
                        try:
                            raw = await asyncio.wait_for(socket.recv(), timeout=remaining)
                        except TimeoutError:
                            logger.warning("websocket monitor timed out for %s", prompt_id)
                            return
                        message = _decode(raw)
                        if message is None:
                            continue
                        data = message.get("data") or {}
                        if data.get("prompt_id") not in (None, prompt_id):
                            continue
                        yield message
                        if message.get("type") in TERMINAL_MESSAGE_TYPES:
                            return
            except (TimeoutError, ConnectionClosed, InvalidStatus, OSError) as exc:
                logger.warning(
                    "websocket monitor connection issue (attempt %s/%s): %s",
                    attempt + 1,
                    attempts,
                    exc,
                )
                if attempt >= attempts - 1 or deadline - time.monotonic() <= 1:
                    return
                await asyncio.sleep(min(2.0 * (attempt + 1), max(0.0, deadline - time.monotonic())))

    async def wait_for_prompt(self, prompt_id: str, timeout: float | None = None) -> RenderOutcome:
        """Wait for a queued prompt, falling back to history when the socket dies."""
        started = time.monotonic()
        outcome = RenderOutcome(status="unknown", prompt_id=prompt_id)
        seen = 0
        try:
            async for message in self.websocket_monitor(prompt_id, timeout=timeout):
                seen += 1
                msg_type = message.get("type")
                data = message.get("data") or {}
                if msg_type == "execution_error":
                    outcome.status = "error"
                    outcome.error = _format_execution_error(data)
                    break
                if msg_type in ("execution_interrupted", "execution_cancelled"):
                    outcome.status = "interrupted"
                    outcome.error = "execution interrupted (likely OOM, cancel or node crash)"
                    break
                if msg_type == "execution_success":
                    outcome.status = "success"
                    break
                if msg_type == "executing" and data.get("node") is None:
                    # ComfyUI sent the final "nothing executing" marker for this prompt.
                    outcome.status = "success"
                    break
                if msg_type == "status" and data.get("status", {}).get("status_str") == "error":
                    outcome.status = "error"
                    outcome.error = truncate(json.dumps(data), 400)
                    break
        except Exception as exc:  # noqa: BLE001 - socket layer must never crash a job
            logger.warning("websocket monitoring failed for %s: %s", prompt_id, exc)

        if outcome.status == "unknown":
            # Socket closed early (or never connected): ask history before giving up.
            try:
                result = await self.get_result(prompt_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("history fallback failed for %s: %s", prompt_id, exc)
            else:
                status = (result.get("status") or {}).get("status_str")
                if status == "success":
                    outcome.status = "success"
                elif status == "error":
                    outcome.status = "error"
                    outcome.error = _format_history_error(result)
                elif result.get("outputs"):
                    outcome.status = "success"

        outcome.messages = seen
        outcome.duration_s = round(time.monotonic() - started, 3)
        return outcome

    async def get_output_images(self, prompt_id: str) -> list[OutputImage]:
        result = await self.get_result(prompt_id)
        images: list[OutputImage] = []
        for node_id, node_output in (result.get("outputs") or {}).items():
            if not isinstance(node_output, dict):
                continue
            for key in ("images", "gifs", "videos"):
                for item in node_output.get(key) or []:
                    if not isinstance(item, dict) or not item.get("filename"):
                        continue
                    images.append(
                        OutputImage(
                            filename=str(item["filename"]),
                            subfolder=str(item.get("subfolder", "") or ""),
                            type=str(item.get("type", "output") or "output"),
                            node_id=str(node_id),
                        )
                    )
        return images

    async def download_image(
        self,
        image: OutputImage | str | dict[str, Any],
        *,
        subfolder: str = "",
        type: str = "output",
        retries: int = 2,
    ) -> bytes:
        if isinstance(image, OutputImage):
            params = {"filename": image.filename, "subfolder": image.subfolder, "type": image.type}
        elif isinstance(image, dict):
            params = {
                "filename": image.get("filename", ""),
                "subfolder": image.get("subfolder", ""),
                "type": image.get("type", "output"),
            }
        else:
            params = {"filename": str(image), "subfolder": subfolder, "type": type}

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                response = await self._client.get("/view", params=params)
                response.raise_for_status()
                return response.content
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < retries:
                    await asyncio.sleep(0.25 * (attempt + 1))
        raise ComfyUIError(f"could not download {params['filename']}: {last_error}")

    async def get_queue(self) -> dict[str, Any]:
        response = await self._client.get("/queue")
        response.raise_for_status()
        return response.json()


def _decode(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:  # pragma: no cover - ComfyUI sends JSON text frames
            return None
    if not isinstance(raw, str):
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _format_execution_error(data: dict[str, Any]) -> str:
    parts = [
        str(data.get("exception_type", "ExecutionError")),
        str(data.get("exception_message", "")),
    ]
    node_id = data.get("node_id")
    if node_id is not None:
        parts.append(f"node={node_id}")
    if data.get("traceback"):
        trace = data["traceback"]
        if isinstance(trace, list):
            trace = "".join(str(line) for line in trace)
        parts.append(truncate(str(trace), 800))
    return " | ".join(part for part in parts if part)


def _format_history_error(result: dict[str, Any]) -> str:
    messages = (result.get("status") or {}).get("messages") or []
    for entry in reversed(messages):
        if isinstance(entry, list) and entry and entry[0] == "execution_error":
            payload = entry[1] if len(entry) > 1 and isinstance(entry[1], dict) else {}
            return _format_execution_error(payload)
    return "execution failed (see ComfyUI logs)"


__all__ = [
    "ComfyUIError",
    "ComfyUIClient",
    "OutputImage",
    "RenderOutcome",
    "image_name",
    "validate_workflow",
]
