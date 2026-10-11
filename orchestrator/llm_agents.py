"""LLM agent roles for VFX pipeline orchestration.

Wire protocols supported (auto-detected, overridable with ``kind``):

* ``anthropic``  — Claude messages API (text + base64 images)
* ``dashscope``  — Alibaba Qwen-VL native multimodal generation endpoint
* ``openai``     — any OpenAI-compatible ``/chat/completions`` endpoint
  (GLM/Zhipu, DeepSeek, Qwen compatible-mode, Ollama, vLLM, Groq, Gemini OpenAI mode…)
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from .config import LLMConfig, LLMProviderConfig
from .utils import (
    JSONExtractionError,
    backoff_delay,
    coerce_score,
    extract_json,
    retry_after_seconds,
    truncate,
)

logger = logging.getLogger(__name__)

KIND_ANTHROPIC = "anthropic"
KIND_DASHSCOPE = "dashscope"
KIND_OPENAI = "openai"

_DEFAULT_BASE = {
    KIND_ANTHROPIC: "https://api.anthropic.com/v1",
    KIND_DASHSCOPE: "https://dashscope.aliyuncs.com/api/v1",
    KIND_OPENAI: "https://open.bigmodel.cn/api/paas/v4",
}

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}

_KIND_ALIASES = {
    "claude": KIND_ANTHROPIC,
    "anthropic": KIND_ANTHROPIC,
    "messages": KIND_ANTHROPIC,
    "qwen": KIND_DASHSCOPE,
    "dashscope": KIND_DASHSCOPE,
    "aliyun": KIND_DASHSCOPE,
    "openai": KIND_OPENAI,
    "compatible": KIND_OPENAI,
    "glm": KIND_OPENAI,
    "zhipu": KIND_OPENAI,
    "azure": KIND_OPENAI,
    "ollama": KIND_OPENAI,
    "vllm": KIND_OPENAI,
}

_DEFAULT_MODELS = {
    KIND_ANTHROPIC: "claude-sonnet-4-20250514",
    KIND_DASHSCOPE: "qwen-vl-max",
    KIND_OPENAI: "glm-4v-plus",
}

_clients: dict[tuple[float, bool], httpx.AsyncClient] = {}
_semaphores: dict[tuple[str, str], asyncio.Semaphore] = {}


class LLMError(RuntimeError):
    """Raised when every candidate provider failed to answer a request."""


@dataclass(frozen=True)
class ProviderEndpoint:
    url: str
    headers: dict[str, str]
    kind: str
    model: str
    trust_env: bool = True


def detect_kind(provider: LLMProviderConfig) -> str:
    """Best-effort detection of the wire protocol for a provider."""
    explicit = (provider.kind or "").strip().lower()
    if explicit:
        return _KIND_ALIASES.get(explicit, explicit if explicit in _DEFAULT_BASE else KIND_OPENAI)
    model = (provider.model or "").lower()
    base = (provider.base_url or "").lower()
    if "anthropic" in base or "claude" in model:
        return KIND_ANTHROPIC
    if "compatible-mode" in base or "openai" in base or "generativelanguage" in base:
        return KIND_OPENAI
    if "dashscope" in base or "aliyun" in base or "qwen" in model:
        return KIND_DASHSCOPE
    if "bigmodel" in base or "zhipu" in base or "glm" in model:
        return KIND_OPENAI
    return KIND_OPENAI


_VERSION_SEGMENT = re.compile(r"v\d+[a-z]*")


def _path_segments(base: str) -> list[str]:
    return [segment for segment in urlsplit(base).path.split("/") if segment]


def _versioned(base: str, kind: str) -> str:
    """Add the default API version segment when the base URL lacks one."""
    base = base.rstrip("/")
    segments = _path_segments(base)
    has_version = any(_VERSION_SEGMENT.fullmatch(segment) for segment in segments) or "beta" in segments
    if has_version:
        return base
    if kind == KIND_ANTHROPIC:
        return f"{base}/v1"
    if kind == KIND_OPENAI and not base.endswith("chat/completions"):
        return f"{base}/v1"
    return base


def resolve_endpoint(provider: LLMProviderConfig) -> ProviderEndpoint:
    """Resolve a provider config into a concrete URL + headers + protocol."""
    kind = detect_kind(provider)
    base = (provider.base_url or _DEFAULT_BASE[kind]).rstrip("/")
    base = _versioned(base, kind)

    if kind == KIND_ANTHROPIC:
        url = base if base.endswith("/messages") else f"{base}/messages"
        headers = {
            "x-api-key": provider.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
    elif kind == KIND_DASHSCOPE:
        if base.endswith("/generation"):
            url = base
        elif base.endswith("/api/v1"):
            url = f"{base}/services/aigc/multimodal-generation/generation"
        else:
            url = f"{base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "content-type": "application/json",
        }
    else:
        url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "content-type": "application/json",
        }

    model = provider.model or _DEFAULT_MODELS[kind]
    return ProviderEndpoint(
        url=url, headers=headers, kind=kind, model=model, trust_env=provider.use_proxy
    )


def shared_client(timeout: float = 120.0, trust_env: bool = True) -> httpx.AsyncClient:
    """A pooled HTTP client per (timeout, proxy) bucket — no TLS handshake per call."""
    key = (float(timeout), bool(trust_env))
    client = _clients.get(key)
    if client is None or client.is_closed:
        limits = httpx.Limits(max_connections=32, max_keepalive_connections=16)
        client = httpx.AsyncClient(timeout=timeout, limits=limits, trust_env=trust_env)
        _clients[key] = client
    return client


async def aclose_clients() -> None:
    """Close every pooled client (call on shutdown / between tests)."""
    for key, client in list(_clients.items()):
        with contextlib.suppress(Exception):
            await client.aclose()
        _clients.pop(key, None)
    _semaphores.clear()


def _semaphore_for(endpoint: ProviderEndpoint, limit: int) -> asyncio.Semaphore:
    """One bounded semaphore per (endpoint, model) so a burst cannot hammer a provider."""
    key = (endpoint.url, endpoint.model)
    semaphore = _semaphores.get(key)
    if semaphore is None:
        semaphore = asyncio.Semaphore(max(1, int(limit)))
        _semaphores[key] = semaphore
    return semaphore


def build_payload(
    endpoint: ProviderEndpoint,
    system: str,
    user_message: str,
    max_tokens: int,
    *,
    image: bytes | None = None,
    image_media_type: str = "image/png",
) -> dict[str, Any]:
    """Build the provider-specific request body (text-only when ``image`` is None)."""
    if endpoint.kind == KIND_ANTHROPIC:
        blocks: list[dict[str, Any]] = [{"type": "text", "text": user_message}]
        if image is not None:
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image_media_type,
                        "data": base64.b64encode(image).decode("ascii"),
                    },
                }
            )
        return {
            "model": endpoint.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": blocks}],
        }

    if endpoint.kind == KIND_DASHSCOPE:
        content: list[dict[str, Any]] = []
        if image is not None:
            encoded = base64.b64encode(image).decode("ascii")
            content.append({"image": f"data:{image_media_type};base64,{encoded}"})
        content.append({"text": user_message})
        return {
            "model": endpoint.model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": {"max_tokens": max_tokens, "incremental_output": False},
        }

    content: Any
    if image is not None:
        encoded = base64.b64encode(image).decode("ascii")
        content = [
            {"type": "text", "text": user_message},
            {"type": "image_url", "image_url": {"url": f"data:{image_media_type};base64,{encoded}"}},
        ]
    else:
        content = user_message
    return {
        "model": endpoint.model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
    }


def parse_response(kind: str, body: dict[str, Any]) -> str:
    """Extract the assistant text from a provider response body."""
    try:
        if kind == KIND_ANTHROPIC:
            parts = body["content"]
            if isinstance(parts, str):
                return parts
            return "\n".join(
                part.get("text", "")
                for part in parts
                if isinstance(part, dict) and part.get("type", "text") == "text"
            ).strip()
        if kind == KIND_DASHSCOPE:
            choices = body.get("output", {}).get("choices") or body.get("choices") or []
            if not choices:
                raise KeyError("output.choices")
            message = choices[0].get("message", {})
            content = message.get("content", "")
            if isinstance(content, str):
                return content.strip()
            return "\n".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("text")
            ).strip()
        choices = body.get("choices") or []
        if not choices:
            raise KeyError("choices")
        content = choices[0].get("message", {}).get("content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return "\n".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type", "text") == "text"
            ).strip()
        return str(content).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"unexpected {kind} response shape: {truncate(json.dumps(body), 300)}") from exc


async def _post_once(
    endpoint: ProviderEndpoint,
    payload: dict[str, Any],
    timeout: float,
    client: httpx.AsyncClient | None,
) -> str:
    http = client or shared_client(timeout, endpoint.trust_env)
    response = await http.post(endpoint.url, json=payload, headers=endpoint.headers, timeout=timeout)
    if response.status_code >= 400:
        detail = truncate(response.text, 300)
        error = LLMError(f"HTTP {response.status_code} from {endpoint.url}: {detail}")
        error.retryable = response.status_code in _RETRYABLE_STATUS  # type: ignore[attr-defined]
        error.retry_after = retry_after_seconds(response.headers.get("retry-after"))  # type: ignore[attr-defined]
        raise error
    if not response.content:
        raise LLMError(f"empty response body from {endpoint.url}")
    try:
        body = response.json()
    except ValueError as exc:
        raise LLMError(f"non-JSON response from {endpoint.url}: {truncate(response.text, 200)}") from exc
    text = parse_response(endpoint.kind, body)
    if not text:
        raise LLMError(f"empty completion text from {endpoint.url}")
    return text


async def _call_llm(
    provider: LLMProviderConfig,
    system: str,
    user_message: str,
    max_tokens: int | None = None,
    *,
    image: bytes | None = None,
    image_media_type: str = "image/png",
    client: httpx.AsyncClient | None = None,
    _provider_name: str = "",
) -> str:
    """Call one provider with retries, jittered backoff and bounded concurrency."""
    endpoint = resolve_endpoint(provider)
    payload = build_payload(
        endpoint,
        system,
        user_message,
        max_tokens or provider.max_tokens or 4096,
        image=image,
        image_media_type=image_media_type,
    )
    attempts = max(1, provider.max_retries + 1)
    last_error: Exception | None = None
    semaphore = _semaphore_for(endpoint, provider.max_concurrency)

    for attempt in range(attempts):
        try:
            async with semaphore:
                return await _post_once(endpoint, payload, provider.timeout, client)
        except LLMError as exc:
            last_error = exc
            if not getattr(exc, "retryable", False):
                raise
            delay = getattr(exc, "retry_after", None)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            delay = None
        if attempt == attempts - 1:
            break
        sleep_for = delay if delay is not None else backoff_delay(attempt)
        logger.debug(
            "llm%s retry %s/%s in %.2fs (%s)",
            f"[{_provider_name}]" if _provider_name else "",
            attempt + 1,
            attempts - 1,
            sleep_for,
            truncate(str(last_error), 120),
        )
        await asyncio.sleep(sleep_for)

    raise LLMError(
        f"provider {_provider_name or endpoint.model} failed after {attempts} attempt(s): "
        f"{truncate(str(last_error), 300)}"
    )


async def call_provider_chain(
    chain: list[tuple[str, LLMProviderConfig]],
    system: str,
    user_message: str,
    max_tokens: int | None = None,
    *,
    image: bytes | None = None,
    image_media_type: str = "image/png",
    client: httpx.AsyncClient | None = None,
) -> str:
    """Try each provider in order; raise :class:`LLMError` if all of them fail."""
    if not chain:
        raise LLMError("no LLM provider configured (set an api_key or base_url in the llm section)")
    errors: list[str] = []
    skipped = 0
    for name, provider in chain:
        if image is not None and not provider.vision:
            logger.debug("provider %s has vision disabled — trying next in chain", name)
            skipped += 1
            continue
        try:
            return await _call_llm(
                provider,
                system,
                user_message,
                max_tokens,
                image=image,
                image_media_type=image_media_type,
                client=client,
                _provider_name=name,
            )
        except Exception as exc:  # noqa: BLE001 - we aggregate and re-raise
            errors.append(f"{name}: {truncate(str(exc), 200)}")
            logger.warning("provider %s failed: %s", name, truncate(str(exc), 200))
    if skipped and not errors:
        raise LLMError("no vision-capable provider in the chain (set vision: true on one of them)")
    raise LLMError("all providers failed -> " + " | ".join(errors))


@dataclass
class _AgentBase:
    """Common plumbing for the role-playing agents."""

    config: LLMConfig
    role: str = "claude"
    max_tokens: int = 4096

    def chain(self) -> list[tuple[str, LLMProviderConfig]]:
        return self.config.chain_for(self.role)

    async def _call(
        self,
        system: str,
        user_message: str,
        *,
        image: bytes | None = None,
        image_media_type: str = "image/png",
        max_tokens: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> str:
        return await call_provider_chain(
            self.chain(),
            system,
            user_message,
            max_tokens or self.max_tokens,
            image=image,
            image_media_type=image_media_type,
            client=client,
        )

    async def _call_json(
        self,
        system: str,
        user_message: str,
        *,
        image: bytes | None = None,
        image_media_type: str = "image/png",
        client: httpx.AsyncClient | None = None,
    ) -> Any:
        """Call the model and parse JSON, re-asking once if the answer was prose."""
        raw = await self._call(system, user_message, image=image, image_media_type=image_media_type, client=client)
        try:
            return extract_json(raw)
        except JSONExtractionError as exc:
            logger.warning("%s returned non-JSON (%s); asking for a repair", self.role, exc)
        repair = (
            f"{user_message}\n\nYour previous answer could not be parsed as JSON. "
            "Reply with ONLY the JSON value — no prose, no markdown fences."
        )
        raw = await self._call(
            system,
            repair,
            image=image,
            image_media_type=image_media_type,
            client=client,
        )
        return extract_json(raw)


@dataclass
class DirectorAgent(_AgentBase):
    """Claude (or fallback) agent — workflow planning and JSON generation."""

    role: str = "claude"
    max_tokens: int = 8192

    SYSTEM_PROMPT = (
        "You are a VFX Director. Given a user request, generate a ComfyUI API-format workflow. "
        "Return ONLY valid JSON — an object mapping numeric string node ids to node objects. "
        "Each node must have 'class_type' and 'inputs'; links are [node_id, output_index] pairs. "
        "Always include CheckpointLoaderSimple, CLIPTextEncode (positive/negative), KSampler, "
        "EmptyLatentImage, VAEDecode and SaveImage nodes so the graph is directly executable."
    )

    async def plan(
        self,
        user_prompt: str,
        *,
        template: dict[str, Any] | None = None,
        asset_hints: dict[str, Any] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        parts = [f"Request: {user_prompt}"]
        if template:
            template_name = template.get("name", "unnamed")
            defaults = {
                key: value
                for key, value in template.items()
                if key
                in {
                    "default_sampler",
                    "default_steps",
                    "default_cfg",
                    "default_size",
                    "negative_prompt",
                    "default_loras",
                }
            }
            parts.append(f"Template '{template_name}' defaults to honor: {json.dumps(defaults, ensure_ascii=False)}")
        if asset_hints:
            parts.append(f"Available assets (use only these, do not invent names): {json.dumps(asset_hints, ensure_ascii=False)}")
        workflow = await self._call_json(self.SYSTEM_PROMPT, "\n\n".join(parts), client=client)
        if not isinstance(workflow, dict) or not workflow:
            raise LLMError("director returned an empty or non-object workflow")
        return workflow


@dataclass
class QAInspectorAgent(_AgentBase):
    """Qwen-VL (or fallback) agent — visual quality assessment."""

    role: str = "qwen"
    max_tokens: int = 1024

    SYSTEM_PROMPT = (
        "You are a QA Inspector for VFX renders. Analyze the image (and any context given) "
        "and output a JSON object: {\"score\": 0-1, \"issues\": [str], \"summary\": str}. "
        "Score >= 0.8 is passing. Be strict on: artifacts, lighting, composition, coherence, "
        "anatomy, text legibility. Prefer numeric scores on a 0-1 scale."
    )

    async def inspect(
        self,
        image_description: str = "",
        criteria: str = "",
        *,
        image: bytes | None = None,
        image_media_type: str = "image/png",
        extra_context: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        prompt_parts = []
        if image_description:
            prompt_parts.append(f"Image: {image_description}")
        if image is None:
            prompt_parts.append("No pixels are attached; judge from the description above.")
        if criteria:
            prompt_parts.append(f"Criteria: {criteria}")
        if extra_context:
            prompt_parts.append(f"Context: {extra_context}")
        report = await self._call_json(
            self.SYSTEM_PROMPT,
            "\n".join(prompt_parts) or "No image or description provided.",
            image=image,
            image_media_type=image_media_type,
            client=client,
        )
        return normalize_qa_report(report)


@dataclass
class AssetManagerAgent(_AgentBase):
    """GLM (or fallback) agent — RAG-style lookup of LoRAs, models and textures."""

    role: str = "glm"
    max_tokens: int = 1024

    SYSTEM_PROMPT = (
        "You are an Asset Manager for VFX pipelines. Given a render description, return a JSON "
        "object listing recommended assets: "
        "{\"loras\": [{\"name\", \"strength\"}], \"models\": [{\"name\", \"type\"}], "
        "\"textures\": [{\"name\", \"resolution\"}]}. "
        "Only include assets that are actually available; never invent file names."
    )

    async def find_assets(
        self,
        description: str,
        *,
        available: list[str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        prompt = f"Render description: {description}"
        if available:
            prompt += (
                "\n\nAssets present on disk (pick from this list only): "
                + json.dumps(sorted(available), ensure_ascii=False)
            )
        else:
            prompt += "\n\nNo asset inventory was provided; return empty lists instead of guessing."
        data = await self._call_json(self.SYSTEM_PROMPT, prompt, client=client)
        if not isinstance(data, dict):
            return {"loras": [], "models": [], "textures": []}
        return {
            "loras": data.get("loras") or [],
            "models": data.get("models") or [],
            "textures": data.get("textures") or [],
        }


@dataclass
class CorrectionAgent(_AgentBase):
    """Generates surgical fix patches for failed renders."""

    role: str = "claude"
    max_tokens: int = 4096

    SYSTEM_PROMPT = (
        "You are a VFX Correction Agent. Given a ComfyUI workflow JSON and a QA report or error "
        "log, generate a PATCH: a JSON object mapping node id -> input overrides, e.g. "
        "{\"3\": {\"steps\": 45, \"cfg\": 6.5}}. You may also add nodes with the special keys "
        "\"__new_nodes__\": {node_id: node} and \"__remove_nodes__\": [node_id]. "
        "Return ONLY the patch JSON. Be surgical — change as few nodes as possible, and never "
        "repeat a change that already failed."
    )

    async def generate_fix(
        self,
        workflow: dict[str, Any],
        qa_report: dict[str, Any],
        error_log: str = "",
        *,
        prior_corrections: list[dict[str, Any]] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        sections = [
            f"Workflow:\n{json.dumps(workflow, indent=2, ensure_ascii=False)[:12000]}",
            f"QA Report:\n{json.dumps(qa_report, indent=2, ensure_ascii=False)}",
        ]
        if error_log:
            sections.append(f"Error Log:\n{truncate(error_log, 4000)}")
        if prior_corrections:
            sections.append(
                "Already attempted (do not repeat):\n"
                + json.dumps(prior_corrections[-3:], ensure_ascii=False)
            )
        data = await self._call_json(self.SYSTEM_PROMPT, "\n\n".join(sections), client=client)
        if not isinstance(data, dict):
            raise LLMError("correction agent returned a non-object patch")
        return data

    def apply_patch(self, workflow: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        """Apply input overrides (plus optional node add/remove) to a copy of the workflow."""
        patched = json.loads(json.dumps(workflow))
        for node_id, overrides in patch.items():
            if node_id in {"__new_nodes__", "__remove_nodes__"}:
                continue
            if not isinstance(overrides, dict):
                logger.warning("ignoring non-object override for node %s", node_id)
                continue
            node = patched.get(node_id)
            if not isinstance(node, dict):
                logger.warning("patch references unknown node %s — skipping", node_id)
                continue
            inputs = node.setdefault("inputs", {})
            if not isinstance(inputs, dict):
                inputs = {}
                node["inputs"] = inputs
            inputs.update(overrides)

        new_nodes = patch.get("__new_nodes__")
        if isinstance(new_nodes, dict):
            for node_id, node in new_nodes.items():
                if isinstance(node, dict):
                    patched[str(node_id)] = node
        removals = patch.get("__remove_nodes__")
        if isinstance(removals, list):
            for node_id in removals:
                patched.pop(str(node_id), None)
        return patched


def normalize_qa_report(report: Any) -> dict[str, Any]:
    """Coerce a model's QA answer into ``{score: float, issues: [str], summary: str}``.

    Extra keys produced by callers (``degraded``, ``file``…) are preserved.
    """
    if not isinstance(report, dict):
        return {"score": 0.0, "issues": [f"unparseable QA report: {truncate(str(report), 120)}"], "summary": ""}
    issues_raw = report.get("issues") or report.get("problems") or []
    if isinstance(issues_raw, str):
        issues = [issues_raw]
    elif isinstance(issues_raw, list):
        issues = [str(item) for item in issues_raw if item is not None]
    else:
        issues = [str(issues_raw)]
    score = report.get("score", report.get("quality", report.get("rating", 0.0)))
    summary = report.get("summary") or report.get("reason") or ""
    normalized = {
        key: value
        for key, value in report.items()
        if key not in {"score", "quality", "rating", "issues", "problems", "summary", "reason"}
    }
    normalized.update(
        {
            "score": coerce_score(score),
            "issues": issues,
            "summary": str(summary),
        }
    )
    return normalized


__all__ = [
    "AssetManagerAgent",
    "CorrectionAgent",
    "DirectorAgent",
    "LLMError",
    "ProviderEndpoint",
    "QAInspectorAgent",
    "aclose_clients",
    "build_payload",
    "call_provider_chain",
    "detect_kind",
    "normalize_qa_report",
    "parse_response",
    "resolve_endpoint",
    "shared_client",
]
