"""Configuration dataclasses, YAML/env loading and CLI overrides."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, get_type_hints

import yaml

logger = logging.getLogger(__name__)

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

_PROVIDER_SECTIONS = ("claude", "qwen", "glm")


def resolve_env(value: Any) -> Any:
    """Expand ``${VAR}`` / ``${VAR:-default}`` placeholders inside strings."""
    if not isinstance(value, str) or "${" not in value:
        return value
    full = _ENV_RE.fullmatch(value)
    if full is not None:
        name, default = full.group(1), full.group(2)
        return os.environ.get(name, "" if default is None else default)
    return _ENV_RE.sub(
        lambda m: os.environ.get(m.group(1), "" if m.group(2) is None else m.group(2)),
        value,
    )


def field_kinds(cls: type) -> dict[str, Any]:
    """Dataclass field name -> resolved annotation (``f.type`` is a str under PEP 563)."""
    resolved: dict[str, Any] = {}
    try:
        resolved = dict(get_type_hints(cls))
    except Exception:  # pragma: no cover - defensive: unresolvable forward refs
        resolved = {}
    return {f.name: resolved.get(f.name, f.type) for f in fields(cls)}


def coerce_scalar(value: Any, kind: Any) -> Any:
    """Coerce a YAML/CLI scalar into the annotation used by a dataclass field."""
    if kind is float and isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if kind is int and isinstance(value, (str, float)) and not isinstance(value, bool):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return value
    if kind is bool and isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if kind is str and isinstance(value, (int, float, bool)):
        return str(value)
    return value


def _build_dataclass(cls: type, data: Any, *, owner: str) -> Any:
    """Build ``cls`` from a mapping, coercing scalars and ignoring unknown keys."""
    if data is None:
        return cls()
    if not isinstance(data, dict):
        logger.warning("config: %s must be a mapping, got %s — using defaults", owner, type(data).__name__)
        return cls()
    kinds = field_kinds(cls)
    unknown = sorted(set(data) - set(kinds))
    if unknown:
        logger.warning("config: ignoring unknown %s keys: %s", owner, ", ".join(unknown))
    kwargs: dict[str, Any] = {}
    for name, raw in data.items():
        if name not in kinds:
            continue
        value = resolve_env(raw)
        kind = kinds[name]
        if is_dataclass(kind):
            kwargs[name] = _build_dataclass(kind, value, owner=f"{owner}.{name}")
        elif isinstance(value, dict):
            kwargs[name] = dict(value)
        else:
            kwargs[name] = coerce_scalar(value, kind)
    return cls(**kwargs)


@dataclass
class ComfyUIConfig:
    """Where and how to reach the ComfyUI server."""

    host: str = "127.0.0.1"
    port: int = 8188
    timeout: float = 300.0
    scheme: str = "http"
    api_url: str = ""
    ws_reconnect_attempts: int = 5
    ws_timeout: float = 3600.0
    max_concurrent_renders: int = 1
    client_id: str = ""
    use_proxy: bool = False
    follow_redirects: bool = True

    def __post_init__(self) -> None:
        # Tolerate `host: https://comfy.example.com` (a very common config slip).
        if "://" in str(self.host):
            scheme, _, rest = str(self.host).partition("://")
            self.scheme = scheme
            self.host = rest.split("/", 1)[0]
        self.api_url = str(self.api_url or "").rstrip("/")
        self.timeout = float(self.timeout)
        self.ws_timeout = float(self.ws_timeout)
        self.port = int(self.port)
        self.max_concurrent_renders = max(1, int(self.max_concurrent_renders))
        self.ws_reconnect_attempts = max(1, int(self.ws_reconnect_attempts))

    def _authority(self) -> tuple[str, str]:
        """``(scheme, host[:port][/path])`` from either ``api_url`` or host/port."""
        if self.api_url:
            if "://" in self.api_url:
                scheme, _, rest = self.api_url.partition("://")
                return scheme, rest.rstrip("/")
            return self.scheme, self.api_url
        return self.scheme, f"{self.host}:{self.port}"

    @property
    def base_url(self) -> str:
        scheme, authority = self._authority()
        return f"{scheme}://{authority}"

    @property
    def ws_url(self) -> str:
        scheme, authority = self._authority()
        return f"{'wss' if scheme == 'https' else 'ws'}://{authority}/ws"


@dataclass
class LLMProviderConfig:
    """One LLM endpoint. ``kind`` selects the wire protocol (auto-detected if empty)."""

    model: str = ""
    api_key: str = ""
    base_url: str = ""
    kind: str = ""
    timeout: float = 120.0
    max_retries: int = 3
    max_tokens: int = 4096
    max_concurrency: int = 4
    vision: bool = True
    use_proxy: bool = True

    def __post_init__(self) -> None:
        self.timeout = float(self.timeout)
        self.max_retries = max(0, int(self.max_retries))
        self.max_tokens = max(1, int(self.max_tokens))
        self.max_concurrency = max(1, int(self.max_concurrency))

    @property
    def usable(self) -> bool:
        """Callable when it has a model and either a key or a custom URL (local servers)."""
        return bool(self.model) and bool(self.api_key or self.base_url)


@dataclass
class LLMConfig:
    """Provider registry plus a fallback chain used when a provider misbehaves."""

    claude: LLMProviderConfig = field(default_factory=LLMProviderConfig)
    qwen: LLMProviderConfig = field(default_factory=LLMProviderConfig)
    glm: LLMProviderConfig = field(default_factory=LLMProviderConfig)
    providers: dict[str, LLMProviderConfig] = field(default_factory=dict)
    fallbacks: list[str] = field(default_factory=list)

    def registry(self) -> dict[str, LLMProviderConfig]:
        registry = {name: getattr(self, name) for name in _PROVIDER_SECTIONS}
        registry.update(self.providers)
        return registry

    def get(self, name: str) -> LLMProviderConfig | None:
        return self.registry().get(name)

    def chain_for(self, role: str) -> list[tuple[str, LLMProviderConfig]]:
        """Ordered ``(name, provider)`` candidates: the role's provider then fallbacks."""
        registry = self.registry()
        chain: list[tuple[str, LLMProviderConfig]] = []
        primary = registry.get(role)
        if primary is not None and primary.usable:
            chain.append((role, primary))
        for name in self.fallbacks:
            if name == role or any(name == existing for existing, _ in chain):
                continue
            provider = registry.get(name)
            if provider is not None and provider.usable:
                chain.append((name, provider))
        return chain

    def configured(self) -> list[str]:
        return [name for name, provider in self.registry().items() if provider.usable]


@dataclass
class PipelineConfig:
    """Full pipeline configuration (quality gates, retries, concurrency, storage)."""

    max_retries: int = 3
    qa_threshold: float = 0.8
    min_score_improvement: float = 0.01
    plateau_patience: int = 2
    concurrency: int = 4
    qa_concurrency: int = 4
    max_qa_images: int = 4
    vision_max_bytes: int = 4_000_000
    correct_execution_errors: bool = True
    store_dir: str = ""
    comfyui: ComfyUIConfig = field(default_factory=ComfyUIConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    template: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> PipelineConfig:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path}: top-level YAML must be a mapping")
        logger.debug("loaded config from %s", path)
        return cls.from_mapping(data)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> PipelineConfig:
        data = dict(data or {})
        pipeline_data = data.pop("pipeline", None)
        if pipeline_data is None:
            pipeline_data = {}
        if not isinstance(pipeline_data, dict):
            raise ValueError("pipeline section must be a mapping")

        known = set(field_kinds(cls))
        merged: dict[str, Any] = {**pipeline_data}
        for key, raw in data.items():
            if key in known or key in {"template"}:
                merged[key] = raw
            else:
                logger.warning("config: ignoring unknown top-level key %r", key)

        unknown = sorted(set(merged) - set(known) - {"comfyui", "llm", "template"})
        if unknown:
            logger.warning("config: ignoring unknown pipeline keys: %s", ", ".join(unknown))
        kinds = field_kinds(cls)
        config = cls()
        for key, raw in merged.items():
            if key == "comfyui":
                config.comfyui = _build_dataclass(ComfyUIConfig, resolve_env(raw), owner="comfyui")
            elif key == "llm":
                config.llm = _build_llm_config(resolve_env(raw))
            elif key == "template":
                if isinstance(raw, dict):
                    config.template = dict(raw)
                else:
                    logger.warning("config: template must be a mapping, got %s", type(raw).__name__)
            elif key in kinds:
                setattr(config, key, coerce_scalar(resolve_env(raw), kinds[key]))
        config.validate()
        return config

    @classmethod
    def from_env(cls, base: PipelineConfig | None = None) -> PipelineConfig:
        """Apply ``VFP_*`` environment overrides on top of ``base``."""
        config = base or cls()
        scalars: dict[str, tuple[str, Any]] = {
            "VFP_MAX_RETRIES": ("max_retries", int),
            "VFP_QA_THRESHOLD": ("qa_threshold", float),
            "VFP_CONCURRENCY": ("concurrency", int),
            "VFP_QA_CONCURRENCY": ("qa_concurrency", int),
            "VFP_MAX_QA_IMAGES": ("max_qa_images", int),
            "VFP_STORE_DIR": ("store_dir", str),
        }
        for env_name, (attr, caster) in scalars.items():
            raw = os.environ.get(env_name)
            if raw:
                setattr(config, attr, caster(raw))
        comfy = {
            "VFP_COMFYUI_URL": "api_url",
            "VFP_COMFYUI_HOST": "host",
            "VFP_COMFYUI_PORT": "port",
            "VFP_COMFYUI_TIMEOUT": "timeout",
            "VFP_COMFYUI_WS_TIMEOUT": "ws_timeout",
            "VFP_COMFYUI_CONCURRENCY": "max_concurrent_renders",
        }
        comfy_kinds = field_kinds(ComfyUIConfig)
        for env_name, attr in comfy.items():
            raw = os.environ.get(env_name)
            if raw:
                setattr(
                    config.comfyui,
                    attr,
                    coerce_scalar(raw, comfy_kinds.get(attr)),
                )
        config.validate()
        return config

    def with_overrides(self, overrides: list[str] | tuple[str, ...] = ()) -> PipelineConfig:
        """Apply ``dotted.key=value`` overrides (used by ``vfp --set``)."""
        for item in overrides:
            key, sep, raw = item.partition("=")
            if not sep:
                raise ValueError(f"invalid override {item!r}: expected key=value")
            self._apply_override(key.strip(), raw.strip())
        self.validate()
        return self

    def _apply_override(self, key: str, raw: str) -> None:
        target: Any = self
        parts = key.split(".")
        if parts and parts[0] == "pipeline":
            parts = parts[1:]  # `pipeline.qa_threshold` and `qa_threshold` are the same key
        for part in parts[:-1]:
            if is_dataclass(target) and part in field_kinds(type(target)):
                target = getattr(target, part)
            elif isinstance(target, dict):
                target = target.setdefault(part, {})
            else:
                raise ValueError(f"unknown config path {key!r}")
        leaf = parts[-1]
        if isinstance(target, dict):
            target[leaf] = _typed_scalar(raw)
        elif is_dataclass(target) and leaf in field_kinds(type(target)):
            setattr(target, leaf, coerce_scalar(_typed_scalar(raw), field_kinds(type(target))[leaf]))
        else:
            raise ValueError(f"unknown config path {key!r}")

    def validate(self) -> PipelineConfig:
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if not 0.0 <= self.qa_threshold <= 1.0:
            raise ValueError("qa_threshold must be within [0, 1]")
        if self.concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        if self.qa_concurrency < 1:
            raise ValueError("qa_concurrency must be >= 1")
        if self.max_qa_images < 1:
            raise ValueError("max_qa_images must be >= 1")
        if self.plateau_patience < 0:
            raise ValueError("plateau_patience must be >= 0")
        return self

    @property
    def jobs_dir(self) -> Path:
        root = self.store_dir or os.environ.get("VFP_HOME", "") or str(Path.home() / ".vfp")
        return Path(root).expanduser() / "jobs"


def _typed_scalar(raw: str) -> Any:
    lowered = raw.strip().lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _build_llm_config(data: Any) -> LLMConfig:
    if data is None:
        return LLMConfig()
    if not isinstance(data, dict):
        logger.warning("config: llm section must be a mapping, got %s", type(data).__name__)
        return LLMConfig()
    known = {"providers", "fallbacks"}
    sections = {k: v for k, v in data.items() if k not in known}
    unknown = sorted(set(sections) - set(_PROVIDER_SECTIONS))
    if unknown:
        logger.warning("config: ignoring unknown llm providers: %s", ", ".join(unknown))
    providers: dict[str, LLMProviderConfig] = {}
    for name, raw in sections.items():
        if name in _PROVIDER_SECTIONS:
            continue
        providers[name] = _build_dataclass(LLMProviderConfig, resolve_env(raw), owner=f"llm.{name}")
    explicit = data.get("providers")
    if isinstance(explicit, dict):
        for name, raw in explicit.items():
            providers[str(name)] = _build_dataclass(
                LLMProviderConfig, resolve_env(raw), owner=f"llm.providers.{name}"
            )
    fallbacks = data.get("fallbacks") or []
    if isinstance(fallbacks, str):
        fallbacks = [part.strip() for part in fallbacks.split(",") if part.strip()]
    return LLMConfig(
        claude=_build_dataclass(LLMProviderConfig, resolve_env(sections.get("claude")), owner="llm.claude"),
        qwen=_build_dataclass(LLMProviderConfig, resolve_env(sections.get("qwen")), owner="llm.qwen"),
        glm=_build_dataclass(LLMProviderConfig, resolve_env(sections.get("glm")), owner="llm.glm"),
        providers=providers,
        fallbacks=[str(item) for item in fallbacks if isinstance(item, str)],
    )
