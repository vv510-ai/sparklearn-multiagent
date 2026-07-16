"""Request-scoped tenant identity shared by auth and persistence layers."""
from __future__ import annotations

from contextvars import ContextVar


current_user_context: ContextVar[str | None] = ContextVar(
    "sparklearn_current_user",
    default=None,
)


def current_user_id() -> str | None:
    """Return the authenticated tenant for the current async request."""
    return current_user_context.get()
