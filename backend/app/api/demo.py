"""Authenticated controls for the repeatable final-review demonstration."""
from __future__ import annotations

from fastapi import APIRouter

from ..auth import require_current_user_id
from ..services.final_review_demo_service import (
    final_review_status,
    prepare_final_review,
    restore_final_review,
)

router = APIRouter(prefix="/api/demo/final-review", tags=["demo"])


@router.get("")
async def status():
    return final_review_status(require_current_user_id())


@router.post("/prepare")
async def prepare():
    return prepare_final_review(require_current_user_id())


@router.post("/restore")
async def restore():
    return restore_final_review(require_current_user_id())
