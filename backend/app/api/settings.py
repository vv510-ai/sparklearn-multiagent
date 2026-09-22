"""Authenticated account settings; request bodies and keys must never be logged."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..auth import require_current_user_id
from ..services import model_preferences as preferences
from ..llm.spark_client import llm_complete

router = APIRouter(prefix="/api/settings/models", tags=["settings"])


class Update(BaseModel):
    revision: int = Field(default=0, ge=0)
    routes: dict[str, str] = Field(default_factory=dict, max_length=8)
    keys: dict[str, str] = Field(default_factory=dict, max_length=3)


class Probe(BaseModel):
    model: str = Field(max_length=80)


@router.get("")
def read():
    return preferences.view(require_current_user_id())


@router.post("")
def update(body: Update):
    return preferences.save(require_current_user_id(), body.routes, body.keys, body.revision)


@router.post("/test")
async def test(body: Probe):
    route = preferences.test_route(require_current_user_id(), body.model)
    token = preferences._OVERRIDE.set(route)
    try:
        text = await llm_complete("请只回复：连接成功", max_tokens=32, reasoning_mode="disabled", allow_mock_fallback=False, allow_model_fallback=False)
        return {"ok": True, "model": body.model, "reply": text[:80], "mode": "live"}
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from None
    finally:
        preferences._OVERRIDE.reset(token)
