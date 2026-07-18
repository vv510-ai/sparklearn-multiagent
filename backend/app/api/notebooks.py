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


router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])


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
