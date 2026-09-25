"""Authenticated course-library API. No public administrative publishing endpoint."""
from typing import Literal
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from ..auth import require_current_user_id
from ..services import course_library as service

router = APIRouter(prefix="/api/library", tags=["course-library"])

class EnrollRequest(BaseModel):
    release_id: str = Field(min_length=1, max_length=96)

class ProgressRequest(BaseModel):
    action: Literal["read", "answer", "work", "listen", "reveal_work"]
    revision: int = Field(ge=0)
    audio_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    question_id: str | None = Field(default=None, max_length=64)
    choice: int | None = Field(default=None, ge=0, le=3)
    assisted: bool = False
    work: str = Field(default="", max_length=8000)
    self_checked: list[int] = Field(default_factory=list, max_length=10)

class IssueRequest(BaseModel):
    description: str = Field(min_length=3, max_length=2000)

@router.get("")
def catalogue():
    return service.catalogue(require_current_user_id())

@router.post("/enroll")
def enroll(req: EnrollRequest):
    return service.enroll(require_current_user_id(), req.release_id)

@router.get("/studies/{study_id}")
def state(study_id: str):
    return service.state(require_current_user_id(), study_id)

@router.get("/studies/{study_id}/lessons/{lesson_id}")
def lesson(study_id: str, lesson_id: str):
    return service.lesson(require_current_user_id(), study_id, lesson_id)

@router.post("/studies/{study_id}/lessons/{lesson_id}")
def progress(study_id: str, lesson_id: str, req: ProgressRequest):
    return service.update_progress(require_current_user_id(), study_id, lesson_id, req.model_dump())

@router.post("/studies/{study_id}/lessons/{lesson_id}/issues")
def issue(study_id: str, lesson_id: str, req: IssueRequest):
    service.report_issue(require_current_user_id(), study_id, lesson_id, req.description)
    return {"saved": True}


@router.get("/releases/{release_id}/media/{lesson_id}")
def scene_audio(release_id: str, lesson_id: str):
    require_current_user_id()
    bundle, _ = service.load_release(release_id)
    selected = next((x for x in bundle["lessons"] if x["id"] == lesson_id), None)
    if not selected or not selected.get("scene"):
        raise HTTPException(404, "本课没有场景音频")
    from ..services.english_scene_library import media_file
    try:
        path = media_file(selected["scene"]["audio"])
    except ValueError:
        raise HTTPException(503, "音频暂不可用，可继续文字学习")
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "private, no-store"})


@router.get("/releases/{release_id}/sections/{section_id}")
def original_source(release_id: str, section_id: str):
    require_current_user_id()
    bundle, _ = service.load_release(release_id)
    section = next((s for s in bundle["textbook"]["sections"] if s["id"] == section_id), None)
    if not section:
        raise HTTPException(404, "来源小节不存在")
    return PlainTextResponse(section["title"] + "\n版本：" + bundle["textbook"]["version"] + "\n\n" + section["text"],
                             headers={"Cache-Control": "private, no-store"})
