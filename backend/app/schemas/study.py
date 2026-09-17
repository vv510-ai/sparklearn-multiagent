"""Shared first-use and assessment context. Self-report never grades ability."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Goal = Literal["掌握课程基础", "准备课程考试", "考研 408 复习", "竞赛与算法练习", "编程项目应用", "兴趣理解", "探索学习起点", "看懂学习资料", "从零系统学习", "独立解题与纠错", "安排计划与复习", "完成项目或实践"]
Barrier = Literal["concepts", "application", "coding", "forgetting", "starting", "vocabulary", "listening", "expression", "reading_speed"]
Support = Literal["visual", "steps", "examples", "hints", "small_steps"]


class StudySurvey(BaseModel):
    notebook_id: str = Field(default="", max_length=64)
    course_key: Literal["ds_algo", "python", "calculus", "cet6", "custom"] = "ds_algo"
    course_title: str = Field(default="数据结构与算法", max_length=120)
    source_ids: list[str] = Field(default_factory=list, max_length=6)
    course_revision: str = Field(default="", max_length=64)
    target_kps: list[str] | None = Field(default=None, max_length=30)
    daily_minutes: int = Field(default=20, ge=8, le=180)
    study_days: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5], min_length=1, max_length=7)
    goal: str = Field(default="掌握课程基础", max_length=120)
    goals: list[Goal] = Field(default_factory=list, max_length=6)
    barriers: list[Barrier] = Field(default_factory=list, max_length=9)
    supports: list[Support] = Field(default_factory=list, max_length=5)
    stage: str = Field(default="大学课程", max_length=40)
    prior_experience: str = Field(default="不确定", max_length=80)
    pressure: Literal["normal", "high", "skip"] = "skip"
    study_habit: Literal["reread", "practice", "mixed", "skip"] = "skip"
    support: str = Field(default="", max_length=120)
    target_date: dt.date | None = None
    study_cue: str = Field(default="", max_length=60)
    materials_status: Literal["已有资料", "暂时没有", "稍后上传"] = "暂时没有"
    intro_practiced: bool = False

    @model_validator(mode="after")
    def check_context(self):
        if len(set(self.study_days)) != len(self.study_days) or any(day not in range(1, 8) for day in self.study_days):
            raise ValueError("请选择有效且不重复的学习日")
        for key in ("goals", "barriers", "supports"):
            values = getattr(self, key)
            if len(values) != len(set(values)):
                raise ValueError("多选项不能重复")
        if self.goals and self.goal not in self.goals:
            raise ValueError("当前优先目标必须是已选择的目标之一")
        if "探索学习起点" in self.goals and len(self.goals) > 1:
            raise ValueError("有明确目标时，请取消还不确定")
        today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
        if self.target_date and self.target_date < today:
            raise ValueError("目标日期不能早于今天")
        return self
