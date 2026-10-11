"""Loading and application of the pipeline templates shipped in ``orchestrator/templates``."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"

# class_type -> (template key, node input name)
_SAMPLER_KEYS = {"steps": "default_steps", "cfg": "default_cfg", "sampler_name": "default_sampler"}
_SIZE_KEYS = {"width": "width", "height": "height"}


def available_templates() -> list[str]:
    if not TEMPLATE_DIR.is_dir():
        return []
    return sorted(path.stem for path in TEMPLATE_DIR.glob("*.yaml"))


def load_template(name_or_path: str | Path | None) -> dict[str, Any]:
    """Load a template by short name (``character_generation``) or by path."""
    if not name_or_path:
        return {}
    candidate = Path(name_or_path)
    if not candidate.exists():
        candidate = TEMPLATE_DIR / f"{name_or_path}.yaml"
    if not candidate.exists():
        raise FileNotFoundError(
            f"template {name_or_path!r} not found (available: {', '.join(available_templates()) or 'none'})"
        )
    data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"template {candidate} must be a YAML mapping")
    template = data.get("template", data)
    if not isinstance(template, dict):
        raise ValueError(f"template section in {candidate} must be a mapping")
    template.setdefault("name", candidate.stem)
    template["_source"] = str(candidate)
    return template


def apply_template_defaults(workflow: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    """Fill in missing sampler/size/negative-prompt values from a template.

    Only *missing* values are touched, so an explicit workflow always wins.
    """
    if not template or not isinstance(workflow, dict):
        return workflow
    size = template.get("default_size") or {}
    negative = template.get("negative_prompt")
    patched = False
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        inputs = node.setdefault("inputs", {})
        if not isinstance(inputs, dict):
            continue
        if class_type == "KSampler":
            for key, template_key in _SAMPLER_KEYS.items():
                value = template.get(template_key)
                if value is not None and inputs.get(key) in (None, ""):
                    inputs[key] = value
                    patched = True
        elif class_type == "EmptyLatentImage" and isinstance(size, dict):
            for key, template_key in _SIZE_KEYS.items():
                value = size.get(template_key)
                if value is not None and inputs.get(key) in (None, ""):
                    inputs[key] = value
                    patched = True
        elif class_type == "CLIPTextEncode" and negative and _looks_negative(inputs.get("text")):
            inputs["text"] = negative
            patched = True
    if patched:
        logger.debug("applied template defaults from %s", template.get("name"))
    return workflow


_NEGATIVE_HINTS = ("blurry", "low quality", "worst quality", "bad anatomy", "watermark", "nsfw")


def _looks_negative(text: Any) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    lowered = text.lower()
    return any(hint in lowered for hint in _NEGATIVE_HINTS)


__all__ = ["TEMPLATE_DIR", "apply_template_defaults", "available_templates", "load_template"]
