"""Authenticated, server-scored baseline assessment and study calendar."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..auth import require_current_user_id
from ..services import assessment_service as service
from ..schemas.study import StudySurvey

router = APIRouter(prefix="/api/assessment", tags=["assessment"])


class StartRequest(BaseModel):
    mode: Literal["screening", "comprehensive", "foundation"] = "screening"
    survey: StudySurvey = Field(default_factory=StudySurvey)


class AnswerRequest(BaseModel):
    revision: int = Field(ge=0)
    question_id: str = Field(min_length=1, max_length=64)
    status: Literal["answered", "dont_know", "skipped"]
    choice: str | None = Field(default=None, max_length=1)
    choices: list[str] = Field(default_factory=list, max_length=5)
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    elapsed_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class TaskRequest(BaseModel):
    done: bool


class ExtendRequest(BaseModel):
    revision: int = Field(ge=0)


@router.get("")
def latest():
    return service.latest(require_current_user_id())


@router.post("/start")
def start(req: StartRequest):
    return service.start(require_current_user_id(), req.survey.model_dump(mode="json"), req.mode)


@router.post("/{assessment_id}/answers")
def answer(assessment_id: str, req: AnswerRequest):
    return service.answer(require_current_user_id(), assessment_id, req.model_dump())


@router.post("/{assessment_id}/tasks/{task_id}")
def update_task(assessment_id: str, task_id: str, req: TaskRequest):
    return service.update_task(require_current_user_id(), assessment_id, task_id, req.done)


@router.post("/{assessment_id}/replan")
def replan(assessment_id: str, req: StartRequest):
    return service.replan(require_current_user_id(), assessment_id, req.survey.model_dump(mode="json"))


@router.post("/{assessment_id}/extend")
def extend(assessment_id: str, req: ExtendRequest):
    return service.extend(require_current_user_id(), assessment_id, req.revision)
