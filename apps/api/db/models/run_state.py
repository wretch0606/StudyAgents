"""AgentRun state machine — valid status transitions.

Following the convention of module-level set constants (see IngestionJob).
"""

from __future__ import annotations

# ---- Status constants ----
QUEUED = "queued"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"

ALL_STATUSES: set[str] = {QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED}

# ---- Transition map ----
VALID_TRANSITIONS: dict[str, set[str]] = {
    QUEUED:    {RUNNING},
    RUNNING:   {COMPLETED, FAILED, CANCELLED},
    FAILED:    {QUEUED},        # retry
    COMPLETED: set(),           # terminal
    CANCELLED: set(),           # terminal
}


def validate_transition(current: str, target: str) -> None:
    """Raise ValueError if the transition is invalid."""
    if current not in ALL_STATUSES:
        raise ValueError(f"Unknown current status: {current}")
    if target not in ALL_STATUSES:
        raise ValueError(f"Unknown target status: {target}")
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(
            f"Invalid state transition: {current} -> {target}. "
            f"Allowed: {sorted(allowed)}"
        )
