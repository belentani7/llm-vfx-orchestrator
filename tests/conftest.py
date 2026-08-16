"""Shared test fixtures."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestrator.config import LLMConfig, LLMProviderConfig, PipelineConfig


@pytest.fixture
def llm_config() -> LLMConfig:
    return LLMConfig(
        claude=LLMProviderConfig(model="claude-sonnet-4-20250514", api_key="test-claude-key"),
        qwen=LLMProviderConfig(model="qwen-vl-max", api_key="test-qwen-key"),
        glm=LLMProviderConfig(model="glm-4v-plus", api_key="test-glm-key"),
    )


@pytest.fixture
def pipeline_config(llm_config: LLMConfig) -> PipelineConfig:
    return PipelineConfig(max_retries=3, qa_threshold=0.8, llm=llm_config)


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


@pytest.fixture
def mock_comfyui_client():
    client = AsyncMock()
    client.upload_image = AsyncMock(return_value="uploaded.png")
    client.queue_prompt = AsyncMock(return_value="test-prompt-id")
    client.get_result = AsyncMock(return_value={
        "outputs": {
            "9": {"images": [{"filename": "output_001.png", "subfolder": "", "type": "output"}]}
        }
    })
    client.get_output_images = AsyncMock(return_value=["output_001.png"])
    client.download_image = AsyncMock(return_value=b"\x89PNG_FAKE_IMAGE_DATA")
    client.close = AsyncMock()
    return client


@pytest.fixture
def sample_qa_pass() -> dict:
    return {"score": 0.92, "issues": [], "summary": "Excellent render quality"}


@pytest.fixture
def sample_qa_fail() -> dict:
    return {
        "score": 0.45,
        "issues": ["visible artifacts on face", "lighting inconsistency"],
        "summary": "Significant artifacts detected, needs correction",
    }
