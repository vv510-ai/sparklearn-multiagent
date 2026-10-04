"""The model writes bounded prose; dates, arithmetic and actions stay in code."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cet6 import Skill

Sentence = Annotated[str, Field(min_length=8, max_length=900)]


class AdviceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # The shared browser helper adds this legacy field. Authentication, never
    # the supplied value, selects the report owner.
    user_id: str | None = Field(default=None, max_length=64, exclude=True)
    profile_revision: int = Field(ge=1)


class AdviceSection(BaseModel):
    # Persist only teaching fields; harmless extra model metadata must not lose a report.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    kind: Skill
    title: str = Field(min_length=2, max_length=45)
    body: str = Field(min_length=80, max_length=3600)


class TargetBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")
    listening: int = Field(ge=0, le=249)
    reading: int = Field(ge=0, le=249)
    writing_translation: int = Field(ge=0, le=212)
    reason: str = Field(min_length=30, max_length=700)


class AdviceStage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=2, max_length=35)
    text: Sentence


class AdviceText(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    summary: str = Field(min_length=30, max_length=600)
    score_analysis: str = Field(min_length=80, max_length=2600)
    priority_kind: Skill
    rationale: Sentence
    uncertainty: Sentence
    target_breakdown: TargetBreakdown | None = None
    sections: list[AdviceSection] = Field(min_length=5, max_length=5)
    plan_explanation: str = Field(min_length=30, max_length=1200)
    closing: str = Field(min_length=30, max_length=800)
    week_note: Sentence
    stages: list[AdviceStage] = Field(min_length=1, max_length=3)
    followup_keys: list[Literal["preparation", "reading_completion"]] = Field(max_length=2)

    @model_validator(mode="after")
    def complete_sections(self):
        if {s.kind for s in self.sections} != {"reading", "listening", "writing", "translation", "vocabulary"}:
            raise ValueError("Every learning section must appear exactly once")
        if len(set(self.followup_keys)) != len(self.followup_keys):
            raise ValueError("Repeated follow-up")
        return self
