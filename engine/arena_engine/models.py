"""Strict request models for the implemented v1 endpoints."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from .contract import canonical_bytes
from .driver import validate_scenario


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
    a: str | None
    b: str | None

    @field_validator("a", "b")
    @classmethod
    def display_label(cls, value):
        if value is not None and not value.strip():
            raise ValueError("label must be a non-empty string or null")
        return value


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


class ChallengeRequest(Mutation):
    target_candidate_id: str
    title: Annotated[str, Field(min_length=1, max_length=240)]
    requirement_ids: Annotated[list[Literal["BOOK-01", "BOOK-02", "BOOK-03", "BOOK-04", "BOOK-05", "BOOK-06", "BOOK-07"]], Field(min_length=1, max_length=7)]
    scenario: dict

    @field_validator("requirement_ids")
    @classmethod
    def unique_requirements(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("requirement IDs must be unique")
        return value

    @field_validator("scenario")
    @classmethod
    def bounded_scenario(cls, value):
        validate_scenario(value)
        if len(canonical_bytes(value)) > 65536:
            raise ValueError("scenario exceeds input limit")
        return value


class ReviewComplete(Mutation):
    target_candidate_id: str


class ChallengeDecision(Mutation):
    disposition: Literal["accepted", "rejected"]
    reason: Annotated[str, Field(min_length=1, max_length=2000)]


class EvidenceKey(Model):
    candidate_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    spec_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    suite_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    runner_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Selection(Mutation):
    selection: Literal["a", "b", "neither"]
    candidate_id: str | None
    expected_evidence_key: EvidenceKey | None
    reason: Annotated[str, Field(min_length=1, max_length=2000)]
