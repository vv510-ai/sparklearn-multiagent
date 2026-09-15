"""Authenticated, server-scored baseline assessment and study calendar."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from ..auth import require_current_user_id
from ..services import assessment_service as service

router = APIRouter(prefix="/api/assessment", tags=["assessment"])


class StudySurvey(BaseModel):
    daily_minutes: int = Field(default=30, ge=8, le=180)
    study_days: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5], min_length=1, max_length=7)
    goal: str = Field(default="掌握课程基础", max_length=120)
    stage: str = Field(default="大学课程", max_length=40)
    prior_experience: str = Field(default="不确定", max_length=80)
    pressure: Literal["normal", "high", "skip"] = "skip"
    study_habit: Literal["reread", "practice", "mixed", "skip"] = "skip"
    support: str = Field(default="", max_length=120)
    target_date: dt.date | None = None

    @model_validator(mode="after")
    def check_calendar(self):
        if len(set(self.study_days)) != len(self.study_days) or any(day not in range(1, 8) for day in self.study_days):
            raise ValueError("请选择有效且不重复的学习日")
        today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
        if self.target_date and self.target_date < today:
            raise ValueError("目标日期不能早于今天")
        return self


class StartRequest(BaseModel):
    mode: Literal["comprehensive", "foundation"] = "comprehensive"
    survey: StudySurvey = Field(default_factory=StudySurvey)


class AnswerRequest(BaseModel):
    revision: int = Field(ge=0)
    question_id: str = Field(min_length=1, max_length=64)
    status: Literal["answered", "dont_know", "skipped"]
    choice: str | None = Field(default=None, max_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    elapsed_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class TaskRequest(BaseModel):
    done: bool


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
