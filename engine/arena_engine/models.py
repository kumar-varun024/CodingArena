"""Strict request models for the implemented v1 endpoints."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(Model):
    kind: Literal["switch_context", "unverified_context", "operator_recorded", "fixture"]
    room_id: str | None
    message_id: str | None
    note: str | None


class Mutation(Model):
    request_id: UUID
    source: Source


class Labels(Model):
    a: str
    b: str


class CreateMatch(Mutation):
    task_id: Literal["booking-v1"]
    candidate_budget_minutes: Annotated[int, Field(strict=True, ge=1)]
    max_repair_rounds: Annotated[int, Field(strict=True, ge=0, le=2)]
    provider_labels: Labels


class Submit(Mutation):
    slot: Literal["a", "b"]
    commit_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]


class Action(Mutation):
    action: Literal["reveal", "start_repair", "finalize", "cancel"]
    reason: Annotated[str, Field(min_length=1, max_length=2000)]
