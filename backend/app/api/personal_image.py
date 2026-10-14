"""Worker-only API, authenticated separately from user sessions."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from ..services import personal_image as service

router = APIRouter(prefix="/api/personal-image-worker", tags=["personal-image-worker"])


class Update(BaseModel):
    lease: str = Field(min_length=48, max_length=48)
    code: str = Field(default="", max_length=32)


@router.post("/claim")
async def claim():
    return {"job": service.claim()}


@router.post("/{identifier}/heartbeat")
async def heartbeat(identifier: str, update: Update):
    return service.transition(identifier, update.lease, "heartbeat")


@router.post("/{identifier}/submitted")
async def submitted(identifier: str, update: Update):
    return service.transition(identifier, update.lease, "submitted")


@router.post("/{identifier}/fail")
async def fail(identifier: str, update: Update):
    return service.transition(identifier, update.lease, "fail", update.code)


@router.post("/{identifier}/complete")
async def complete(identifier: str, request: Request):
    parts, count = [], 0
    async for chunk in request.stream():
        count += len(chunk)
        if count > service.MAX_IMAGE_BYTES:
            raise HTTPException(413, "图片超过 20 MB")
        parts.append(chunk)
    return service.complete(identifier, request.headers.get("x-image-lease", ""),
                            b"".join(parts), request.headers.get("content-type", ""))
