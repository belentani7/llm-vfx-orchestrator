"""Durable job store — makes ``vfp status``/``vfp retry`` work across processes."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from .utils import atomic_write_json, read_json, utcnow

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
_MAX_WORKFLOW_BYTES = 2_000_000


class JobStore:
    """File-per-job JSON store (atomic writes, tolerant of corrupt files)."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, job_id: str) -> Path:
        """Reject invalid IDs rather than collapsing distinct jobs onto one file.

        The previous sanitization mapped `../job` and `job` to the same
        path. Job IDs are opaque ASCII keys, never filesystem paths.
        """
        if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", job_id):
            raise ValueError("job_id must contain 1–120 ASCII letters, digits, underscores or hyphens")
        return self.directory / f"{job_id}.json"

    def save(self, job_id: str, payload: dict[str, Any]) -> bool:
        """Persist a job record; invalid IDs raise, serialization/disk failures return False."""
        record = dict(payload)
        record["job_id"] = job_id
        record.setdefault("schema_version", SCHEMA_VERSION)
        record.setdefault("updated_at", utcnow().isoformat())
        workflow = record.get("workflow")
        if isinstance(workflow, dict):
            try:
                import json

                # ComfyUI workflows must remain JSON data, never Python reprs.
                # Reject objects and non-finite numbers instead of silently
                # persisting an unusable graph via default=str.
                encoded = json.dumps(
                    workflow, indent=2, ensure_ascii=False, allow_nan=False,
                ).encode("utf-8")
                if len(encoded) > _MAX_WORKFLOW_BYTES:
                    record["workflow"] = None
                    record["workflow_truncated"] = True
            except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
                # Circular, deeply nested and non-JSON workflows must never block the
                # status record, and omission must be visible to consumers.
                record["workflow"] = None
                record["workflow_omitted_reason"] = "invalid_serialization"
        # Validate the ID before the recovery boundary: unsafe paths are caller errors.
        path = self.path_for(job_id)
        try:
            atomic_write_json(path, record)
            return True
        except (OSError, ValueError, TypeError, UnicodeError) as exc:
            # A cyclic metadata object or malformed Unicode must not crash a job
            # or overwrite its last valid status. Never log potentially private payloads.
            logger.warning("could not persist job %s (%s)", job_id, type(exc).__name__)
            return False

    def get(self, job_id: str) -> dict[str, Any] | None:
        data = read_json(self.path_for(job_id))
        return data if isinstance(data, dict) else None

    def exists(self, job_id: str) -> bool:
        return self.path_for(job_id).exists()

    def delete(self, job_id: str) -> bool:
        try:
            self.path_for(job_id).unlink()
            return True
        except OSError:
            return False

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        """Most recent jobs first (by start time, falling back to mtime)."""
        records: list[dict[str, Any]] = []
        try:
            paths = list(self.directory.glob("*.json"))
        except OSError as exc:  # pragma: no cover - unreadable dir
            logger.warning("could not list jobs: %s", exc)
            return []
        for path in paths:
            data = read_json(path)
            if isinstance(data, dict):
                data.setdefault("job_id", path.stem)
                records.append(data)
        records.sort(key=lambda r: str(r.get("started_at") or r.get("updated_at") or ""), reverse=True)
        return records[:limit]
