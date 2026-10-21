"""Verify the shipped user-facing configuration stays loadable and secret-free."""
from pathlib import Path
from unittest.mock import patch

import yaml

from orchestrator.config import PipelineConfig

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "config.example.yaml"


def test_example_configuration_parses_and_contains_no_credentials():
    raw = EXAMPLE.read_text(encoding="utf-8")
    doc = yaml.safe_load(raw)
    assert isinstance(doc, dict)
    assert "sk-" not in raw
    assert "api_key:" in raw
    assert "${ANTHROPIC_API_KEY}" in raw
    assert "${DASHSCOPE_API_KEY}" in raw
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "", "DASHSCOPE_API_KEY": "", "ZHIPUAI_API_KEY": ""}):
        config = PipelineConfig.from_yaml(EXAMPLE)
    assert config.comfyui.port == 8188
    assert config.qa_threshold == 0.8
    assert config.llm.claude.api_key == ""
    assert config.llm.qwen.api_key == ""


def test_static_product_home_is_linked_to_real_documentation():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert "<main" in html
    assert "config.example.yaml" in html
    assert "ComfyUI" in html
    assert "site.css" in html
    assert "site.js" in html
