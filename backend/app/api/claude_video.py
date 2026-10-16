"""Claude teaching videos: owner settings, learner actions and the paired local worker."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import require_current_user_id
from ..services import claude_video as service

settings_router = APIRouter(prefix="/api/settings/claude-video", tags=["settings"])
video_router = APIRouter(prefix="/api/claude-video", tags=["claude-video"])
worker_router = APIRouter(prefix="/api/claude-video-worker", tags=["claude-video-worker"])

Phase = Literal["", "prepare", "storyboard", "voice", "compose", "review", "render", "check", "upload"]


class SettingsUpdate(BaseModel):
    revision: int = Field(default=0, ge=0)
    config: dict = Field(default_factory=dict, max_length=12)
    api_key: str | None = Field(default=None, max_length=400)


class Approval(BaseModel):
    notes: str = Field(default="", max_length=400)


class WorkerInfo(BaseModel):
    info: dict = Field(default_factory=dict, max_length=12)


class Update(BaseModel):
    lease: str = Field(min_length=48, max_length=48)
    phase: Phase = ""
    message: str = Field(default="", max_length=200)


class StoryboardBody(BaseModel):
    lease: str = Field(min_length=48, max_length=48)
    storyboard: dict


class Finish(BaseModel):
    lease: str = Field(min_length=48, max_length=48)
    meta: dict = Field(default_factory=dict, max_length=12)


class Failure(BaseModel):
    lease: str = Field(min_length=48, max_length=48)
    code: str = Field(default="worker_error", max_length=32)
    detail: str = Field(default="", max_length=300)


class Ping(BaseModel):
    lease: str = Field(min_length=48, max_length=48)
    ok: bool
    reply: str = Field(default="", max_length=200)
    code: str = Field(default="", max_length=32)
    detail: str = Field(default="", max_length=300)


@settings_router.get("")
def read_settings():
    return service.view(require_current_user_id())


@settings_router.post("")
def save_settings(body: SettingsUpdate):
    return service.save(require_current_user_id(), body.config, body.api_key, body.revision)


@settings_router.post("/test")
def test_settings():
    return {"test": service.queue_test(require_current_user_id())}


def _task(task_id: str) -> str:
    if not service.is_task(task_id):
        raise HTTPException(404, "视频任务不存在")
    return task_id


@video_router.post("/{task_id}/approve")
def approve(task_id: str, body: Approval):
    return service.approve(require_current_user_id(), _task(task_id), body.notes)


@video_router.post("/{task_id}/cancel")
def cancel(task_id: str):
    return service.cancel(require_current_user_id(), _task(task_id))


@video_router.post("/{task_id}/retry")
def retry(task_id: str):
    return service.retry(require_current_user_id(), _task(task_id))


async def _body(request: Request, limit: int) -> bytes:
    parts, count = [], 0
    async for chunk in request.stream():
        count += len(chunk)
        if count > limit:
            raise HTTPException(413, "上传内容过大")
        parts.append(chunk)
    return b"".join(parts)


@worker_router.post("/hello")
def hello(body: WorkerInfo):
    service.hello(require_current_user_id(), body.info)
    return {"ok": True}


@worker_router.post("/claim")
def claim(body: WorkerInfo):
    return {"job": service.claim(require_current_user_id(), body.info)}


@worker_router.post("/{identifier}/heartbeat")
def heartbeat(identifier: str, body: Update):
    return service.heartbeat(identifier, body.lease, body.phase, body.message)


@worker_router.post("/{identifier}/storyboard")
def storyboard(identifier: str, body: StoryboardBody):
    return service.store_storyboard(identifier, body.lease, body.storyboard)


@worker_router.post("/{identifier}/video")
async def video(identifier: str, request: Request):
    return service.store_video(identifier, request.headers.get("x-video-lease", ""),
                               await _body(request, service.MAX_VIDEO_BYTES))


@worker_router.post("/{identifier}/poster")
async def poster(identifier: str, request: Request):
    return service.store_poster(identifier, request.headers.get("x-video-lease", ""),
                                await _body(request, service.MAX_POSTER_BYTES), request.headers.get("content-type", ""))


@worker_router.post("/{identifier}/finish")
def finish(identifier: str, body: Finish):
    return service.finish(identifier, body.lease, body.meta)


@worker_router.post("/{identifier}/fail")
def fail(identifier: str, body: Failure):
    return service.fail(identifier, body.lease, body.code, body.detail)


@worker_router.post("/{identifier}/ping")
def ping(identifier: str, body: Ping):
    return service.finish_ping(identifier, body.lease, body.ok, body.reply, body.code, body.detail)
