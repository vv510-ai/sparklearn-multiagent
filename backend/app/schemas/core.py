"""Pydantic 请求/响应模型(API 层)。"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field(default="demo_user")
    session_id: str = Field(default="s1")
    message: str
    source_ids: list[str] = Field(default_factory=list)


class GenerateRequest(BaseModel):
    user_id: str = "demo_user"
    goal: str = Field(default="", description="学习目标自然语言,如:两周后期末考,先攻克二叉树")
    knowledge_points: list[str] = Field(default_factory=list)
    kinds: list[str] = Field(default_factory=lambda: ["doc", "mindmap", "quiz", "code", "video"])
    source_ids: list[str] = Field(default_factory=list)
    prompt_template: str = Field(default="", description="后端白名单学习模板键")


class TutorRequest(BaseModel):
    user_id: str = "demo_user"
    question: str = ""
    image_base64: Optional[str] = None
    want: Literal["text", "diagram", "video", "auto"] = "auto"


class AnswerItem(BaseModel):
    question_id: str
    answer: str
    correct: bool
    seconds: float = 0
    hint_used: bool = False
    revealed: bool = False
    misconception: str = ""


class EvalSupportRequest(BaseModel):
    user_id: str = "demo_user"
    quiz_resource_id: str
    question_id: str
    mode: Literal["hint", "reveal"]
    attempt: str = ""


class EvalSubmit(BaseModel):
    user_id: str = "demo_user"
    quiz_resource_id: str
    kp: str = ""
    answers: list[AnswerItem]
    behavior: dict[str, Any] = Field(default_factory=dict, description="停留/重看/求助等")


class RetestAnswerItem(BaseModel):
    question_id: str
    answer: str
    seconds: float = 0


class EvalRetestRequest(BaseModel):
    user_id: str = "demo_user"
    quiz_resource_id: str
    attempt_id: int = Field(gt=0)
    answers: list[RetestAnswerItem]


class ReplanRequest(BaseModel):
    user_id: str = "demo_user"
    reason: str = "评估后重排"
