"""Agent event type constants and Literal type for validation.

Defines the allowed event_type values for AgentEventDraft.
C must use these exact values when submitting events.
"""

from __future__ import annotations

from typing import Literal

# Allowed event types per Issue #13 C-D contract
AGENT_EVENT_TYPES: frozenset[str] = frozenset({
    "run.started",
    "agent.started",
    "agent.summary",
    "agent.completed",
    "run.waiting_user",
    "run.completed",
    "run.failed",
    "heartbeat",
})

AgentEventType = Literal[
    "run.started",
    "agent.started",
    "agent.summary",
    "agent.completed",
    "run.waiting_user",
    "run.completed",
    "run.failed",
    "heartbeat",
]
