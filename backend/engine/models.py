"""Pydantic models for the planning engine API.

Request models carry the fields a caller may supply when creating
or updating an entity. Response models reflect the full row shape
returned by the engine, including server-generated fields (id,
created_at, updated_at).
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


# ── Milestone models ─────────────────────────────────────────────────────────

class MilestoneCreate(BaseModel):
    title: str
    description: str = ""


class MilestoneUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class MilestoneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime


# ── Slice models ─────────────────────────────────────────────────────────────

class SliceCreate(BaseModel):
    title: str
    description: str = ""


class SliceUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    order: Optional[int] = None


class SliceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    milestone_id: int
    title: str
    description: str
    status: str
    order: int
    created_at: datetime
    updated_at: datetime


# ── Task models ──────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str
    description: str = ""


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


class TaskStatusUpdate(BaseModel):
    status: str


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slice_id: int
    title: str
    description: str
    status: str
    order: int
    created_at: datetime
    updated_at: datetime
