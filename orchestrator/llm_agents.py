"""LLM agent roles for VFX pipeline orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import LLMConfig, LLMProviderConfig


def _resolve_api(provider: LLMProviderConfig) -> tuple[str, dict[str, str]]:
    model = provider.model.lower()
    base = provider.base_url.rstrip("/") if provider.base_url else ""
    if "claude" in model or "anthropic" in base:
        url_base = base or "https://api.anthropic.com/v1"
        return f"{url_base}/messages", {"x-api-key": provider.api_key, "anthropic-version": "2023-06-01"}
    if "qwen" in model or "dashscope" in base:
        url_base = base or "https://dashscope.aliyuncs.com/api/v1"
        return f"{url_base}/services/aigc/multimodal-generation/generation", {
            "Authorization": f"Bearer {provider.api_key}"
        }
    url_base = base or "https://open.bigmodel.cn/api/paas/v4"
    return f"{url_base}/chat/completions", {"Authorization": f"Bearer {provider.api_key}"}


async def _call_llm(
    provider: LLMProviderConfig,
    system: str,
    user_message: str,
    max_tokens: int = 4096,
) -> str:
    url, headers = _resolve_api(provider)
    headers["Content-Type"] = "application/json"

    if "anthropic" in headers.get("anthropic-version", ""):
        payload = {
            "model": provider.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user_message}],
        }
    else:
        payload = {
            "model": provider.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
        }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()

    if "content" in body:
        return body["content"][0]["text"]
    return body["choices"][0]["message"]["content"]


@dataclass
class DirectorAgent:
    """Claude agent — workflow planning and JSON generation."""

    config: LLMConfig

    SYSTEM_PROMPT = (
        "You are a VFX Director. Given a user request, generate a ComfyUI workflow JSON. "
        "Return ONLY valid JSON — the workflow dictionary with node definitions. "
        "Each node must have 'class_type', 'inputs', and a numeric string key."
    )

    async def plan(self, user_prompt: str) -> dict[str, Any]:
        raw = await _call_llm(self.config.claude, self.SYSTEM_PROMPT, user_prompt)
        return json.loads(raw)


@dataclass
class QAInspectorAgent:
    """Qwen VL agent — visual quality assessment."""

    config: LLMConfig

    SYSTEM_PROMPT = (
        "You are a QA Inspector for VFX renders. Analyze the provided image description "
        "and output a JSON object: {score: 0-1, issues: [str], summary: str}. "
        "Score >= 0.8 is passing. Be strict on: artifacts, lighting, composition, coherence."
    )

    async def inspect(self, image_description: str, criteria: str = "") -> dict[str, Any]:
        prompt = f"Image: {image_description}"
        if criteria:
            prompt += f"\nCriteria: {criteria}"
        raw = await _call_llm(self.config.qwen, self.SYSTEM_PROMPT, prompt)
        return json.loads(raw)


@dataclass
class AssetManagerAgent:
    """GLM agent — RAG for LoRAs, models, textures."""

    config: LLMConfig

    SYSTEM_PROMPT = (
        "You are an Asset Manager for VFX pipelines. Given a render description, "
        "return a JSON object listing recommended assets: "
        "{loras: [{name, strength}], models: [{name, type}], textures: [{name, resolution}]}. "
        "Only include assets that exist in common VFX repositories."
    )

    async def find_assets(self, description: str) -> dict[str, Any]:
        raw = await _call_llm(self.config.glm, self.SYSTEM_PROMPT, description)
        return json.loads(raw)


@dataclass
class CorrectionAgent:
    """Generates fix patches for failed renders."""

    config: LLMConfig
    max_tokens: int = 4096

    SYSTEM_PROMPT = (
        "You are a VFX Correction Agent. Given a failed workflow JSON and QA report, "
        "generate a PATCH: a JSON object with node ID keys mapping to input overrides. "
        "Return ONLY the patch JSON. Be surgical — change as few nodes as possible."
    )

    async def generate_fix(
        self,
        workflow: dict[str, Any],
        qa_report: dict[str, Any],
        error_log: str = "",
    ) -> dict[str, Any]:
        prompt = f"Workflow:\n{json.dumps(workflow, indent=2)}\n\nQA Report:\n{json.dumps(qa_report, indent=2)}"
        if error_log:
            prompt += f"\n\nError Log:\n{error_log}"
        raw = await _call_llm(
            self.config.claude,
            self.SYSTEM_PROMPT,
            prompt,
            max_tokens=self.max_tokens,
        )
        return json.loads(raw)

    def apply_patch(self, workflow: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        patched = json.loads(json.dumps(workflow))
        for node_id, overrides in patch.items():
            if node_id in patched:
                patched[node_id]["inputs"].update(overrides)
        return patched
