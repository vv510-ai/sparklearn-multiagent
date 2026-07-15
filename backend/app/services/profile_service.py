"""画像服务:≥6 维动态学生画像的持久化与"随学随新"增量更新。

8 个维度(超出赛题 ≥6 维要求):
1 knowledge_mastery  各知识点掌握度 0-1(BKT 更新)
2 cognitive_style    认知风格:视觉型/语言型/动手型
3 error_prone        易错点偏好(高频错误知识点与错误类型)
4 goal               学习目标/动机:应试/竞赛/工程实践/兴趣
5 pace               学习节奏与投入(时长/频率/专注度)
6 difficulty_pref    难度偏好:循序渐进 vs 挑战式
7 resource_pref      资源类型偏好(各类点击/完成率)
8 metacognition      元认知水平(自评准确度、求助频率)
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select

from ..models.db import init_db, session
from ..models.entities import EventLog, Profile, User
from ..services.bkt import bkt_update
from ..services.knowledge_graph import all_kp_ids, canonical_kp_id

_PROFILE_FIELDS = {
    "knowledge_mastery", "cognitive_style", "error_prone", "goal", "pace",
    "difficulty_pref", "resource_pref", "metacognition", "evidence",
}
_COGNITIVE_STYLES = {"视觉型", "语言型", "动手型"}
_GOALS = {"应试", "竞赛", "工程实践", "兴趣"}
_DIFFICULTY_PREFS = {"循序渐进", "挑战式"}
_RESOURCE_KINDS = {"doc", "video", "quiz", "mindmap", "code"}
_FOCUS_LEVELS = {"高", "中", "低"}


def default_profile() -> dict:
    return {
        "knowledge_mastery": {kp: 0.30 for kp in all_kp_ids()},
        "cognitive_style": "未知",
        "error_prone": [],
        "goal": "未知",
        "pace": {"frequency": "未知", "focus": "中"},
        "difficulty_pref": "循序渐进",
        "resource_pref": {"doc": 0.2, "video": 0.2, "quiz": 0.2, "mindmap": 0.2, "code": 0.2},
        "metacognition": 0.5,
        "evidence": "冷启动默认画像(8-10 题诊断问卷或首次对话后更新)",
    }


def ensure_user(user_id: str, name: str = "同学") -> None:
    init_db()
    with session() as s:
        if not s.get(User, user_id):
            s.add(User(id=user_id, name=name))
            s.commit()


def _bounded_float(value: Any, low: float = 0.0, high: float = 1.0) -> float | None:
    try:
        return min(high, max(low, float(value)))
    except (TypeError, ValueError):
        return None


def _clean_error_tags(value: Any) -> list[str]:
    values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    tags: list[str] = []
    for item in values:
        tag = str(item or "").strip()
        if len(tag) < 2 or tag in tags:
            continue
        tags.append(tag)
    return tags[:8]


def sanitize_profile_patch(patch: dict[str, Any] | None) -> dict[str, Any]:
    """Validate an incremental profile patch before it reaches the JSON column."""
    if not isinstance(patch, dict):
        return {}
    out: dict[str, Any] = {}

    mastery = patch.get("knowledge_mastery")
    if isinstance(mastery, dict):
        clean_mastery: dict[str, float] = {}
        for raw_kp, raw_value in mastery.items():
            kp = canonical_kp_id(str(raw_kp))
            value = _bounded_float(raw_value)
            if kp and value is not None:
                clean_mastery[kp] = round(value, 4)
        if clean_mastery:
            out["knowledge_mastery"] = clean_mastery

    style = str(patch.get("cognitive_style") or "").strip()
    if style in _COGNITIVE_STYLES:
        out["cognitive_style"] = style

    tags = _clean_error_tags(patch.get("error_prone"))
    if tags:
        out["error_prone"] = tags

    goal = str(patch.get("goal") or "").strip()
    if goal in _GOALS:
        out["goal"] = goal

    pace = patch.get("pace")
    if isinstance(pace, dict):
        clean_pace: dict[str, Any] = {}
        try:
            minutes = int(pace.get("daily_minutes"))
            if 1 <= minutes <= 1440:
                clean_pace["daily_minutes"] = minutes
        except (TypeError, ValueError):
            pass
        frequency = str(pace.get("frequency") or "").strip()
        if frequency and frequency != "未知":
            clean_pace["frequency"] = frequency[:20]
        focus = str(pace.get("focus") or "").strip()
        if focus in _FOCUS_LEVELS:
            clean_pace["focus"] = focus
        if clean_pace:
            out["pace"] = clean_pace

    pref = patch.get("resource_pref")
    if isinstance(pref, dict):
        clean_pref: dict[str, float] = {}
        for kind in _RESOURCE_KINDS:
            if kind not in pref:
                continue
            value = _bounded_float(pref[kind])
            if value is not None:
                clean_pref[kind] = round(value, 4)
        if clean_pref:
            out["resource_pref"] = clean_pref

    difficulty = str(patch.get("difficulty_pref") or "").strip()
    if difficulty == "挑战型":
        difficulty = "挑战式"
    if difficulty in _DIFFICULTY_PREFS:
        out["difficulty_pref"] = difficulty

    metacognition = _bounded_float(patch.get("metacognition"))
    if metacognition is not None:
        out["metacognition"] = round(metacognition, 4)

    evidence = str(patch.get("evidence") or "").strip()
    if evidence and evidence != "未知":
        out["evidence"] = evidence[:300]

    return {k: v for k, v in out.items() if k in _PROFILE_FIELDS}


def get_profile(user_id: str) -> dict:
    ensure_user(user_id)
    with session() as s:
        p = s.get(Profile, user_id)
        if p is None:
            p = Profile(user_id=user_id, data=default_profile(), version=1)
            s.add(p)
            s.commit()
        data = dict(p.data)
        data["_version"] = p.version
        data["_updated_at"] = (p.updated_at or dt.datetime.now(dt.timezone.utc)).isoformat()
        return data


def merge_profile(user_id: str, patch: dict[str, Any]) -> dict:
    """浅合并 + 字典维度深合并;version 自增,实现"随学随新"。"""
    ensure_user(user_id)
    patch = sanitize_profile_patch(patch)
    if not patch:
        return get_profile(user_id)
    evidence = patch.pop("evidence", None)
    with session() as s:
        p = s.get(Profile, user_id)
        if p is None:
            p = Profile(user_id=user_id, data=default_profile(), version=0)
            s.add(p)
        data = dict(p.data or default_profile())
        original = dict(data)
        for k, v in patch.items():
            if k.startswith("_"):
                continue
            if k == "error_prone" and isinstance(v, list):
                existing = _clean_error_tags(data.get(k))
                data[k] = list(dict.fromkeys([*existing, *v]))[:8]
            elif isinstance(v, dict) and isinstance(data.get(k), dict):
                merged = dict(data[k])
                merged.update(v)
                data[k] = merged
            elif v not in (None, "", "未知"):
                data[k] = v
        if data == original:
            result = dict(original)
            result["_version"] = p.version
            result["_updated_at"] = (p.updated_at or dt.datetime.now(dt.timezone.utc)).isoformat()
            return result
        if evidence:
            data["evidence"] = evidence
        p.data = data
        p.version = (p.version or 0) + 1
        s.commit()
        return get_profile(user_id)


def update_mastery(user_id: str, kp: str, correct: bool) -> float:
    canonical = canonical_kp_id(kp)
    if canonical is None:
        raise ValueError(f"unknown knowledge point: {kp}")
    prof = get_profile(user_id)
    cur = float(prof["knowledge_mastery"].get(canonical, 0.3))
    new = bkt_update(cur, correct)
    merge_profile(user_id, {"knowledge_mastery": {canonical: new}})
    return new


def log_event(user_id: str, etype: str, payload: dict) -> None:
    ensure_user(user_id)
    with session() as s:
        s.add(EventLog(user_id=user_id, etype=etype, payload=payload))
        s.commit()


def recent_events(user_id: str, limit: int = 30) -> list[dict]:
    with session() as s:
        rows = s.execute(
            select(EventLog).where(EventLog.user_id == user_id)
            .order_by(EventLog.id.desc()).limit(limit)
        ).scalars().all()
        return [{"etype": r.etype, "payload": r.payload,
                 "ts": r.created_at.isoformat() if r.created_at else ""} for r in rows]
