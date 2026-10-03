"""The model writes bounded prose; dates, arithmetic and actions stay in code."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cet6 import Skill

Sentence = Annotated[str, Field(min_length=8, max_length=500)]
Step = Annotated[str, Field(min_length=8, max_length=220)]


class AdviceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # The shared browser helper adds this legacy field. Authentication, never
    # the supplied value, selects the report owner.
    user_id: str | None = Field(default=None, max_length=64, exclude=True)
    profile_revision: int = Field(ge=1)


class AdviceSection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Skill
    title: str = Field(min_length=2, max_length=45)
    analysis: Sentence
    steps: list[Step] = Field(min_length=2, max_length=4)
    check: Sentence


class AdviceStage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=2, max_length=35)
    text: Sentence


class AdviceText(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    summary: str = Field(min_length=30, max_length=600)
    priority_kind: Skill
    rationale: Sentence
    uncertainty: Sentence
    sections: list[AdviceSection] = Field(min_length=5, max_length=5)
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
