"""The single owner of personal integrations (subscriptions, ChatGPT web, Claude Code).

An explicit user id wins (migrated installs). A fresh native install can name the
owner by e-mail instead, because the account is created only after setup.
"""
from __future__ import annotations

import os

_cache: dict[str, str] = {}


def resolve_owner(explicit_env: str) -> str:
    explicit = os.getenv(explicit_env, "").strip()
    if explicit:
        return explicit
    email = os.getenv("LEARNLOOP_OWNER_EMAIL", "").strip().lower()
    if not email:
        return ""
    if email in _cache:
        return _cache[email]
    try:
        from ..models.db import session
        from ..models.entities import AuthAccount
        with session() as db:
            row = db.query(AuthAccount).filter_by(email=email).first()
    except Exception:
        return ""
    if row is None:
        return ""
    _cache[email] = row.user_id
    return row.user_id
