"""Pydantic 请求/响应模型(API 层)。"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field(default="demo_user")
    session_id: str = Field(default="s1")
    message: str
    topic_label: str = ""
    source_ids: list[str] = Field(default_factory=list)


class GenerateRequest(BaseModel):
    user_id: str = "demo_user"
    session_id: str = ""
    goal: str = Field(default="", description="学习目标自然语言,如:两周后期末考,先攻克二叉树")
    conversation_focus: str = Field(default="", description="最近一轮真实学习问题，用于工坊产物随对话切换主题")
    topic_label: str = Field(default="", description="当前学习笔记本的主题")
    knowledge_points: list[str] = Field(default_factory=list)
    kinds: list[str] = Field(default_factory=lambda: ["doc", "mindmap", "quiz", "code", "video"])
    source_ids: list[str] = Field(default_factory=list)
    prompt_template: str = Field(default="", description="后端白名单学习模板键")
    artifact_scope: Literal["current_topic", "conversation"] = Field(
        default="current_topic",
        description="学习产物覆盖当前主题或整段会话",
    )


class AudioRetryRequest(BaseModel):
    user_id: str = "demo_user"


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
    confidence: Literal["", "guess", "unsure", "confident"] = ""


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
    confidence: Literal["", "guess", "unsure", "confident"] = ""


class EvalRetestRequest(BaseModel):
    user_id: str = "demo_user"
    quiz_resource_id: str
    attempt_id: int = Field(gt=0)
    answers: list[RetestAnswerItem]


class ReviewSubmitItem(BaseModel):
    review_item_id: int = Field(gt=0)
    answer: str
    seconds: float = 0
    confidence: Literal["", "guess", "unsure", "confident"] = ""


class EvalReviewRequest(BaseModel):
    user_id: str = "demo_user"
    items: list[ReviewSubmitItem]


class MistakeFavoriteRequest(BaseModel):
    user_id: str = "demo_user"
    favorite: bool = True


class MistakePracticeRequest(BaseModel):
    user_id: str = "demo_user"
    answer: str
    seconds: float = 0
    confidence: Literal["", "guess", "unsure", "confident"] = ""


class RemediationRequest(BaseModel):
    user_id: str = "demo_user"
    attempt_id: int = Field(gt=0)


class ReplanRequest(BaseModel):
    user_id: str = "demo_user"
    reason: str = "评估后重排"
