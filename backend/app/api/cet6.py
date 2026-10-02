from fastapi import APIRouter, Query
from typing import Literal
from ..auth import require_current_user_id
from ..schemas.cet6 import ProfileSave, WordAction, PracticeAction
from ..services import cet6_learning as learning, cet6_vocabulary as vocabulary, cet6_practice as practice

router = APIRouter(prefix="/api/notebooks/{notebook_id}/cet6", tags=["cet6"])


@router.get("")
def overview(notebook_id: str):
    return learning.overview(require_current_user_id(), notebook_id)


@router.post("/preferences")
def preferences(notebook_id: str, req: ProfileSave):
    return learning.save_profile(require_current_user_id(), notebook_id, req.revision, req.preferences)


@router.get("/words")
def words(notebook_id: str, q: str = Query(default="", max_length=100),
          group: Literal["all", "foundation", "cet6"] = "all", view: Literal["all", "today", "mine"] = "all",
          offset: int = Query(default=0, ge=0, le=20000), limit: int = Query(default=30, ge=1, le=60)):
    return vocabulary.catalogue(require_current_user_id(), notebook_id, q, group, view, offset, limit)


@router.get("/words/{entry_id}")
def word(notebook_id: str, entry_id: str):
    return vocabulary.detail(require_current_user_id(), notebook_id, entry_id)


@router.post("/words/{entry_id}")
def word_action(notebook_id: str, entry_id: str, req: WordAction):
    return vocabulary.act(require_current_user_id(), notebook_id, entry_id, req)


@router.get("/practice")
def practice_list(notebook_id: str):
    return practice.catalogue(require_current_user_id(), notebook_id)


@router.get("/practice/{task_id}")
def practice_detail(notebook_id: str, task_id: str):
    return practice.detail(require_current_user_id(), notebook_id, task_id)


@router.post("/practice/{task_id}")
def practice_action(notebook_id: str, task_id: str, req: PracticeAction):
    return practice.act(require_current_user_id(), notebook_id, task_id, req)
