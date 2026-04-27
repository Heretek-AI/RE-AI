"""Planning engine — state machine, CRUD, and Pydantic models.

Convenience imports so callers can use::

    from backend.engine import (
        PlanningEngine,
        validate_transition,
        VALID_STATUSES,
        MilestoneCreate, MilestoneResponse, MilestoneUpdate,
        SliceCreate, SliceResponse, SliceUpdate,
        TaskCreate, TaskResponse, TaskUpdate, TaskStatusUpdate,
    )
"""

from backend.engine.models import (
    MilestoneCreate,
    MilestoneResponse,
    MilestoneUpdate,
    SliceCreate,
    SliceResponse,
    SliceUpdate,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
    TaskStatusUpdate,
)
from backend.engine.planning import PlanningEngine
from backend.engine.state_machine import VALID_STATUSES, validate_transition

__all__ = [
    "PlanningEngine",
    "validate_transition",
    "VALID_STATUSES",
    "MilestoneCreate",
    "MilestoneResponse",
    "MilestoneUpdate",
    "SliceCreate",
    "SliceResponse",
    "SliceUpdate",
    "TaskCreate",
    "TaskResponse",
    "TaskUpdate",
    "TaskStatusUpdate",
]
