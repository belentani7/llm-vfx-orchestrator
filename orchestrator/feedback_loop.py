"""Autonomous correction feedback loop (workflow-aware, plateau-aware)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .config import PipelineConfig
from .llm_agents import CorrectionAgent
from .utils import coerce_score

logger = logging.getLogger(__name__)


@dataclass
class CorrectionPlan:
    patch: dict[str, Any]
    reason: str
    affected_nodes: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.patch


class FeedbackLoop:
    """Decides *whether* to retry and *what* to change; never renders anything."""

    def __init__(self, config: PipelineConfig, correction_agent: CorrectionAgent | None = None) -> None:
        self._config = config
        self._agent = correction_agent or CorrectionAgent(config.llm)

    async def analyze_failure(
        self,
        qa_report: dict[str, Any],
        error_log: str = "",
        *,
        workflow: dict[str, Any] | None = None,
        prior_corrections: list[dict[str, Any]] | None = None,
    ) -> CorrectionPlan:
        """Ask the correction agent for a patch; empty patch when already passing."""
        if qa_report.get("score") is not None and coerce_score(qa_report.get("score")) >= self._config.qa_threshold:
            return CorrectionPlan(patch={}, reason="Quality above threshold — no correction needed")

        patch = await self._agent.generate_fix(
            workflow=workflow or {},
            qa_report=qa_report,
            error_log=error_log,
            prior_corrections=prior_corrections,
        )
        affected = [str(node) for node in patch if node not in {"__new_nodes__", "__remove_nodes__"}]
        if isinstance(patch.get("__new_nodes__"), dict):
            affected.extend(str(node) for node in patch["__new_nodes__"])
        return CorrectionPlan(
            patch=patch,
            reason=str(qa_report.get("summary") or error_log or "Quality below threshold"),
            affected_nodes=affected,
        )

    def apply_correction(self, plan: CorrectionPlan, workflow: dict[str, Any]) -> dict[str, Any]:
        if plan.is_empty:
            return workflow
        return self._agent.apply_patch(workflow, plan.patch)

    # ------------------------------------------------------------------ policy
    def should_retry(self, qa_report: dict[str, Any], attempt: int) -> bool:
        if attempt >= self._config.max_retries:
            return False
        score = coerce_score(qa_report.get("score", 0))
        return score < self._config.qa_threshold

    def should_escalate(self, qa_report: dict[str, Any], attempt: int) -> bool:
        if attempt < self._config.max_retries:
            return False
        return coerce_score(qa_report.get("score", 0)) < self._config.qa_threshold

    def is_plateau(self, history: list[float]) -> bool:
        """True when the last ``plateau_patience`` corrections stopped helping.

        Retrying a stalled loop only burns GPU time and API budget, so the pipeline
        escalates to manual review instead.
        """
        patience = self._config.plateau_patience
        if patience <= 0 or len(history) < patience + 1:
            return False
        best_so_far = max(history[:-1])
        recent = history[-patience:]
        return all(score - best_so_far < self._config.min_score_improvement for score in recent)
