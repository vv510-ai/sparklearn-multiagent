"""Worker-only API, authenticated separately from user sessions."""
from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, Field
from typing import Literal
from ..services import personal_image as service

router = APIRouter(prefix="/api/personal-image-worker", tags=["personal-image-worker"])

Phase = Literal["", "connect", "prepare_prompt", "submit", "wait_image", "continue_more", "read_image", "upload_image"]


class Update(BaseModel):
    lease: str = Field(min_length=48, max_length=48)
    code: str = Field(default="", max_length=32)
    phase: Phase = ""


class Finish(BaseModel):
    lease: str = Field(min_length=48, max_length=48)
    count: int = Field(ge=1, le=service.MAX_IMAGES)
    conversation_url: str = Field(default="", max_length=120)


async def _body(request: Request) -> bytes:
    parts, count = [], 0
    async for chunk in request.stream():
        count += len(chunk)
        if count > service.MAX_IMAGE_BYTES:
            raise HTTPException(413, "图片超过 20 MB")
        parts.append(chunk)
    return b"".join(parts)


@router.post("/claim")
async def claim():
    return {"job": service.claim()}


@router.post("/{identifier}/heartbeat")
async def heartbeat(identifier: str, update: Update):
    return service.transition(identifier, update.lease, "heartbeat", phase=update.phase)


@router.post("/{identifier}/submitted")
async def submitted(identifier: str, update: Update):
    return service.transition(identifier, update.lease, "submitted", phase=update.phase)


@router.post("/{identifier}/fail")
async def fail(identifier: str, update: Update):
    return service.transition(identifier, update.lease, "fail", update.code)


@router.post("/{identifier}/complete")
async def complete(identifier: str, request: Request):
    return service.complete(identifier, request.headers.get("x-image-lease", ""),
                            await _body(request), request.headers.get("content-type", ""))


@router.post("/{identifier}/image/{index}")
async def image(identifier: str, request: Request, index: int = Path(ge=1, le=service.MAX_IMAGES)):
    return service.store_image(identifier, request.headers.get("x-image-lease", ""), index,
                               await _body(request), request.headers.get("content-type", ""))


@router.post("/{identifier}/finish")
async def finish(identifier: str, body: Finish):
    return service.finish(identifier, body.lease, body.count, body.conversation_url)
