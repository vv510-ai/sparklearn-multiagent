from fastapi import APIRouter, Query
from typing import Literal
from ..auth import require_current_user_id
from ..schemas.cet6 import ProfileSave, WordAction, PracticeAction, WordTargetSave, PaperAction
from ..services import cet6_learning as learning, cet6_vocabulary as vocabulary, cet6_practice as practice
from ..services import cet6_word_plan as word_plan
from ..services import vocabulary_lessons
from ..services import cet6_papers as papers
from ..services import cet6_exams as exams
from ..schemas.cet6 import ExamAction

router = APIRouter(prefix="/api/notebooks/{notebook_id}/cet6", tags=["cet6"])


@router.get("/exams")
def exam_catalogue(notebook_id: str):
    return exams.catalogue(require_current_user_id(), notebook_id)


@router.get("/exams/{paper_id}/{kind}")
def exam_detail(notebook_id: str, paper_id: str, kind: str):
    return exams.detail(require_current_user_id(), notebook_id, paper_id, kind)


@router.post("/exams/{paper_id}/{kind}")
def exam_action(notebook_id: str, paper_id: str, kind: str, req: ExamAction):
    return exams.act(require_current_user_id(), notebook_id, paper_id, kind, req)


@router.post("/exams/{paper_id}/{kind}/review")
async def exam_review(notebook_id: str, paper_id: str, kind: str):
    return await exams.review(require_current_user_id(), notebook_id, paper_id, kind)


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


@router.get("/word-plan")
def daily_word_plan(notebook_id: str):
    return word_plan.today(require_current_user_id(), notebook_id)


@router.post("/word-plan")
def word_target(notebook_id: str, req: WordTargetSave):
    return word_plan.save_target(require_current_user_id(), notebook_id, req.revision, req.daily_new_words)


@router.get("/words/{entry_id}")
def word(notebook_id: str, entry_id: str):
    return vocabulary.detail(require_current_user_id(), notebook_id, entry_id)


@router.post("/words/{entry_id}")
def word_action(notebook_id: str, entry_id: str, req: WordAction):
    return vocabulary.act(require_current_user_id(), notebook_id, entry_id, req)


@router.get("/words/{entry_id}/lesson")
def word_lesson(notebook_id: str, entry_id: str, sense_id: str = Query(min_length=1, max_length=64)):
    return vocabulary_lessons.get(require_current_user_id(), notebook_id, entry_id, sense_id)


@router.post("/words/{entry_id}/lesson")
async def generate_word_lesson(notebook_id: str, entry_id: str, sense_id: str = Query(min_length=1, max_length=64)):
    return await vocabulary_lessons.generate(require_current_user_id(), notebook_id, entry_id, sense_id)


@router.get("/practice")
def practice_list(notebook_id: str):
    return practice.catalogue(require_current_user_id(), notebook_id)


@router.get("/papers")
def paper_list(notebook_id: str):
    return papers.catalogue(require_current_user_id(), notebook_id)


@router.get("/papers/{paper_id}")
def paper_detail(notebook_id: str, paper_id: str):
    return papers.detail(require_current_user_id(), notebook_id, paper_id)


@router.post("/papers/{paper_id}")
def paper_action(notebook_id: str, paper_id: str, req: PaperAction):
    return papers.act(require_current_user_id(), notebook_id, paper_id, req)


@router.get("/practice/{task_id}")
def practice_detail(notebook_id: str, task_id: str):
    return practice.detail(require_current_user_id(), notebook_id, task_id)


@router.post("/practice/{task_id}")
def practice_action(notebook_id: str, task_id: str, req: PracticeAction):
    return practice.act(require_current_user_id(), notebook_id, task_id, req)
