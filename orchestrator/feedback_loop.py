"""Autonomous correction feedback loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import PipelineConfig
from .llm_agents import CorrectionAgent


@dataclass
class CorrectionPlan:
    patch: dict[str, Any]
    reason: str
    affected_nodes: list[str] = field(default_factory=list)


class FeedbackLoop:
    def __init__(self, config: PipelineConfig, correction_agent: CorrectionAgent | None = None) -> None:
        self._config = config
        self._agent = correction_agent or CorrectionAgent(config.llm)

    async def analyze_failure(
        self,
        qa_report: dict[str, Any],
        error_log: str = "",
    ) -> CorrectionPlan:
        if qa_report.get("score", 0) >= self._config.qa_threshold:
            return CorrectionPlan(patch={}, reason="Quality above threshold — no correction needed")

        patch = await self._agent.generate_fix(
            workflow={},
            qa_report=qa_report,
            error_log=error_log,
        )
        return CorrectionPlan(
            patch=patch,
            reason=qa_report.get("summary", "Quality below threshold"),
            affected_nodes=list(patch.keys()),
        )

    def apply_correction(
        self,
        plan: CorrectionPlan,
        workflow: dict[str, Any],
    ) -> dict[str, Any]:
        if not plan.patch:
            return workflow
        return self._agent.apply_patch(workflow, plan.patch)

    def should_retry(self, qa_report: dict[str, Any], attempt: int) -> bool:
        if attempt >= self._config.max_retries:
            return False
        score = qa_report.get("score", 0)
        return score < self._config.qa_threshold

    def should_escalate(self, qa_report: dict[str, Any], attempt: int) -> bool:
        if attempt < self._config.max_retries:
            return False
        return qa_report.get("score", 0) < self._config.qa_threshold
