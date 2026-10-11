"""Pipeline state machine (with escalation and JSON round-tripping)."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


class PipelineState(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    QA = "qa"
    CORRECTING = "correcting"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    FAILED = "failed"


_VALID_TRANSITIONS: dict[PipelineState, set[PipelineState]] = {
    PipelineState.PENDING: {PipelineState.RUNNING, PipelineState.FAILED},
    PipelineState.RUNNING: {
        PipelineState.QA,
        PipelineState.CORRECTING,
        PipelineState.COMPLETED,
        PipelineState.ESCALATED,
        PipelineState.FAILED,
    },
    PipelineState.QA: {
        PipelineState.CORRECTING,
        PipelineState.RUNNING,
        PipelineState.COMPLETED,
        PipelineState.ESCALATED,
        PipelineState.FAILED,
    },
    PipelineState.CORRECTING: {
        PipelineState.RUNNING,
        PipelineState.QA,
        PipelineState.COMPLETED,
        PipelineState.ESCALATED,
        PipelineState.FAILED,
    },
    PipelineState.COMPLETED: set(),
    PipelineState.ESCALATED: {PipelineState.RUNNING, PipelineState.PENDING, PipelineState.COMPLETED},
    PipelineState.FAILED: {PipelineState.PENDING, PipelineState.RUNNING},
}

TERMINAL_STATES = frozenset({PipelineState.COMPLETED, PipelineState.FAILED, PipelineState.ESCALATED})


@dataclass
class StateTransition:
    from_state: PipelineState
    to_state: PipelineState
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_state.value,
            "to": self.to_state.value,
            "at": self.timestamp.isoformat(),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StateTransition:
        return cls(
            from_state=PipelineState(data.get("from", "pending")),
            to_state=PipelineState(data.get("to", "pending")),
            timestamp=_parse_ts(data.get("at")),
            reason=str(data.get("reason", "")),
        )


def _parse_ts(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    return datetime.now(UTC)


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

    @property
    def is_terminal(self) -> bool:
        return self._state in TERMINAL_STATES

    def transition(self, to: PipelineState, reason: str = "") -> StateTransition:
        valid = _VALID_TRANSITIONS.get(self._state, set())
        if to not in valid:
            raise ValueError(
                f"Invalid transition: {self._state.value} -> {to.value}. "
                f"Valid targets: {sorted(s.value for s in valid)}"
            )
        transition = StateTransition(from_state=self._state, to_state=to, reason=reason)
        self._history.append(transition)
        self._state = to
        return transition

    def can_transition(self, to: PipelineState) -> bool:
        return to in _VALID_TRANSITIONS.get(self._state, set())

    def history_dicts(self) -> list[dict[str, Any]]:
        return [transition.as_dict() for transition in self._history]
