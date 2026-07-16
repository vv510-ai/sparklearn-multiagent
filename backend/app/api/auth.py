"""真实账号注册、登录与当前会话 API。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..auth import (
    authenticate_account,
    create_access_token,
    register_account,
    require_current_user_id,
    user_payload,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="同学", max_length=64)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


def _session_response(user: dict) -> dict:
    token, expires_in = create_access_token(user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": user,
    }


@router.post("/register", status_code=201)
async def register(req: RegisterRequest):
    return _session_response(register_account(req.email, req.password, req.name))


@router.post("/login")
async def login(req: LoginRequest):
    return _session_response(authenticate_account(req.email, req.password))


@router.get("/me")
async def me():
    return user_payload(require_current_user_id())
