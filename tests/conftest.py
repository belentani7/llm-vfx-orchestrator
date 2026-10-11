"""Shared fixtures: fake ComfyUI, stub agents and pipeline builders."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import replace
from typing import Any

import pytest

from orchestrator.comfyui_client import OutputImage, RenderOutcome
from orchestrator.config import ComfyUIConfig, LLMConfig, LLMProviderConfig, PipelineConfig
from orchestrator.llm_agents import CorrectionAgent, normalize_qa_report
from orchestrator.pipeline import VFPPipeline
from orchestrator.store import JobStore

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-image-data" * 8


@pytest.fixture
def llm_config() -> LLMConfig:
    return LLMConfig(
        claude=LLMProviderConfig(model="claude-sonnet-4-20250514", api_key="test-claude-key"),
        qwen=LLMProviderConfig(model="qwen-vl-max", api_key="test-qwen-key"),
        glm=LLMProviderConfig(model="glm-4v-plus", api_key="test-glm-key"),
    )


@pytest.fixture
def pipeline_config(llm_config: LLMConfig, tmp_path) -> PipelineConfig:
    return PipelineConfig(
        max_retries=3,
        qa_threshold=0.8,
        llm=llm_config,
        store_dir=str(tmp_path / "store"),
    )


@pytest.fixture
def sample_workflow() -> dict:
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 42,
                "steps": 30,
                "cfg": 7.5,
                "sampler_name": "euler_a",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "model.safetensors"},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 1024, "height": 1024, "batch_size": 1},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "a character", "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "blurry, low quality", "clip": ["4", 1]},
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "output", "images": ["8", 0]},
        },
    }


class FakeComfyUI:
    """Drop-in replacement for :class:`ComfyUIClient` with observable behaviour."""

    def __init__(
        self,
        *,
        images: list[Any] | None = None,
        outcomes: list[RenderOutcome] | None = None,
        render_delay: float = 0.0,
        download_error: Exception | None = None,
    ) -> None:
        self.config = ComfyUIConfig()
        self.client_id = "fake-client"
        self.images: list[Any] | None = images if images is not None else [OutputImage("output_001.png")]
        self.outcomes: deque[RenderOutcome] = deque(outcomes or [])
        self.render_delay = render_delay
        self.download_error = download_error
        self.queued: list[dict] = []
        self.interrupts = 0
        self.inflight = 0
        self.max_inflight = 0
        self.closed = False
        self.downloads: list[Any] = []

    async def queue_prompt(self, workflow: dict, extra_data: dict | None = None) -> str:
        self.queued.append(json.loads(json.dumps(workflow)))
        return f"prompt-{len(self.queued)}"

    async def wait_for_prompt(self, prompt_id: str, timeout: float | None = None) -> RenderOutcome:
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            if self.render_delay:
                await asyncio.sleep(self.render_delay)
            if self.outcomes:
                return replace(self.outcomes.popleft(), prompt_id=prompt_id)
            return RenderOutcome(status="success", prompt_id=prompt_id)
        finally:
            self.inflight -= 1

    async def get_output_images(self, prompt_id: str) -> list[Any]:
        return list(self.images or [])

    async def download_image(self, image: Any, **kwargs: Any) -> bytes:
        self.downloads.append(image)
        if self.download_error is not None:
            raise self.download_error
        return PNG_BYTES

    async def interrupt(self) -> None:
        self.interrupts += 1

    async def close(self) -> None:
        self.closed = True

    async def ping(self) -> bool:
        return True


class StubQA:
    """QA inspector stub: consumes a queue of scores, records every call."""

    role = "qwen"

    def __init__(self, scores: list[float] | None = None, error: Exception | None = None) -> None:
        self.scores: deque[float] = deque(scores or [])
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def inspect(
        self,
        image_description: str = "",
        criteria: str = "",
        *,
        image: bytes | None = None,
        image_media_type: str = "image/png",
        extra_context: str = "",
        client: Any = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "description": image_description,
                "criteria": criteria,
                "image": image,
                "media_type": image_media_type,
                "extra_context": extra_context,
            }
        )
        if self.error is not None:
            raise self.error
        score = self.scores.popleft() if self.scores else 0.92
        return normalize_qa_report({"score": score, "issues": [], "summary": f"stub score {score}"})


class StubDirector:
    """Director stub returning a fixed (deep-copied) workflow."""

    role = "claude"

    def __init__(self, workflow: dict | None = None) -> None:
        self.workflow = workflow or {
            "3": {"class_type": "KSampler", "inputs": {"steps": None, "cfg": None, "sampler_name": None}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": None, "height": None}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, low quality"}},
            "9": {"class_type": "SaveImage", "inputs": {}},
        }
        self.calls: list[dict[str, Any]] = []

    async def plan(self, prompt: str, *, template=None, asset_hints=None, client=None) -> dict:
        self.calls.append({"prompt": prompt, "template": template, "asset_hints": asset_hints})
        return json.loads(json.dumps(self.workflow))


class StubAssets:
    role = "glm"

    def __init__(self, result: dict | None = None, error: Exception | None = None) -> None:
        self.result = result or {"loras": [{"name": "style_v1", "strength": 0.7}], "models": [], "textures": []}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def find_assets(self, description: str, *, available=None, client=None) -> dict:
        self.calls.append({"description": description, "available": available})
        if self.error is not None:
            raise self.error
        return self.result


class StubCorrection(CorrectionAgent):
    """Real patch application, scripted patches."""

    def __init__(self, config: LLMConfig, patches: list[dict] | None = None, error: Exception | None = None) -> None:
        super().__init__(config)
        self.patches: deque[dict] = deque(patches if patches is not None else [{"3": {"steps": 50}}])
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def generate_fix(self, workflow, qa_report, error_log="", *, prior_corrections=None, client=None) -> dict:
        self.calls.append(
            {
                "workflow": workflow,
                "qa_report": qa_report,
                "error_log": error_log,
                "prior_corrections": list(prior_corrections or []),
            }
        )
        if self.error is not None:
            raise self.error
        return dict(self.patches.popleft()) if self.patches else {}


def build_pipeline(
    config: PipelineConfig,
    *,
    comfyui: Any = None,
    qa: Any = None,
    director: Any = None,
    assets: Any = None,
    correction: Any = None,
    store: JobStore | None = None,
    **kwargs: Any,
) -> VFPPipeline:
    """Build a pipeline with stubs injected (no network, no real state files)."""
    return VFPPipeline(
        config,
        comfyui=comfyui or FakeComfyUI(),
        qa=qa or StubQA(),
        director=director or StubDirector(),
        assets=assets or StubAssets(),
        correction=correction or StubCorrection(config.llm),
        store=store if store is not None else JobStore(config.jobs_dir),
        **kwargs,
    )


@pytest.fixture
def fake_comfyui() -> FakeComfyUI:
    return FakeComfyUI()


