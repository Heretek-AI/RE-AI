"""Pure-Python state machine for planning entity status transitions.

Defines valid statuses and transitions for milestones, slices, and tasks.
The state machine is a pure function — no DB or IO dependencies — making it
trivially testable and safe to import from anywhere.

Transitions (→ means valid):
    pending → in_progress, pending (idempotent)
    in_progress → complete, errored, in_progress (idempotent)
    errored → in_progress, errored (idempotent)
    complete → complete (terminal, idempotent)
"""

VALID_STATUSES: list[str] = ["pending", "in_progress", "complete", "errored"]

# Maps from_status → set of valid to_status targets
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"in_progress", "pending"},
    "in_progress": {"complete", "errored", "in_progress"},
    "errored": {"in_progress", "errored"},
    "complete": {"complete"},
}


def validate_transition(from_status: str, to_status: str) -> bool:
    """Check whether a transition from *from_status* to *to_status* is valid.

    Returns ``True`` if the transition is allowed (including idempotent
    self-transitions). Raises ``ValueError`` when *from_status* or
    *to_status* is not a member of ``VALID_STATUSES``.
    """
    if from_status not in _VALID_TRANSITIONS:
        valid = ", ".join(VALID_STATUSES)
        raise ValueError(
            f"Invalid from_status: {from_status!r}. "
            f"Must be one of: {valid}"
        )
    if to_status not in _VALID_TRANSITIONS:
        valid = ", ".join(VALID_STATUSES)
        raise ValueError(
            f"Invalid to_status: {to_status!r}. "
            f"Must be one of: {valid}"
        )
    return to_status in _VALID_TRANSITIONS[from_status]
