"""Configuration dataclasses and loader."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ComfyUIConfig:
    host: str = "127.0.0.1"
    port: int = 8188
    timeout: int = 300
    ws_reconnect_attempts: int = 5

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}/ws"


@dataclass
class LLMProviderConfig:
    model: str = ""
    api_key: str = ""
    base_url: str = ""


@dataclass
class LLMConfig:
    claude: LLMProviderConfig = field(default_factory=LLMProviderConfig)
    qwen: LLMProviderConfig = field(default_factory=LLMProviderConfig)
    glm: LLMProviderConfig = field(default_factory=LLMProviderConfig)


@dataclass
class PipelineConfig:
    max_retries: int = 3
    qa_threshold: float = 0.8
    comfyui: ComfyUIConfig = field(default_factory=ComfyUIConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> PipelineConfig:
        data = yaml.safe_load(Path(path).read_text())
        comfyui_data = data.get("comfyui", {})
        llm_data = data.get("llm", {})
        pipeline_data = data.get("pipeline", {})

        def _resolve_env(val: str) -> str:
            if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
                import os
                return os.environ.get(val[2:-1], "")
            return val

        llm_cfg = LLMConfig(
            claude=LLMProviderConfig(**{
                k: _resolve_env(v) for k, v in llm_data.get("claude", {}).items()
            }),
            qwen=LLMProviderConfig(**{
                k: _resolve_env(v) for k, v in llm_data.get("qwen", {}).items()
            }),
            glm=LLMProviderConfig(**{
                k: _resolve_env(v) for k, v in llm_data.get("glm", {}).items()
            }),
        )

        return cls(
            max_retries=pipeline_data.get("max_retries", 3),
            qa_threshold=pipeline_data.get("qa_threshold", 0.8),
            comfyui=ComfyUIConfig(**comfyui_data),
            llm=llm_cfg,
        )
