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

from ..auth import enforce_user_scope
from ..models.db import init_db, session
from ..models.entities import EventLog, Profile, User
from ..services.bkt import bkt_update
from ..services.knowledge_graph import all_kp_ids, canonical_kp_id
from .learning_scope import current_space, profile_row, event_in_scope, notebook_id

_PROFILE_FIELDS = {
    "knowledge_mastery", "cognitive_style", "error_prone", "goal", "pace",
    "difficulty_pref", "resource_pref", "metacognition", "evidence",
    "focus_kps", "learning_topic", "current_level", "materials_status",
    "onboarding_completed",
}
_COGNITIVE_STYLES = {"视觉型", "语言型", "动手型"}
_GOALS = {"应试", "竞赛", "工程实践", "兴趣"}
_DIFFICULTY_PREFS = {"循序渐进", "挑战式"}
_RESOURCE_KINDS = {"doc", "video", "quiz", "mindmap", "code"}
_FOCUS_LEVELS = {"高", "中", "低"}
_CURRENT_LEVELS = {"刚开始接触", "学过一些概念", "能做基础题", "能独立解决综合题", "不确定"}
_MATERIAL_STATUSES = {"已有资料", "暂时没有", "稍后上传"}
_ONBOARDING_TOPICS = {
    "从基础开始": ["complexity", "array", "linked_list", "stack", "queue"],
    "排序与查找": ["sorting_basic", "sorting_adv", "hash"],
    "树与图": ["binary_tree", "bst", "graph_basic", "graph_traverse"],
    "动态规划": ["recursion", "dp"],
    "还没想好": [],
}
_STYLE_TO_PROFILE = {
    "图示和例子": ("视觉型", {"video": 0.34, "mindmap": 0.30, "doc": 0.18, "quiz": 0.10, "code": 0.08}),
    "讲解和文字": ("语言型", {"doc": 0.38, "video": 0.20, "mindmap": 0.18, "quiz": 0.14, "code": 0.10}),
    "边写代码边学": ("动手型", {"code": 0.34, "doc": 0.20, "quiz": 0.22, "video": 0.14, "mindmap": 0.10}),
    "先做题再讲解": ("动手型", {"quiz": 0.40, "doc": 0.18, "code": 0.18, "video": 0.14, "mindmap": 0.10}),
}


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
        "focus_kps": [],
        "learning_topic": "",
        "current_level": "",
        "materials_status": "",
        "onboarding_completed": False,
        "evidence": "尚未测评；掌握度数值是系统初始先验，不是测得的成绩。请完成起点测评并通过后续独立作答更新。",
    }


def ensure_user(user_id: str, name: str = "同学") -> None:
    enforce_user_scope(user_id)
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
        try:
            weekly_minutes = int(pace.get("weekly_minutes"))
            if 1 <= weekly_minutes <= 10080:
                clean_pace["weekly_minutes"] = weekly_minutes
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

    focus_kps = patch.get("focus_kps")
    if isinstance(focus_kps, list):
        clean_focus = []
        for raw_kp in focus_kps:
            kp = canonical_kp_id(str(raw_kp))
            if kp and kp not in clean_focus:
                clean_focus.append(kp)
        out["focus_kps"] = clean_focus[:8]

    learning_topic = str(patch.get("learning_topic") or "").strip()
    if learning_topic:
        out["learning_topic"] = learning_topic[:80]

    current_level = str(patch.get("current_level") or "").strip()
    if current_level in _CURRENT_LEVELS:
        out["current_level"] = current_level

    materials_status = str(patch.get("materials_status") or "").strip()
    if materials_status in _MATERIAL_STATUSES:
        out["materials_status"] = materials_status

    if isinstance(patch.get("onboarding_completed"), bool):
        out["onboarding_completed"] = patch["onboarding_completed"]

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
        p = profile_row(s, user_id)
        if p is None:
            p = Profile(user_id=user_id, data=default_profile(), version=1)
            s.add(p)
            s.commit()
        data = dict(p.data)
        # Course graphs can evolve. Remove mastery keys left by an older or
        # accidentally mixed taxonomy before they leak into radar/path views.
        raw_mastery = data.get("knowledge_mastery")
        if not isinstance(raw_mastery, dict):
            raw_mastery = {}
        normalized_mastery: dict[str, float] = {}
        for kp in all_kp_ids():
            value = _bounded_float(raw_mastery.get(kp, 0.3))
            normalized_mastery[kp] = round(0.3 if value is None else value, 4)
        profile_changed = raw_mastery != normalized_mastery
        if "onboarding_completed" not in data:
            data["onboarding_completed"] = False
            profile_changed = True
        if profile_changed:
            data["knowledge_mastery"] = normalized_mastery
            p.data = data
            p.version = (p.version or 0) + 1
            s.commit()
        data["_version"] = p.version
        data["_updated_at"] = (p.updated_at or dt.datetime.now(dt.timezone.utc)).isoformat()
        if current_space():
            data["notebook_id"] = notebook_id()
            data["course_title"] = current_space()["course"]["title"]
            data["knowledge_labels"] = {k: v["name"] for k, v in current_space()["graph"]["nodes"].items()}
            current_space()["profile"] = dict(data)
        return data


def merge_profile(user_id: str, patch: dict[str, Any]) -> dict:
    """浅合并 + 字典维度深合并;version 自增,实现"随学随新"。"""
    ensure_user(user_id)
    patch = sanitize_profile_patch(patch)
    if not patch:
        return get_profile(user_id)
    evidence = patch.pop("evidence", None)
    with session() as s:
        p = profile_row(s, user_id)
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
            elif isinstance(v, bool):
                data[k] = v
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


def onboarding_patch(answers: dict[str, Any] | None) -> dict[str, Any]:
    """Turn the short first-use questionnaire into a durable profile patch.

    Self-report sets goals, presentation preferences and available time only.
    It must never overwrite evidence from independent course questions.
    """
    raw = answers if isinstance(answers, dict) else {}
    topic = str(raw.get("topic") or "还没想好").strip()
    if topic not in _ONBOARDING_TOPICS:
        topic = "还没想好"
    level = str(raw.get("current_level") or "不确定").strip()
    if level not in _CURRENT_LEVELS:
        level = "不确定"
    focus_kps = list(_ONBOARDING_TOPICS[topic])

    goal = str(raw.get("goal") or "").strip()
    if goal not in _GOALS:
        goal = ""
    style_label = str(raw.get("style") or "").strip()
    _, resource_pref = _STYLE_TO_PROFILE.get(
        style_label,
        ("未知", {"doc": 0.2, "video": 0.2, "quiz": 0.2, "mindmap": 0.2, "code": 0.2}),
    )
    try:
        weekly_minutes = int(raw.get("weekly_minutes"))
    except (TypeError, ValueError):
        try:
            weekly_minutes = int(raw.get("daily_minutes")) * 7
        except (TypeError, ValueError):
            weekly_minutes = 140
    weekly_minutes = min(1260, max(30, weekly_minutes))
    daily_minutes = min(180, max(5, round(weekly_minutes / 7)))
    frequency = str(raw.get("frequency") or "每天").strip()[:20] or "每天"
    materials_status = str(raw.get("materials_status") or "").strip()
    if materials_status not in _MATERIAL_STATUSES:
        materials_status = ""
    difficulty = "挑战式" if level == "能独立解决综合题" else "循序渐进"
    patch: dict[str, Any] = {
        "focus_kps": focus_kps,
        "learning_topic": topic,
        "current_level": level,
        "difficulty_pref": difficulty,
        "resource_pref": resource_pref,
        "pace": {
            "weekly_minutes": weekly_minutes,
            "daily_minutes": daily_minutes,
            "frequency": frequency,
        },
        "onboarding_completed": True,
        "evidence": "学习引导自述仅用于目标、时间与资料偏好；知识水平以独立作答为依据。",
    }
    if goal:
        patch["goal"] = goal
    if materials_status:
        patch["materials_status"] = materials_status
    return patch


def complete_onboarding(user_id: str, answers: dict[str, Any] | None) -> dict:
    return merge_profile(user_id, onboarding_patch(answers))


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
        s.add(EventLog(user_id=user_id, etype=etype, payload={**payload, "notebook_id": notebook_id(),
            "course_revision": (current_space() or {}).get("course", {}).get("revision")}))
        s.commit()


def recent_events(user_id: str, limit: int = 30) -> list[dict]:
    with session() as s:
        rows = s.execute(
            select(EventLog).where(EventLog.user_id == user_id)
            .order_by(EventLog.id.desc()).limit(max(limit, 500))
        ).scalars().all()
        rows = [r for r in rows if event_in_scope(r.payload)][:limit]
        return [{"etype": r.etype, "payload": r.payload,
                 "ts": r.created_at.isoformat() if r.created_at else ""} for r in rows]
