"""Shared helpers: JSON extraction, score coercion, retry math and atomic IO."""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import tempfile
from collections.abc import Awaitable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


class JSONExtractionError(ValueError):
    """Raised when no valid JSON value can be extracted from a model response."""


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def extract_json(text: str) -> Any:
    """Best-effort extraction of a JSON value from an LLM response.

    Handles the two classic failure modes of chat models: markdown fences and
    prose wrapped around the payload (or a payload wrapped around prose).
    """
    if not isinstance(text, str):
        raise JSONExtractionError(f"expected str, got {type(text).__name__}")

    candidates: list[str] = []
    stripped = text.strip()
    if stripped:
        candidates.append(stripped)
    candidates.extend(match.group(1).strip() for match in _FENCE_RE.finditer(text))

    expanded: list[str] = []
    for candidate in candidates:
        expanded.append(candidate)
        expanded.extend(_balanced_slices(candidate))

    seen: set[str] = set()
    for candidate in expanded:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        for attempt in (candidate, _repair(candidate)):
            try:
                return json.loads(attempt)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
    raise JSONExtractionError(f"no JSON object found in response: {truncate(text, 200)!r}")


def _balanced_slices(text: str) -> list[str]:
    """Substrings starting at each ``{``/``[`` with balanced brackets."""
    out: list[str] = []
    for start, char in enumerate(text):
        if char not in "{[":
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            current = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current in "{[":
                depth += 1
            elif current in "}]":
                depth -= 1
                if depth == 0:
                    if (char == "{" and current == "}") or (char == "[" and current == "]"):
                        out.append(text[start : index + 1])
                    break
    return out


def _repair(text: str) -> str:
    """Cheap repairs for common model JSON mistakes."""
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def coerce_score(value: Any, default: float = 0.0) -> float:
    """Normalize a model-supplied score to ``[0.0, 1.0]``.

    Accepts ``0.85``, ``"0.85"``, ``"85%"``, ``"8.5/10"`` and ``9`` (interpreted
    as a 0-10 scale, a very common LLM mistake).
    """
    if isinstance(value, bool) or value is None:
        return default
    raw: float | None = None
    percent = False
    ratio_10 = False
    if isinstance(value, (int, float)):
        raw = float(value)
    elif isinstance(value, str):
        match = _NUMBER_RE.search(value)
        if match is None:
            return default
        raw = float(match.group())
        percent = "%" in value
        ratio_10 = re.search(r"/\s*(?:10|ten)\b", value, re.IGNORECASE) is not None
    if raw is None:
        return default
    # Models mix 0-1, 0-10 and percentage scales; normalize them all to 0-1.
    if percent:
        raw /= 100.0
    elif ratio_10 or raw > 1.0:
        raw /= 10.0
    return clamp(raw, 0.0, 1.0)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def backoff_delay(
    attempt: int,
    *,
    base: float = 0.5,
    factor: float = 2.0,
    cap: float = 30.0,
    jitter: float = 0.25,
) -> float:
    """Exponential backoff with symmetric jitter, in seconds (attempt is 0-based)."""
    delay = min(cap, base * (factor**max(0, attempt)))
    if jitter:
        delay += random.uniform(-jitter, jitter) * delay
    return max(0.0, delay)


def retry_after_seconds(header_value: str | None) -> float | None:
    """Parse a ``Retry-After`` header (seconds form)."""
    if not header_value:
        return None
    try:
        return max(0.0, float(header_value.strip()))
    except ValueError:
        return None


def truncate(text: str, limit: int = 500) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def atomic_write_text(path: str | Path, text: str) -> Path:
    """Write ``text`` to ``path`` atomically (tmp file + ``os.replace``)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        with suppress_os_error():
            os.unlink(tmp_name)
        raise
    return target


def atomic_write_json(path: str | Path, data: Any) -> Path:
    return atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False, default=str))


def read_json(path: str | Path, default: Any = None) -> Any:
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


class suppress_os_error:  # noqa: N801 - context manager, lowercase reads better at call site
    """Tiny ``contextlib.suppress(OSError)`` alias that keeps the call sites short."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc_type is not None and issubclass(exc_type, OSError)


async def gather_bounded(aws: Sequence[Awaitable[T]], limit: int) -> list[T]:
    """Run awaitables concurrently with at most ``limit`` in flight, keeping order."""
    if not aws:
        return []
    if limit <= 1 or len(aws) == 1:
        return [await aw for aw in aws]
    semaphore = asyncio.Semaphore(limit)

    async def _run(awaitable: Awaitable[T]) -> T:
        async with semaphore:
            return await awaitable

    return list(await asyncio.gather(*(_run(aw) for aw in aws)))
