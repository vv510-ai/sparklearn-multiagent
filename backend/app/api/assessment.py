"""Authenticated, server-scored baseline assessment and study calendar."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..auth import require_current_user_id
from ..services import assessment_service as service
from ..schemas.study import StudySurvey
from ..services.learning_scope import scoped_endpoint

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


class PracticeRequest(BaseModel):
    kp: str = Field(min_length=1, max_length=64)


class PracticeAnswerRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=64)
    choice: Literal["A", "B", "C", "D"] | None = None
    assisted: bool = False


@router.post("/{assessment_id}/practice")
@scoped_endpoint
def practice(assessment_id: str, req: PracticeRequest):
    from ..services import assessment_practice
    return assessment_practice.begin(require_current_user_id(), assessment_id, req.kp)


@router.post("/{assessment_id}/practice/answers")
@scoped_endpoint
def practice_answer(assessment_id: str, req: PracticeAnswerRequest):
    from ..services import assessment_practice
    return assessment_practice.answer(require_current_user_id(), assessment_id, req.question_id, req.choice, req.assisted)


@router.get("")
@scoped_endpoint
def latest(notebook_id: str = ""):
    return service.latest(require_current_user_id())


@router.post("/start")
@scoped_endpoint
def start(req: StartRequest):
    user = require_current_user_id()
    if not req.survey.notebook_id:
        raise HTTPException(409, "请先打开课程，按原教材学习，或上传自己的资料后进行检查。")
    return service.start(user, req.survey.model_dump(mode="json"), req.mode,
                         req.survey.course_revision, req.survey.target_kps)


@router.post("/{assessment_id}/answers")
@scoped_endpoint
def answer(assessment_id: str, req: AnswerRequest):
    return service.answer(require_current_user_id(), assessment_id, req.model_dump())


@router.post("/{assessment_id}/tasks/{task_id}")
@scoped_endpoint
def update_task(assessment_id: str, task_id: str, req: TaskRequest):
    return service.update_task(require_current_user_id(), assessment_id, task_id, req.done)


@router.post("/{assessment_id}/replan")
@scoped_endpoint
def replan(assessment_id: str, req: StartRequest):
    return service.replan(require_current_user_id(), assessment_id, req.survey.model_dump(mode="json"))


@router.post("/{assessment_id}/extend")
@scoped_endpoint
def extend(assessment_id: str, req: ExtendRequest):
    from ..services.learning_scope import current_space
    require_current_user_id()
    if not current_space():
        raise HTTPException(409, "旧测评已保留，请进入当前课程继续学习。")
    return service.extend(require_current_user_id(), assessment_id, req.revision)
