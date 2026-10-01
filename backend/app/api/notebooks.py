"""Notebook library APIs: one durable subject workspace per notebook."""
from __future__ import annotations

from fastapi import APIRouter, Query, status

from ..schemas.core import NotebookConversationRequest, NotebookCreateRequest
from ..services.notebook_service import (
    create_notebook,
    get_notebook,
    list_notebooks,
    start_new_conversation,
)
from ..services.profile_service import ensure_user
from ..auth import require_current_user_id
from ..schemas.study import StudySurvey
from pydantic import BaseModel, Field
from ..services import course_learning_service as course_service
from ..services.learning_scope import course_scope, ensure_space
from ..services import study_paths
import datetime as dt
from ..schemas.reading import ReadingImport, ReadingAction
from ..services import reading_training


class CoursePrepareRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    course_key: str = Field(default="custom", max_length=40)
    source_ids: list[str] = Field(default_factory=list, max_length=6)
    survey: StudySurvey = Field(default_factory=StudySurvey)


router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])


@router.get("/{notebook_id}/reading")
def reading_library(notebook_id: str):
    return reading_training.library(require_current_user_id(), notebook_id)


@router.post("/{notebook_id}/reading/import")
def reading_import(notebook_id: str, req: ReadingImport):
    return reading_training.import_material(require_current_user_id(), notebook_id, str(req.request_id), req.material)


@router.post("/{notebook_id}/reading/examples/{sample_id}")
def reading_example(notebook_id: str, sample_id: str):
    return reading_training.start_example(require_current_user_id(), notebook_id, sample_id)


@router.get("/{notebook_id}/reading/{item_id}")
def reading_detail(notebook_id: str, item_id: str):
    return reading_training.detail(require_current_user_id(), notebook_id, item_id)


@router.post("/{notebook_id}/reading/{item_id}")
def reading_action(notebook_id: str, item_id: str, req: ReadingAction):
    return reading_training.act(require_current_user_id(), notebook_id, item_id, req)


class UnitProgressRequest(BaseModel):
    revision: int = Field(ge=0)
    version: str = Field(max_length=40)
    read: bool = False
    practiced: bool = False
    checked: bool = False
    completed: bool = False
    notes: str = Field(default="", max_length=8000)
    next_review: dt.date | None = None


@router.get("/{notebook_id}/study")
def study_path(notebook_id: str):
    return study_paths.get(require_current_user_id(), notebook_id)


@router.post("/{notebook_id}/study/{unit_id}")
def save_unit(notebook_id: str, unit_id: str, req: UnitProgressRequest):
    return study_paths.save(require_current_user_id(), notebook_id, unit_id, req.revision, req.version,
                            req.model_dump(mode="json", exclude={"revision", "version"}))


@router.get("/learning/catalogue")
async def learning_catalogue():
    return {"items": course_service.catalogue()}


@router.post("/{notebook_id}/learning/prepare")
async def prepare_learning(notebook_id: str, req: CoursePrepareRequest):
    return await course_service.prepare(require_current_user_id(), notebook_id,
        title=req.title, course_key=req.course_key, source_ids=req.source_ids,
        survey=req.survey.model_dump(mode="json"))


@router.get("/{notebook_id}/learning")
async def learning_state(notebook_id: str):
    from ..services.profile_service import get_profile
    user_id = require_current_user_id()
    row = ensure_space(user_id, notebook_id)
    with course_scope(user_id, notebook_id):
        return {"course": course_service.public_course(row.course), "profile": get_profile(user_id),
                "context": course_service.context_summary()}


@router.get("")
async def notebooks(user_id: str = Query("demo_user")):
    ensure_user(user_id)
    return {"items": list_notebooks(user_id)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(req: NotebookCreateRequest):
    ensure_user(req.user_id)
    return create_notebook(req.user_id, req.title)


@router.get("/{notebook_id}")
async def detail(notebook_id: str, user_id: str = Query("demo_user")):
    ensure_user(user_id)
    return get_notebook(user_id, notebook_id, include_messages=True)


@router.post("/{notebook_id}/conversations", status_code=status.HTTP_201_CREATED)
async def new_conversation(notebook_id: str, req: NotebookConversationRequest):
    ensure_user(req.user_id)
    return start_new_conversation(req.user_id, notebook_id)
