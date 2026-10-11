"""Main VFX pipeline: render → QA → correct → re-render, with persistence."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .comfyui_client import ComfyUIClient, OutputImage, image_name
from .config import PipelineConfig
from .feedback_loop import FeedbackLoop
from .llm_agents import (
    AssetManagerAgent,
    CorrectionAgent,
    DirectorAgent,
    QAInspectorAgent,
    normalize_qa_report,
)
from .state import TERMINAL_STATES, PipelineState, StateMachine
from .store import JobStore
from .template import apply_template_defaults, load_template
from .utils import coerce_score, gather_bounded, truncate, utcnow

logger = logging.getLogger(__name__)

_MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "mp4": "video/mp4",
    "webm": "video/webm",
}


def new_job_id() -> str:
    return uuid.uuid4().hex[:8]


def guess_media_type(filename: str) -> str:
    suffix = Path(str(filename)).suffix.lower().lstrip(".")
    return _MEDIA_TYPES.get(suffix, "image/png")


@dataclass
class PipelineResult:
    job_id: str
    status: PipelineState
    outputs: list[str] = field(default_factory=list)
    iterations: int = 0
    qa_reports: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    prompt: str | None = None
    score: float | None = None
    best_score: float | None = None
    escalation_reason: str | None = None
    kind: str = "run"
    corrections: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    output_objects: list[dict[str, str]] = field(default_factory=list)

    @property
    def renders(self) -> int:
        return self.iterations

    @property
    def ok(self) -> bool:
        return self.status is PipelineState.COMPLETED

    @property
    def needs_review(self) -> bool:
        return self.status is PipelineState.ESCALATED

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "job_id": self.job_id,
            "status": self.status.value,
            "kind": self.kind,
            "ok": self.ok,
            "outputs": list(self.outputs),
            "output_objects": list(self.output_objects),
            "iterations": self.iterations,
            "score": self.score,
            "best_score": self.best_score,
            "error": self.error,
            "escalation_reason": self.escalation_reason,
            "prompt": self.prompt,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "corrections": self.corrections,
            "metrics": self.metrics,
            "transitions": self.transitions,
            "qa_reports": [
                {
                    "score": report.get("score"),
                    "issues": report.get("issues", [])[:6],
                    "summary": truncate(str(report.get("summary", "")), 300),
                    "degraded": bool(report.get("degraded")),
                }
                for report in self.qa_reports[:20]
            ],
        }
        return data


@dataclass
class PipelineStatus:
    job_id: str
    state: PipelineState
    transitions: list[tuple[PipelineState, PipelineState, str]] = field(default_factory=list)
    score: float | None = None
    updated_at: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES


class VFPPipeline:
    """Closed-loop orchestration of one or many render jobs."""

    def __init__(
        self,
        config: PipelineConfig | None = None,
        *,
        comfyui: ComfyUIClient | None = None,
        store: JobStore | None = None,
        director: DirectorAgent | None = None,
        qa: QAInspectorAgent | None = None,
        assets: AssetManagerAgent | None = None,
        correction: CorrectionAgent | None = None,
        feedback: FeedbackLoop | None = None,
    ) -> None:
        self._config = config or PipelineConfig()
        self._comfyui = comfyui or ComfyUIClient(self._config.comfyui)
        self._director = director or DirectorAgent(self._config.llm)
        self._qa = qa or QAInspectorAgent(self._config.llm)
        self._assets = assets or AssetManagerAgent(self._config.llm)
        self._correction = correction or CorrectionAgent(self._config.llm)
        self._feedback = feedback or FeedbackLoop(self._config, self._correction)
        self._store = store if store is not None else JobStore(self._config.jobs_dir)
        self._state: dict[str, StateMachine] = {}

    # ------------------------------------------------------------------ lifecycle
    async def close(self) -> None:
        await self._comfyui.close()

    async def __aenter__(self) -> VFPPipeline:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------ entrypoints
    async def execute(
        self,
        workflow: dict[str, Any] | None = None,
        input_data: dict[str, Any] | None = None,
        *,
        prompt: str | None = None,
        job_id: str | None = None,
        persist: bool = True,
        max_retries: int | None = None,
    ) -> PipelineResult:
        """Run a workflow to completion (planning first when only a prompt is given)."""
        payload = input_data or {}
        workflow = workflow or payload.get("workflow")
        prompt = prompt or payload.get("prompt")
        if not workflow:
            if not prompt:
                raise ValueError("execute() needs a workflow, a prompt, or input_data with either")
            return await self.execute_prompt(prompt, job_id=job_id, persist=persist, max_retries=max_retries)
        return await self._run(
            job_id=job_id or new_job_id(),
            workflow=workflow,
            prompt=prompt,
            kind="run",
            persist=persist,
            max_retries=max_retries,
        )

    async def plan_prompt(
        self,
        prompt: str,
        *,
        template: str | Path | dict[str, Any] | None = None,
        use_assets: bool | None = None,
    ) -> dict[str, Any]:
        """Director plans a ComfyUI workflow for ``prompt`` (optionally asset-aware)."""
        template_data = self._resolve_template(template)
        want_assets = (
            bool(template_data.get("use_assets", self._config.template.get("use_assets", False)))
            if use_assets is None
            else use_assets
        )
        asset_hints: dict[str, Any] | None = None
        if want_assets:
            inventory = list(template_data.get("available_assets") or []) or None
            try:
                asset_hints = await self._assets.find_assets(prompt, available=inventory)
            except Exception as exc:  # noqa: BLE001 - assets are an optimization, not a blocker
                logger.warning("asset manager unavailable: %s", truncate(str(exc), 200))
        workflow = await self._director.plan(prompt, template=template_data or None, asset_hints=asset_hints)
        return apply_template_defaults(workflow, template_data)

    async def execute_prompt(
        self,
        prompt: str,
        *,
        template: str | Path | dict[str, Any] | None = None,
        use_assets: bool | None = None,
        job_id: str | None = None,
        persist: bool = True,
        max_retries: int | None = None,
    ) -> PipelineResult:
        """Director plans a workflow for ``prompt`` and runs it end to end."""
        workflow = await self.plan_prompt(prompt, template=template, use_assets=use_assets)
        return await self._run(
            job_id=job_id or new_job_id(),
            workflow=workflow,
            prompt=prompt,
            kind="prompt",
            persist=persist,
            max_retries=max_retries,
        )

    async def run_batch(
        self,
        jobs: Sequence[Any],
        *,
        concurrency: int | None = None,
        persist: bool = True,
    ) -> list[PipelineResult]:
        """Run many jobs concurrently (bounded by ``concurrency``, order preserved).

        Each item is a workflow dict, a path to a workflow JSON file, a prompt string,
        or a mapping with ``workflow``/``prompt``/``template``/``job_id`` keys.
        """
        limit = concurrency or self._config.concurrency
        results = await gather_bounded(
            [self._run_spec(spec, persist=persist) for spec in jobs],
            max(1, int(limit)),
        )
        return list(results)

    async def retry_with_corrections(
        self,
        workflow: dict[str, Any],
        qa_reports: list[dict[str, Any]] | None = None,
        attempt: int = 0,
        *,
        job_id: str | None = None,
        persist: bool = True,
    ) -> PipelineResult:
        """Deprecated shim kept for API compatibility — re-runs the closed loop."""
        seed = [coerce_score(report.get("score", 0)) for report in (qa_reports or [])]
        return await self._run(
            job_id=job_id or new_job_id(),
            workflow=workflow,
            kind="retry",
            persist=persist,
            seed_scores=seed,
        )

    async def run_retry(self, job_id: str, *, persist: bool = True) -> PipelineResult:
        """Re-run a stored job (workflow or prompt) under the current config."""
        record = self._store.get(job_id)
        if record is None:
            raise KeyError(f"job {job_id} not found in {self._store.directory}")
        workflow = record.get("workflow")
        prompt = record.get("prompt")
        if isinstance(workflow, dict) and workflow:
            return await self._run(
                job_id=new_job_id(),
                workflow=workflow,
                prompt=prompt if isinstance(prompt, str) else None,
                kind="retry",
                persist=persist,
            )
        if isinstance(prompt, str) and prompt:
            return await self.execute_prompt(prompt, persist=persist)
        raise ValueError(f"job {job_id} has neither a stored workflow nor a prompt to retry")

    # ------------------------------------------------------------------ status
    def get_status(self, job_id: str) -> PipelineStatus | None:
        machine = self._state.get(job_id)
        if machine is not None:
            return PipelineStatus(
                job_id=job_id,
                state=machine.state,
                transitions=[(t.from_state, t.to_state, t.reason) for t in machine.history],
            )
        record = self._store.get(job_id)
        if record is None:
            return None
        state_raw = str(record.get("status", "pending"))
        try:
            state = PipelineState(state_raw)
        except ValueError:
            state = PipelineState.PENDING
        transitions = [
            (
                PipelineState(item.get("from", "pending")),
                PipelineState(item.get("to", "pending")),
                str(item.get("reason", "")),
            )
            for item in (record.get("transitions") or [])
            if isinstance(item, dict)
        ]
        score = record.get("score")
        return PipelineStatus(
            job_id=job_id,
            state=state,
            transitions=transitions,
            score=float(score) if isinstance(score, (int, float)) else None,
            updated_at=record.get("updated_at"),
        )

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._store.list(limit=limit)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self._store.get(job_id)

    # ------------------------------------------------------------------ internals
    def _resolve_template(self, template: str | Path | dict[str, Any] | None) -> dict[str, Any]:
        if template is None:
            return dict(self._config.template)
        if isinstance(template, dict):
            return dict(template)
        return load_template(template)

    async def _run_spec(self, spec: Any, *, persist: bool) -> PipelineResult:
        try:
            if isinstance(spec, Mapping):
                if _looks_like_workflow(spec):
                    return await self.execute(json.loads(json.dumps(spec)), persist=persist)
                prompt = spec.get("prompt")
                workflow = spec.get("workflow")
                job_id = spec.get("job_id")
                retries = spec.get("max_retries")
                job_retries = int(retries) if isinstance(retries, (int, float, str)) else None
                if workflow:
                    return await self.execute(
                        dict(workflow),
                        prompt=prompt,
                        job_id=job_id,
                        persist=persist,
                        max_retries=job_retries,
                    )
                if prompt:
                    return await self.execute_prompt(
                        str(prompt),
                        template=spec.get("template"),
                        job_id=job_id,
                        persist=persist,
                        max_retries=job_retries,
                    )
                raise ValueError("job mapping needs a 'workflow' or a 'prompt'")
            if isinstance(spec, (str, Path)):
                text = str(spec)
                path = Path(text)
                if path.exists() and path.is_file():
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return await self.execute(data, persist=persist)
                if text.lstrip().startswith("{"):
                    return await self.execute(json.loads(text), persist=persist)
                return await self.execute_prompt(text, persist=persist)
            raise TypeError(f"unsupported job spec: {type(spec).__name__}")
        except Exception as exc:  # noqa: BLE001 - one bad job must not sink the batch
            logger.error("job spec failed before rendering: %s", exc)
            result = PipelineResult(
                job_id=new_job_id(),
                status=PipelineState.FAILED,
                error=truncate(str(exc), 400),
                started_at=utcnow(),
                finished_at=utcnow(),
            )
            self._persist(result, None, persist)
            return result

    async def _run(
        self,
        *,
        job_id: str,
        workflow: dict[str, Any],
        prompt: str | None = None,
        kind: str = "run",
        persist: bool = True,
        max_retries: int | None = None,
        seed_scores: list[float] | None = None,
    ) -> PipelineResult:
        config = self._config
        budget = config.max_retries if max_retries is None else max_retries
        machine = StateMachine()
        self._state[job_id] = machine
        result = PipelineResult(
            job_id=job_id,
            status=PipelineState.PENDING,
            started_at=utcnow(),
            prompt=prompt,
            kind=kind,
        )
        history: list[float] = list(seed_scores or [])
        current = json.loads(json.dumps(workflow))
        started = time.monotonic()
        self._persist(result, current, persist)

        try:
            machine.transition(PipelineState.RUNNING, "Starting pipeline")
            result.status = PipelineState.RUNNING
            attempt = 0
            while True:
                render_started = time.monotonic()
                prompt_id = await self._comfyui.queue_prompt(current)
                outcome = await self._comfyui.wait_for_prompt(
                    prompt_id, timeout=config.comfyui.ws_timeout
                )
                render_s = time.monotonic() - render_started
                result.iterations += 1
                result.metrics["renders"] = result.iterations
                result.metrics["total_render_s"] = round(
                    result.metrics.get("total_render_s", 0.0) + render_s, 3
                )
                result.metrics["last_render_s"] = round(render_s, 3)
                logger.info(
                    "job %s render #%s -> %s (%.1fs)",
                    job_id,
                    result.iterations,
                    outcome.status,
                    render_s,
                )
                self._persist(result, current, persist)

                if not outcome.ok:
                    await self._abort_render(outcome.status)
                    message = outcome.error or f"render ended with status={outcome.status}"
                    if config.correct_execution_errors and attempt < budget:
                        machine.transition(
                            PipelineState.CORRECTING,
                            truncate(f"render {outcome.status}: {message}", 180),
                        )
                        result.status = PipelineState.CORRECTING
                        current, changed = await self._correct(
                            current, result, attempt, error_log=message, persist=persist
                        )
                        if not changed:
                            result.error = message
                            result.escalation_reason = "correction produced no change — needs manual review"
                            machine.transition(PipelineState.ESCALATED, "No usable correction")
                            result.status = PipelineState.ESCALATED
                            break
                        attempt += 1
                        machine.transition(PipelineState.RUNNING, f"Retry attempt {attempt}")
                        result.status = PipelineState.RUNNING
                        self._persist(result, current, persist)
                        continue
                    result.error = message
                    machine.transition(PipelineState.FAILED, truncate(message, 180))
                    result.status = PipelineState.FAILED
                    break

                outputs = await self._comfyui.get_output_images(prompt_id)
                result.outputs = [image_name(image) for image in outputs]
                result.output_objects = [
                    image.as_dict()
                    if isinstance(image, OutputImage)
                    else {"filename": image_name(image), "subfolder": "", "type": "output", "node_id": ""}
                    for image in outputs
                ]

                if not outputs:
                    message = "render finished but produced no output images"
                    if config.correct_execution_errors and attempt < budget:
                        machine.transition(PipelineState.CORRECTING, message)
                        result.status = PipelineState.CORRECTING
                        current, changed = await self._correct(
                            current, result, attempt, error_log=message, persist=persist
                        )
                        if not changed:
                            result.error = message
                            result.escalation_reason = "no outputs and no usable correction"
                            machine.transition(PipelineState.ESCALATED, "No usable correction")
                            result.status = PipelineState.ESCALATED
                            break
                        attempt += 1
                        machine.transition(PipelineState.RUNNING, f"Retry attempt {attempt}")
                        result.status = PipelineState.RUNNING
                        self._persist(result, current, persist)
                        continue
                    result.error = message
                    machine.transition(PipelineState.FAILED, message)
                    result.status = PipelineState.FAILED
                    break

                machine.transition(PipelineState.QA, "Render complete, starting QA")
                result.status = PipelineState.QA
                qa_started = time.monotonic()
                round_reports = await self._inspect(outputs)
                result.metrics["total_qa_s"] = round(
                    result.metrics.get("total_qa_s", 0.0) + (time.monotonic() - qa_started), 3
                )
                result.qa_reports.extend(round_reports)
                round_score = _avg_score(round_reports)
                history.append(round_score)
                result.score = round_score
                result.best_score = max(history)

                result.metrics["worst_score"] = min(
                    [coerce_score(report.get("score", 0)) for report in round_reports] or [0.0]
                )
                self._persist(result, current, persist)

                if round_reports and all(report.get("degraded") for report in round_reports):
                    result.error = "quality assessment unavailable (every inspector call failed)"
                    result.escalation_reason = "QA unavailable — cannot verify output"
                    machine.transition(PipelineState.ESCALATED, result.escalation_reason)
                    result.status = PipelineState.ESCALATED
                    break

                if round_score >= config.qa_threshold:
                    machine.transition(
                        PipelineState.COMPLETED, f"QA passed with score {round_score:.3f}"
                    )
                    result.status = PipelineState.COMPLETED
                    break

                if attempt >= budget:
                    result.escalation_reason = f"max_retries={budget} exhausted (score {round_score:.3f})"
                    machine.transition(PipelineState.ESCALATED, result.escalation_reason)
                    result.status = PipelineState.ESCALATED
                    break

                if self._feedback.is_plateau(history):
                    result.escalation_reason = (
                        f"no meaningful improvement over {config.plateau_patience} attempt(s) "
                        f"(score {round_score:.3f})"
                    )
                    machine.transition(PipelineState.ESCALATED, result.escalation_reason)
                    result.status = PipelineState.ESCALATED
                    break

                machine.transition(
                    PipelineState.CORRECTING, f"QA failed ({round_score:.3f}) — correcting"
                )
                result.status = PipelineState.CORRECTING
                current, changed = await self._correct(
                    current, result, attempt, persist=persist
                )
                if not changed:
                    result.escalation_reason = "correction produced no change — needs manual review"
                    machine.transition(PipelineState.ESCALATED, result.escalation_reason)
                    result.status = PipelineState.ESCALATED
                    break
                attempt += 1
                machine.transition(PipelineState.RUNNING, f"Retry attempt {attempt}")
                result.status = PipelineState.RUNNING
                self._persist(result, current, persist)

        except Exception as exc:  # noqa: BLE001 - any failure becomes a failed job
            logger.exception("job %s failed", job_id)
            result.error = truncate(str(exc), 400)
            if machine.can_transition(PipelineState.FAILED):
                machine.transition(PipelineState.FAILED, result.error)
            result.status = PipelineState.FAILED

        result.transitions = machine.history_dicts()
        result.metrics["total_s"] = round(time.monotonic() - started, 3)
        result.finished_at = utcnow()
        if result.score is None and history:
            result.score = history[-1]
            result.best_score = max(history)
        self._persist(result, current, persist)
        return result

    async def _abort_render(self, status: str) -> None:
        """Timeout/interrupt leaves work queued on the GPU — ask ComfyUI to stop it."""
        if status in {"timeout", "unknown"}:
            try:
                await self._comfyui.interrupt()
            except Exception as exc:  # noqa: BLE001
                logger.debug("interrupt after %s failed: %s", status, exc)

    async def _correct(
        self,
        workflow: dict[str, Any],
        result: PipelineResult,
        attempt: int,
        *,
        error_log: str = "",
        persist: bool = True,
    ) -> tuple[dict[str, Any], bool]:
        """Ask the correction agent for a patch; returns ``(workflow, changed)``."""
        corrected = workflow
        changed = False
        qa_report = result.qa_reports[-1] if result.qa_reports else {}
        started = time.monotonic()
        try:
            plan = await self._feedback.analyze_failure(
                qa_report,
                error_log=error_log,
                workflow=workflow,
                prior_corrections=result.corrections,
            )
            corrected = self._feedback.apply_correction(plan, workflow)
            changed = corrected != workflow
            result.corrections.append(
                {
                    "attempt": attempt + 1,
                    "reason": truncate(plan.reason, 300),
                    "nodes": plan.affected_nodes[:20],
                    "changed": changed,
                    "error_log": truncate(error_log, 200) if error_log else "",
                }
            )
        except Exception as exc:  # noqa: BLE001 - a broken LLM must not crash the job
            logger.warning("correction attempt %s failed: %s", attempt + 1, exc)
            result.corrections.append(
                {
                    "attempt": attempt + 1,
                    "reason": f"correction agent failed: {truncate(str(exc), 200)}",
                    "nodes": [],
                    "changed": False,
                    "error_log": truncate(error_log, 200) if error_log else "",
                }
            )
            changed = False
        result.metrics["total_correction_s"] = round(
            result.metrics.get("total_correction_s", 0.0) + (time.monotonic() - started), 3
        )
        self._persist(result, corrected, persist)
        return corrected, changed

    async def _inspect(self, outputs: Sequence[Any]) -> list[dict[str, Any]]:
        config = self._config
        targets = list(outputs)[: config.max_qa_images]
        criteria = str(config.template.get("qa_criteria", "") or "")
        attach_images = self._vision_enabled()
        semaphore_limit = config.qa_concurrency

        async def _one(image: Any) -> dict[str, Any]:
            name = image_name(image)
            node_id = getattr(image, "node_id", "")
            try:
                data = await self._comfyui.download_image(image)
            except Exception as exc:  # noqa: BLE001
                return normalize_qa_report(
                    {
                        "score": 0.0,
                        "issues": [f"download failed: {truncate(str(exc), 160)}"],
                        "summary": "image unavailable for QA",
                        "degraded": True,
                    }
                )
            description = f"Rendered image: {name} ({len(data)} bytes"
            description += f", node {node_id})" if node_id else ")"
            image_bytes = data if attach_images and len(data) <= config.vision_max_bytes else None
            context = "" if image_bytes is not None else "pixels not attached; judged from metadata only"
            try:
                report = await self._qa.inspect(
                    description,
                    criteria,
                    image=image_bytes,
                    image_media_type=guess_media_type(name),
                    extra_context=context,
                )
                report.setdefault("file", name)
                return report
            except Exception as exc:  # noqa: BLE001
                return normalize_qa_report(
                    {
                        "score": 0.0,
                        "issues": [f"QA failed: {truncate(str(exc), 160)}"],
                        "summary": "inspector unavailable",
                        "degraded": True,
                    }
                )

        return await gather_bounded([_one(image) for image in targets], semaphore_limit)

    def _vision_enabled(self) -> bool:
        role = getattr(self._qa, "role", "qwen")
        provider = self._config.llm.get(role)
        return bool(provider and provider.vision) if provider is not None else True

    def _persist(self, result: PipelineResult, workflow: dict[str, Any] | None, persist: bool) -> None:
        if not persist or self._store is None:
            return
        payload = result.as_dict()
        if workflow is not None:
            payload["workflow"] = workflow
        self._store.save(result.job_id, payload)


def _looks_like_workflow(candidate: Mapping[str, Any]) -> bool:
    """A raw ComfyUI graph maps node ids to objects carrying ``class_type``."""
    if "prompt" in candidate or "workflow" in candidate:
        return False
    values = [value for value in candidate.values() if isinstance(value, Mapping)]
    if not values:
        return False
    return all("class_type" in value for value in values)


def _avg_score(reports: list[dict[str, Any]]) -> float:
    if not reports:
        return 0.0
    scores = [coerce_score(report.get("score", 0)) for report in reports]
    return sum(scores) / len(scores)


__all__ = [
    "PipelineResult",
    "PipelineStatus",
    "VFPPipeline",
    "guess_media_type",
    "new_job_id",
]
