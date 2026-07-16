"""账号认证、JWT 会话与请求级用户边界。"""
from __future__ import annotations

import datetime as dt
import logging
import re
import secrets
import uuid
from contextvars import ContextVar, Token
from pathlib import Path

import jwt
from fastapi import HTTPException
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .config import BASE_DIR, auth_required, get_settings
from .models.db import init_db, session
from .models.entities import AuthAccount, User

log = logging.getLogger("sparklearn.auth")
_PASSWORD_HASH = PasswordHash.recommended()
_CURRENT_USER: ContextVar[str | None] = ContextVar("sparklearn_current_user", default=None)
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_LOCAL_SECRET_FILE = Path(BASE_DIR).parent / ".auth_secret"
_ISSUER = "sparklearn"


def _normalize_email(email: str) -> str:
    value = str(email or "").strip().casefold()
    if len(value) > 254 or not _EMAIL_RE.fullmatch(value):
        raise HTTPException(400, "请输入有效的邮箱地址")
    return value


def _clean_name(name: str) -> str:
    value = " ".join(str(name or "").strip().split())
    return (value or "同学")[:64]


def _validate_password(password: str) -> str:
    value = str(password or "")
    if len(value) < 8:
        raise HTTPException(400, "密码至少需要 8 个字符")
    if len(value) > 128:
        raise HTTPException(400, "密码不能超过 128 个字符")
    return value


def _jwt_secret() -> str:
    configured = str(get_settings().auth_secret or "").strip()
    if configured:
        if len(configured) < 32:
            raise HTTPException(503, "AUTH_SECRET 至少需要 32 个字符")
        return configured

    # 本地首次启动自动生成随机密钥，避免把固定开发密钥写进代码。
    # 正式多实例部署仍必须配置 AUTH_SECRET，否则重建实例会使会话失效。
    try:
        if _LOCAL_SECRET_FILE.exists():
            value = _LOCAL_SECRET_FILE.read_text(encoding="utf-8").strip()
            if len(value) >= 32:
                return value
        value = secrets.token_urlsafe(48)
        _LOCAL_SECRET_FILE.write_text(value, encoding="utf-8")
        log.warning("AUTH_SECRET 未配置，已生成本地临时密钥；正式部署请设置环境变量")
        return value
    except OSError as exc:
        raise HTTPException(503, "AUTH_SECRET 未配置且无法生成本地密钥") from exc


def register_account(email: str, password: str, name: str) -> dict:
    init_db()
    normalized = _normalize_email(email)
    secret = _validate_password(password)
    user_id = f"u_{uuid.uuid4().hex}"
    with session() as db:
        existing = db.execute(
            select(AuthAccount).where(AuthAccount.email == normalized),
        ).scalars().first()
        if existing:
            raise HTTPException(409, "该邮箱已经注册")
        user = User(id=user_id, name=_clean_name(name))
        account = AuthAccount(
            user_id=user_id,
            email=normalized,
            password_hash=_PASSWORD_HASH.hash(secret),
        )
        db.add(user)
        db.add(account)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "该邮箱已经注册") from exc
    return {"id": user_id, "email": normalized, "name": user.name, "demo": False}


def authenticate_account(email: str, password: str) -> dict:
    init_db()
    normalized = _normalize_email(email)
    with session() as db:
        account = db.execute(
            select(AuthAccount).where(AuthAccount.email == normalized),
        ).scalars().first()
        if not account or not _PASSWORD_HASH.verify(str(password or ""), account.password_hash):
            raise HTTPException(401, "邮箱或密码不正确")
        user = db.get(User, account.user_id)
        if not user:
            raise HTTPException(401, "账号状态异常")
        return {"id": user.id, "email": account.email, "name": user.name, "demo": False}


def user_payload(user_id: str) -> dict:
    if user_id == "demo_user" and not auth_required():
        return {"id": "demo_user", "email": "", "name": "演示同学", "demo": True}
    init_db()
    with session() as db:
        user = db.get(User, user_id)
        account = db.get(AuthAccount, user_id)
        if not user or not account:
            raise HTTPException(401, "登录账号不存在")
        return {"id": user.id, "email": account.email, "name": user.name, "demo": False}


def create_access_token(user: dict) -> tuple[str, int]:
    now = dt.datetime.now(dt.timezone.utc)
    minutes = max(5, min(int(get_settings().auth_token_minutes or 10080), 60 * 24 * 30))
    expires = now + dt.timedelta(minutes=minutes)
    token = jwt.encode(
        {
            "sub": str(user["id"]),
            "email": str(user.get("email") or ""),
            "name": str(user.get("name") or "同学"),
            "type": "access",
            "iss": _ISSUER,
            "iat": now,
            "exp": expires,
        },
        _jwt_secret(),
        algorithm="HS256",
    )
    return token, minutes * 60


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            str(token or ""),
            _jwt_secret(),
            algorithms=["HS256"],
            issuer=_ISSUER,
        )
    except InvalidTokenError as exc:
        raise HTTPException(401, "登录已失效，请重新登录") from exc
    if payload.get("type") != "access" or not str(payload.get("sub") or "").strip():
        raise HTTPException(401, "登录凭证无效")
    return payload


def bind_request_user(user_id: str) -> Token:
    return _CURRENT_USER.set(str(user_id))


def reset_request_user(token: Token) -> None:
    _CURRENT_USER.reset(token)


def current_user_id() -> str | None:
    return _CURRENT_USER.get()


def require_current_user_id() -> str:
    user_id = current_user_id()
    if user_id:
        return user_id
    if not auth_required():
        return "demo_user"
    raise HTTPException(401, "请先登录")


def enforce_user_scope(user_id: str) -> None:
    """阻止已认证用户通过请求体或查询参数冒充另一个用户。"""
    authenticated = current_user_id()
    if authenticated and str(user_id) != authenticated:
        raise HTTPException(403, "无权访问其他用户的数据")
