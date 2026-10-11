"""Tests for orchestrator.config."""

from __future__ import annotations

import logging

import pytest

from orchestrator.config import (
    ComfyUIConfig,
    LLMConfig,
    LLMProviderConfig,
    PipelineConfig,
    resolve_env,
)

CONFIG_YAML = """
comfyui:
  host: "127.0.0.1"
  port: "8188"
  timeout: 120
  ws_reconnect_attempts: 3
  max_concurrent_renders: 2

llm:
  claude:
    model: "claude-sonnet-4-20250514"
    api_key: "${TEST_CLAUDE_KEY}"
  qwen:
    model: "qwen-vl-max"
    api_key: "${TEST_QWEN_KEY:-fallback-key}"
  glm:
    model: "glm-4v-plus"
    api_key: ""
  fallbacks: [claude, local]
  providers:
    local:
      model: "qwen2.5-vl"
      base_url: "http://127.0.0.1:11434"
      kind: "openai"

pipeline:
  max_retries: 5
  qa_threshold: 0.75
  concurrency: 6
  plateau_patience: 1
  banana: ignored

template:
  name: character_generation
"""


class TestResolveEnv:
    def test_full_placeholder(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "secret")
        assert resolve_env("${MY_KEY}") == "secret"

    def test_default_when_missing(self):
        assert resolve_env("${NOT_SET_ANYWHERE:-fallback}") == "fallback"

    def test_missing_without_default_is_empty(self):
        assert resolve_env("${NOT_SET_ANYWHERE_EITHER}") == ""

    def test_embedded_placeholder(self, monkeypatch):
        monkeypatch.setenv("HOST", "gpu-1")
        assert resolve_env("http://${HOST}:8188") == "http://gpu-1:8188"

    def test_non_string_passthrough(self):
        assert resolve_env(42) == 42


class TestFromYaml:
    def test_loads_nested_sections(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_CLAUDE_KEY", "claude-secret")
        monkeypatch.setenv("TEST_QWEN_KEY", "qwen-secret")
        path = tmp_path / "config.yaml"
        path.write_text(CONFIG_YAML)
        config = PipelineConfig.from_yaml(path)
        assert config.max_retries == 5
        assert config.qa_threshold == pytest.approx(0.75)
        assert config.concurrency == 6
        assert config.plateau_patience == 1
        assert config.comfyui.port == 8188  # coerced from string
        assert config.comfyui.timeout == pytest.approx(120.0)
        assert config.comfyui.max_concurrent_renders == 2
        assert config.llm.claude.api_key == "claude-secret"
        assert config.llm.qwen.api_key == "qwen-secret"
        assert config.template["name"] == "character_generation"
        assert config.llm.fallbacks == ["claude", "local"]
        assert config.llm.get("local").base_url == "http://127.0.0.1:11434"

    def test_defaults_used_for_missing_provider_key(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text(CONFIG_YAML)
        config = PipelineConfig.from_yaml(path)
        assert config.llm.qwen.api_key == "fallback-key"

    def test_unknown_keys_are_ignored_with_warning(self, tmp_path, caplog):
        path = tmp_path / "config.yaml"
        path.write_text(CONFIG_YAML)
        with caplog.at_level(logging.WARNING, logger="orchestrator.config"):
            PipelineConfig.from_yaml(path)
        assert any("banana" in record.message for record in caplog.records)

    def test_invalid_threshold_rejected(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("pipeline:\n  qa_threshold: 1.5\n")
        with pytest.raises(ValueError, match="qa_threshold"):
            PipelineConfig.from_yaml(path)

    def test_non_mapping_llm_rejected(self, tmp_path, caplog):
        path = tmp_path / "config.yaml"
        path.write_text("llm: [1, 2, 3]\n")
        config = PipelineConfig.from_yaml(path)
        assert config.llm.configured() == []
        assert any("llm section" in record.message for record in caplog.records)

    def test_flat_pipeline_keys_supported(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("max_retries: 1\nqa_threshold: 0.5\n")
        config = PipelineConfig.from_yaml(path)
        assert config.max_retries == 1
        assert config.qa_threshold == pytest.approx(0.5)

    def test_top_level_not_mapping(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("- a\n- b\n")
        with pytest.raises(ValueError):
            PipelineConfig.from_yaml(path)


class TestFromEnv:
    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("VFP_MAX_RETRIES", "7")
        monkeypatch.setenv("VFP_QA_THRESHOLD", "0.95")
        monkeypatch.setenv("VFP_CONCURRENCY", "9")
        monkeypatch.setenv("VFP_COMFYUI_URL", "https://comfy.example.com")
        monkeypatch.setenv("VFP_COMFYUI_CONCURRENCY", "4")
        config = PipelineConfig.from_env()
        assert config.max_retries == 7
        assert config.qa_threshold == pytest.approx(0.95)
        assert config.concurrency == 9
        assert config.comfyui.base_url == "https://comfy.example.com"
        assert config.comfyui.ws_url == "wss://comfy.example.com/ws"
        assert config.comfyui.max_concurrent_renders == 4

    def test_env_builds_on_top_of_yaml(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_CLAUDE_KEY", "k")
        path = tmp_path / "config.yaml"
        path.write_text(CONFIG_YAML)
        monkeypatch.setenv("VFP_MAX_RETRIES", "1")
        config = PipelineConfig.from_env(PipelineConfig.from_yaml(path))
        assert config.max_retries == 1
        assert config.concurrency == 6


class TestOverrides:
    def test_dotted_override(self):
        config = PipelineConfig().with_overrides(
            ["pipeline.max_retries=1", "llm.claude.model=claude-opus", "comfyui.port=9000", "template.name=t"]
        )
        assert config.max_retries == 1
        assert config.llm.claude.model == "claude-opus"
        assert config.comfyui.port == 9000
        assert config.template["name"] == "t"

    def test_flat_override(self):
        config = PipelineConfig().with_overrides(["qa_threshold=0.5"])
        assert config.qa_threshold == pytest.approx(0.5)

    def test_bad_override_rejected(self):
        with pytest.raises(ValueError):
            PipelineConfig().with_overrides(["max_retries"])
        with pytest.raises(ValueError):
            PipelineConfig().with_overrides(["nope.nested=1"])

    def test_override_is_validated(self):
        with pytest.raises(ValueError):
            PipelineConfig().with_overrides(["qa_threshold=3"])


class TestComfyUIConfig:
    def test_host_with_scheme(self):
        config = ComfyUIConfig(host="https://comfy.example.com")
        assert config.scheme == "https"
        assert config.host == "comfy.example.com"
        assert config.base_url == "https://comfy.example.com:8188"
        assert config.ws_url == "wss://comfy.example.com:8188/ws"

    def test_api_url_wins(self):
        config = ComfyUIConfig(api_url="https://gpu.example.com/comfy")
        assert config.base_url == "https://gpu.example.com/comfy"
        assert config.ws_url == "wss://gpu.example.com/comfy/ws"

    def test_clamps_concurrency(self):
        assert ComfyUIConfig(max_concurrent_renders=0).max_concurrent_renders == 1
        assert ComfyUIConfig(ws_reconnect_attempts=0).ws_reconnect_attempts == 1


class TestLLMConfig:
    def test_chain_for_uses_fallbacks(self):
        config = LLMConfig(
            claude=LLMProviderConfig(model="claude", api_key="k"),
            glm=LLMProviderConfig(model="glm", api_key="k2"),
            fallbacks=["glm"],
        )
        chain = config.chain_for("claude")
        assert [name for name, _ in chain] == ["claude", "glm"]

    def test_chain_skips_unconfigured(self):
        config = LLMConfig(claude=LLMProviderConfig(), fallbacks=["glm"])
        assert config.chain_for("claude") == []

    def test_usable_without_api_key_but_with_base_url(self):
        provider = LLMProviderConfig(model="local-vl", base_url="http://127.0.0.1:11434")
        assert provider.usable

    def test_configured_lists_only_usable(self):
        config = LLMConfig(
            claude=LLMProviderConfig(model="claude", api_key="k"),
            qwen=LLMProviderConfig(model="qwen"),
        )
        assert config.configured() == ["claude"]


class TestJobsDir:
    def test_store_dir_wins(self, tmp_path):
        config = PipelineConfig(store_dir=str(tmp_path))
        assert config.jobs_dir == tmp_path / "jobs"

    def test_vfp_home_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VFP_HOME", str(tmp_path / "home"))
        assert PipelineConfig().jobs_dir == tmp_path / "home" / "jobs"
