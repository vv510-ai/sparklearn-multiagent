"""Public source catalogue; private learning records."""
import datetime as dt
from typing import Literal
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from ..auth import require_current_user_id
from ..services import study_materials as service

router = APIRouter(prefix="/api/materials", tags=["study-materials"])

class AddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    material_id: str = Field(min_length=1, max_length=96)

class SaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    task: str = Field(max_length=500)
    location: str = Field(max_length=300)
    notes: str = Field(max_length=8000)
    minutes: int = Field(ge=0, le=100000)
    next_review: dt.date | None = None
    status: Literal["planned", "learning", "review", "done"]

@router.get("")
def catalogue():
    return service.catalogue()

@router.get("/studies")
def studies():
    return service.studies(require_current_user_id())

@router.post("/studies")
def add(req: AddRequest):
    return service.add(require_current_user_id(), req.material_id)

@router.post("/studies/{study_id}")
def save(study_id: str, req: SaveRequest):
    return service.save(require_current_user_id(), study_id, req.revision,
        req.model_dump(mode="json", exclude={"revision"}))
