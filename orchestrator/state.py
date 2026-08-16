"""Pipeline state machine."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone


class PipelineState(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    QA = "qa"
    CORRECTING = "correcting"
    COMPLETED = "completed"
    FAILED = "failed"


_VALID_TRANSITIONS: dict[PipelineState, set[PipelineState]] = {
    PipelineState.PENDING: {PipelineState.RUNNING, PipelineState.FAILED},
    PipelineState.RUNNING: {PipelineState.QA, PipelineState.COMPLETED, PipelineState.FAILED},
    PipelineState.QA: {PipelineState.CORRECTING, PipelineState.COMPLETED, PipelineState.FAILED},
    PipelineState.CORRECTING: {PipelineState.RUNNING, PipelineState.FAILED},
    PipelineState.COMPLETED: set(),
    PipelineState.FAILED: {PipelineState.PENDING},
}


@dataclass
class StateTransition:
    from_state: PipelineState
    to_state: PipelineState
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str = ""


class StateMachine:
    def __init__(self, initial: PipelineState = PipelineState.PENDING) -> None:
        self._state = initial
        self._history: list[StateTransition] = []

    @property
    def state(self) -> PipelineState:
        return self._state

    @property
    def history(self) -> list[StateTransition]:
        return list(self._history)

    def transition(self, to: PipelineState, reason: str = "") -> StateTransition:
        valid = _VALID_TRANSITIONS.get(self._state, set())
        if to not in valid:
            raise ValueError(
                f"Invalid transition: {self._state.value} -> {to.value}. "
                f"Valid targets: {sorted(s.value for s in valid)}"
            )
        t = StateTransition(from_state=self._state, to_state=to, reason=reason)
        self._history.append(t)
        self._state = to
        return t

    def can_transition(self, to: PipelineState) -> bool:
        return to in _VALID_TRANSITIONS.get(self._state, set())
