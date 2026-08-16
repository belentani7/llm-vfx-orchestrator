"""Main VFX pipeline orchestration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .comfyui_client import ComfyUIClient
from .config import PipelineConfig
from .feedback_loop import FeedbackLoop
from .llm_agents import (
    AssetManagerAgent,
    CorrectionAgent,
    DirectorAgent,
    QAInspectorAgent,
)
from .state import PipelineState, StateMachine


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


class VFPPipeline:
    def __init__(self, config: PipelineConfig | None = None) -> None:
        self._config = config or PipelineConfig()
        self._comfyui = ComfyUIClient(self._config.comfyui)
        self._director = DirectorAgent(self._config.llm)
        self._qa = QAInspectorAgent(self._config.llm)
        self._assets = AssetManagerAgent(self._config.llm)
        self._correction = CorrectionAgent(self._config.llm)
        self._feedback = FeedbackLoop(self._config, self._correction)
        self._state: dict[str, StateMachine] = {}

    async def execute(self, workflow: dict[str, Any], input_data: dict[str, Any] | None = None) -> PipelineResult:
        job_id = str(uuid.uuid4())[:8]
        sm = StateMachine()
        self._state[job_id] = sm
        result = PipelineResult(job_id=job_id, status=PipelineState.PENDING, started_at=datetime.now(timezone.utc))

        try:
            sm.transition(PipelineState.RUNNING, "Starting pipeline")
            result.status = PipelineState.RUNNING

            prompt_id = await self._comfyui.queue_prompt(workflow)
            async for msg in self._comfyui.websocket_monitor(prompt_id):
                if msg.get("type") == "execution_error":
                    sm.transition(PipelineState.FAILED, "Execution error")
                    result.status = PipelineState.FAILED
                    result.error = str(msg.get("data", {}))
                    return result

            result.outputs = await self._comfyui.get_output_images(prompt_id)
            result.iterations = 1
            sm.transition(PipelineState.QA, "Render complete, starting QA")
            result.status = PipelineState.QA

            for img_name in result.outputs:
                img_bytes = await self._comfyui.download_image(img_name)
                qa = await self._qa.inspect(f"Rendered image: {img_name} ({len(img_bytes)} bytes)")
                result.qa_reports.append(qa)

            avg_score = _avg_score(result.qa_reports)
            if avg_score >= self._config.qa_threshold:
                sm.transition(PipelineState.COMPLETED, "QA passed")
                result.status = PipelineState.COMPLETED
            else:
                sm.transition(PipelineState.CORRECTING, "QA failed, correcting")
                result.status = PipelineState.CORRECTING

        except Exception as exc:
            sm.transition(PipelineState.FAILED, str(exc))
            result.status = PipelineState.FAILED
            result.error = str(exc)

        result.finished_at = datetime.now(timezone.utc)
        return result

    async def retry_with_corrections(
        self,
        workflow: dict[str, Any],
        qa_reports: list[dict[str, Any]],
        attempt: int = 0,
    ) -> PipelineResult:
        job_id = str(uuid.uuid4())[:8]
        sm = StateMachine()
        self._state[job_id] = sm
        result = PipelineResult(job_id=job_id, status=PipelineState.CORRECTING, started_at=datetime.now(timezone.utc))

        try:
            for i in range(attempt, self._config.max_retries):
                sm.transition(PipelineState.RUNNING, f"Retry attempt {i + 1}")
                result.status = PipelineState.RUNNING

                avg_score = _avg_score(qa_reports)
                if avg_score >= self._config.qa_threshold:
                    sm.transition(PipelineState.COMPLETED, "Quality passed")
                    result.status = PipelineState.COMPLETED
                    break

                plan = await self._feedback.analyze_failure(qa_reports[-1] if qa_reports else {})
                workflow = self._feedback.apply_correction(plan, workflow)

                prompt_id = await self._comfyui.queue_prompt(workflow)
                async for msg in self._comfyui.websocket_monitor(prompt_id):
                    if msg.get("type") == "execution_error":
                        sm.transition(PipelineState.FAILED, "Execution error on retry")
                        result.status = PipelineState.FAILED
                        result.error = str(msg.get("data", {}))
                        return result

                outputs = await self._comfyui.get_output_images(prompt_id)
                result.outputs = outputs
                result.iterations = i + 1

                sm.transition(PipelineState.QA, "Re-render complete, QA")
                for img_name in outputs:
                    img_bytes = await self._comfyui.download_image(img_name)
                    qa = await self._qa.inspect(f"Re-rendered image: {img_name} ({len(img_bytes)} bytes)")
                    qa_reports.append(qa)
                    result.qa_reports.append(qa)

                sm.transition(PipelineState.CORRECTING, "Evaluating for next iteration")

            else:
                if _avg_score(qa_reports) < self._config.qa_threshold:
                    sm.transition(PipelineState.FAILED, "Max retries exhausted")
                    result.status = PipelineState.FAILED
                else:
                    sm.transition(PipelineState.COMPLETED, "Passed after corrections")
                    result.status = PipelineState.COMPLETED

        except Exception as exc:
            sm.transition(PipelineState.FAILED, str(exc))
            result.status = PipelineState.FAILED
            result.error = str(exc)

        result.finished_at = datetime.now(timezone.utc)
        return result

    def get_status(self, job_id: str) -> PipelineStatus | None:
        sm = self._state.get(job_id)
        if sm is None:
            return None
        return PipelineStatus(
            job_id=job_id,
            state=sm.state,
            transitions=[(t.from_state, t.to_state, t.reason) for t in sm.history],
        )


@dataclass
class PipelineStatus:
    job_id: str
    state: PipelineState
    transitions: list[tuple[PipelineState, PipelineState, str]] = field(default_factory=list)


def _avg_score(reports: list[dict[str, Any]]) -> float:
    if not reports:
        return 0.0
    scores = [r.get("score", 0) for r in reports]
    return sum(scores) / len(scores)
