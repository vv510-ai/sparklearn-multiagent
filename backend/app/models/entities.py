"""SQLAlchemy ORM 实体:用户/画像/资源/路径/学习事件/答题记录。"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), default="同学")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class AuthAccount(Base):
    """登录凭证与学习用户分表，避免改动既有 users 表和学习数据外键。"""
    __tablename__ = "auth_accounts"
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id"), primary_key=True,
    )
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Profile(Base):
    """≥6 维动态学生画像,JSON 形式整体存取,"随学随新"每次交互增量更新。"""
    __tablename__ = "profiles"
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Resource(Base):
    __tablename__ = "resources"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16))      # doc|mindmap|quiz|code|video|audio|image
    kp: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    safety: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class ConversationMessage(Base):
    """可跨进程恢复的学习对话，供追问和阶段性笔记整理使用。"""
    __tablename__ = "conversation_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class PathPlan(Base):
    __tablename__ = "path_plans"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)   # {nodes:[], edges:[], generated_by}
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)


class EventLog(Base):
    """学习行为日志:答题/停留/重看/求助……Eval Agent 与画像更新的数据底座。"""
    __tablename__ = "event_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    etype: Mapped[str] = mapped_column(String(32))   # answer|dwell|replay|ask|open_resource
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    quiz_resource_id: Mapped[str] = mapped_column(String(64))
    kp: Mapped[str] = mapped_column(String(64), default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class ReviewItem(Base):
    """One durable spaced-review schedule per learner and quiz question."""
    __tablename__ = "review_items"
    __table_args__ = (
        UniqueConstraint("user_id", "quiz_resource_id", "question_id",
                         name="uq_review_item_user_question"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    quiz_resource_id: Mapped[str] = mapped_column(String(64), index=True)
    question_id: Mapped[str] = mapped_column(String(64))
    kp: Mapped[str] = mapped_column(String(64), default="")
    source_attempt_id: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="scheduled")
    due_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, index=True)
    lapse_count: Mapped[int] = mapped_column(Integer, default=0)
    last_correct: Mapped[int] = mapped_column(Integer, default=-1)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)
