"""Explicit learner preferences and bounded, revisioned learning actions."""
import datetime as dt
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

Skill = Literal["listening", "reading", "writing", "translation", "vocabulary"]


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(default="", max_length=300)
    target_score: int | None = Field(default=None, ge=0, le=710)
    exam_date: dt.date | None = None
    daily_minutes: int = Field(default=20, ge=5, le=180)
    daily_new_words: int = Field(default=20, ge=0, le=200)
    mode: Literal["foundation", "balanced", "exam"] = "balanced"
    focus: list[Skill] = Field(default_factory=list, max_length=5)
    total_score: int | None = Field(default=None, ge=0, le=710)
    listening_score: int | None = Field(default=None, ge=0, le=249)
    reading_score: int | None = Field(default=None, ge=0, le=249)
    writing_translation_score: int | None = Field(default=None, ge=0, le=212)
    preparation: Literal["unknown", "none", "irregular", "regular"] = "unknown"
    reading_completion: Literal["unknown", "finished", "unfinished", "not_taken"] = "unknown"

    @model_validator(mode="after")
    def validate_scores(self):
        self.focus = list(dict.fromkeys(self.focus))
        scores = [self.listening_score, self.reading_score, self.writing_translation_score]
        if self.total_score is not None and all(s is not None for s in scores) and sum(scores) != self.total_score:
            raise ValueError("三项成绩与总分不一致，请按同一张成绩单填写，或留空未知项。")
        return self


class ProfileSave(BaseModel):
    revision: int = Field(ge=0)
    preferences: Preferences


class WordTargetSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str | None = Field(default=None, max_length=64, exclude=True)
    revision: int = Field(ge=0)
    daily_new_words: int = Field(ge=0, le=200)


class WordAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str | None = Field(default=None, max_length=64, exclude=True)
    request_id: UUID
    revision: int = Field(ge=0)
    version: str = Field(max_length=64)
    sense_id: str = Field(min_length=1, max_length=64)
    action: Literal["collect", "start", "reveal", "rate"]
    mode: Literal["meaning", "spelling"] = "meaning"
    answer: str = Field(default="", max_length=500)
    rating: Literal["again", "hard", "good", "easy"] = "again"
    used_help: bool = False
    context: str = Field(default="", max_length=1500)
    context_note: str = Field(default="", max_length=500)
    reading_id: str = Field(default="", max_length=64)
    question_id: str = Field(default="", max_length=64)
    paper_id: str = Field(default="", max_length=64)
    paper_question: int | None = Field(default=None, ge=26, le=55)


class PaperAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str | None = Field(default=None, max_length=64, exclude=True)
    request_id: UUID
    revision: int = Field(ge=0)
    action: Literal["save", "submit", "restart"]
    answers: dict[str, str] = Field(default_factory=dict, max_length=30)
    writing: str = Field(default="", max_length=10000)
    translation: str = Field(default="", max_length=10000)
    reflection: str = Field(default="", max_length=3000)
    used_help: bool = False


class ExamAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str | None = Field(default=None, max_length=64, exclude=True)
    request_id: UUID
    revision: int = Field(ge=0)
    version: str = Field(min_length=1, max_length=64)
    action: Literal["save", "submit", "restart"]
    answers: dict[str, str] = Field(default_factory=dict, max_length=30)
    text: str = Field(default="", max_length=10000)
    allow_incomplete: bool = False


class WordRoundStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str | None = Field(default=None, max_length=64, exclude=True)
    request_id: UUID
    kind: Literal["new", "review"]


class PracticeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str | None = Field(default=None, max_length=64, exclude=True)
    request_id: UUID
    revision: int = Field(ge=0)
    action: Literal["draft", "submit", "finish", "restart"]
    answer: str = Field(default="", max_length=10000)
    revision_text: str = Field(default="", max_length=10000)
    reflection: str = Field(default="", max_length=1500)
    used_help: bool = False
    timed: bool = False
