"""Private reading packs: explicit provenance, bounded content and exact evidence."""
from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class ShortExercise(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context: str = Field(min_length=1, max_length=6000)
    prompt: str = Field(min_length=1, max_length=2000)
    options: list[str] = Field(min_length=2, max_length=4)
    answer: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=1, max_length=3000)

    @model_validator(mode="after")
    def valid_options(self):
        if self.answer >= len(self.options) or any(not s.strip() or len(s) > 2000 for s in self.options):
            raise ValueError("选项不能为空，答案必须对应一个选项。")
        if len(set(s.strip() for s in self.options)) != len(self.options):
            raise ValueError("选项不能重复。")
        return self


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paragraph: int = Field(ge=0, le=79)
    quote: str = Field(min_length=1, max_length=4000)


class ReadingQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    skill: str = Field(default="阅读理解", max_length=80)
    prompt: str = Field(min_length=1, max_length=2000)
    options: list[str] = Field(min_length=4, max_length=4)
    answer: int = Field(ge=0, le=3)
    evidence: Evidence
    explanation: str = Field(min_length=1, max_length=4000)
    optionFeedback: list[str] = Field(default_factory=list, max_length=4)
    takeaway: str = Field(default="", max_length=1000)
    drill: ShortExercise | None = None
    recall: ShortExercise | None = None

    @model_validator(mode="after")
    def valid_options(self):
        if any(not s.strip() or len(s) > 2000 for s in self.options):
            raise ValueError("请填写四个非空选项。")
        if len(set(s.strip() for s in self.options)) != 4:
            raise ValueError("四个选项不能重复。")
        if self.optionFeedback and (len(self.optionFeedback) != 4 or any(len(s) > 2000 for s in self.optionFeedback)):
            raise ValueError("选项解析需对应四个选项。")
        return self


class ReadingMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=180)
    englishTitle: str = Field(default="", max_length=240)
    source: str = Field(min_length=1, max_length=600)
    source_url: str = Field(default="", max_length=1200)
    source_type: Literal["past_paper", "other"] = "past_paper"
    paragraphs: list[str] = Field(min_length=1, max_length=80)
    questions: list[ReadingQuestion] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def valid_material(self):
        if not self.title.strip() or not self.source.strip():
            raise ValueError("请填写标题与具体来源。")
        if any(not p.strip() or len(p) > 8000 for p in self.paragraphs) or sum(map(len, self.paragraphs)) > 60000:
            raise ValueError("请按段落填写原文，总长度不超过 60000 字符。")
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError("题目编号不能重复。")
        for q in self.questions:
            if q.evidence.paragraph >= len(self.paragraphs) or q.evidence.quote not in self.paragraphs[q.evidence.paragraph]:
                raise ValueError(f"{q.id} 的证据必须是指定段落中的完整原句或连续片段。")
        if self.source_url:
            parsed = urlsplit(self.source_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("来源链接只接受不含登录信息的 HTTPS 地址。")
        return self


class ReadingImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Legacy BFF adds this field; ownership always comes from the verified token.
    user_id: str | None = Field(default=None, max_length=64, exclude=True)
    request_id: UUID
    material: ReadingMaterial


class ReadingAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str | None = Field(default=None, max_length=64, exclude=True)
    request_id: UUID
    revision: int = Field(ge=0)
    version: str = Field(min_length=1, max_length=64)
    action: Literal["draft", "submit", "reflect", "drill", "finish", "start_review", "review_draft", "review_submit"]
    answers: dict[str, StrictInt] = Field(default_factory=dict, max_length=10)
    uncertain: list[str] = Field(default_factory=list, max_length=10)
    note: str = Field(default="", max_length=2000)
    elapsed_seconds: int = Field(default=0, ge=0, le=86400)
    used_help: bool = False
