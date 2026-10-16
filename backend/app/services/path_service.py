"""路径服务:基于知识图谱依赖 + BKT⁺ 掌握度 + 难度偏好,规划动态个性化学习路径(DAG)。

算法(Path Agent 调用):
1. 拓扑排序得到合法学习序;
2. 有效掌握度 = BKT⁺ 遗忘衰减后的掌握度(距上次练习越久越低,复习越多衰减越慢);
3. 节点状态:done(有效掌握度≥0.8)/ ready(先修有效掌握度≥0.6)/ locked;
   曾经掌握但已淡化到阈值以下的节点重新变为 ready,并获得复习加权;
4. 排序权重 score = (1-有效掌握度) + 目标相关 + 易错点命中 + 难度偏好项
   + ZPD 加权(预测答对率落在 0.55–0.85“跳一跳够得着”区间时优先,低于 0.35 时让位给先修)
   + 遗忘复习加权;
   ZPD 思想见 Clement et al., JEDM 2015(ZPDES);合意困难见 Bjork 1994;
5. 评估(/api/eval)后掌握度变化 → 触发重排,实现"随评估结果重排"闭环。
"""
from __future__ import annotations

import datetime as dt
import hashlib

from ..models.db import init_db, session
from ..models.entities import PathPlan, PersonalizationDecision, Profile
from .bkt import forget, predicted_correct
from .knowledge_graph import kp_name, load_kg, prerequisites, topological_order
from .learning_scope import current_space, profile_row

DONE_T, READY_T = 0.8, 0.6
ZPD_LOW, ZPD_HIGH, TOO_HARD = 0.55, 0.85, 0.35


def _days_since(value, now: dt.datetime) -> float | None:
    try:
        last = dt.datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    last = last if last.tzinfo else last.replace(tzinfo=dt.timezone.utc)
    return max(0.0, (now - last).total_seconds() / 86400)


def effective_mastery(profile: dict, kp: str, now: dt.datetime | None = None) -> tuple[float, float, float | None]:
    """(recorded, retrievable-now, days since the last evidence) for one knowledge point."""
    recorded = float((profile.get("knowledge_mastery") or {}).get(kp, 0.3))
    info = (profile.get("knowledge_trace") or {}).get(kp) or {}
    days = _days_since(info.get("last"), now or dt.datetime.now(dt.timezone.utc))
    return recorded, forget(recorded, days, int(info.get("independent_correct") or 0)), days


def plan_conversation_path(profile: dict, topics: list[dict]) -> dict:
    """Build a durable learning map from every substantive topic in a notebook.

    This is intentionally conversation-wide: tool labels such as “换种说法”
    are filtered before this function, and custom topics receive stable ids so
    later learning adds nodes instead of replacing the previous one.
    """
    mastery: dict[str, float] = profile.get("knowledge_mastery", {})
    nodes: list[dict] = []
    topic_ids: list[str] = []
    for index, topic in enumerate(topics, 1):
        custom = bool(topic.get("custom"))
        name = str(topic.get("name") or "当前主题").strip()[:80]
        raw_id = str(topic.get("id") or "")
        node_id = (
            f"custom_{hashlib.sha1(name.casefold().encode('utf-8')).hexdigest()[:12]}"
            if custom else raw_id
        )
        if not node_id or node_id in topic_ids:
            continue
        question_count = max(1, len(topic.get("questions") or []))
        value = (
            min(0.65, 0.3 + 0.08 * question_count)
            if custom else float(mastery.get(node_id, 0.3))
        )
        status = "done" if value >= DONE_T else "ready"
        topic_ids.append(node_id)
        nodes.append({
            "id": node_id,
            "name": name,
            "mastery": round(value, 3),
            "status": status,
            "difficulty": 1 if custom else int(load_kg()["nodes"].get(node_id, {}).get("difficulty", 3)),
            "chapter": "本书对话主题",
            "desc": "从本书对话历史中提取的持续学习主题",
            "score": round(1 - value, 3),
            "order": index,
            "reason": f"本书对话中已围绕该主题学习 {question_count} 次",
        })

    # Chronological edges make the learner's actual progression visible and
    # ensure the map has no isolated collage nodes.
    edges = [
        {"from": topic_ids[index - 1], "to": topic_ids[index]}
        for index in range(1, len(topic_ids))
    ]
    ready = [node for node in nodes if node["status"] != "done"]
    next_node = min(ready, key=lambda node: (node["mastery"], -int(node["order"]))) if ready else None
    return {
        "course": "本书学习脉络",
        "course_id": "conversation_history",
        "graph_version": 1,
        "nodes": nodes,
        "edges": edges,
        "next_kp": next_node["id"] if next_node else None,
        "generated_by": "conversation_history",
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def plan_path(profile: dict, goal_kps: list[str] | None = None,
              generated_by: str = "rule", now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    pref = profile.get("difficulty_pref", "循序渐进")
    errors = set(profile.get("error_prone", []))
    goal_kps = set(goal_kps or profile.get("focus_kps", []) or [])
    kg = load_kg()

    order = topological_order()
    nodes = []
    for kp in order:
        recorded, m, days = effective_mastery(profile, kp, now)
        faded = recorded >= DONE_T > m
        pres = prerequisites(kp)
        if m >= DONE_T:
            status = "done"
        elif all(effective_mastery(profile, p, now)[1] >= READY_T for p in pres):
            status = "ready"
        else:
            status = "locked"
        diff = kg["nodes"][kp].get("difficulty", 3)
        diff_term = (-0.06 * diff) if pref == "循序渐进" else (0.04 * diff)
        chance = predicted_correct(m)
        zpd = 0.25 if ZPD_LOW <= chance <= ZPD_HIGH else (-0.15 if chance < TOO_HARD else 0.0)
        score = (1 - m) * 1.0 \
            + (0.5 if kp in goal_kps else 0.0) \
            + (0.3 if any(kp in e or kp_name(kp) in e for e in errors) else 0.0) \
            + diff_term + (zpd if status == "ready" else 0.0) + (0.35 if faded else 0.0)
        reason = _reason(kp, m, status, kp in goal_kps, pref)
        if faded and days is not None:
            reason += f",约 {days:.0f} 天没练,记忆已淡化,建议先复习"
        elif status == "ready" and zpd > 0:
            reason += ",预测答对率处在“跳一跳够得着”的区间"
        nodes.append({
            "id": kp, "name": kp_name(kp), "mastery": round(m, 3), "status": status,
            "recorded_mastery": round(recorded, 3), "predicted_correct": chance,
            "days_since_practice": None if days is None else round(days, 1),
            "difficulty": diff, "score": round(score, 3),
            "chapter": str(kg["nodes"][kp].get("chapter") or "课程知识点"),
            "desc": str(kg["nodes"][kp].get("desc") or ""),
            "subtopics": list(kg["nodes"][kp].get("subtopics") or []),
            "reason": reason,
        })

    ready_sorted = sorted([n for n in nodes if n["status"] == "ready"],
                          key=lambda n: -n["score"])
    for i, n in enumerate(ready_sorted, start=1):
        n["order"] = i
    next_kp = ready_sorted[0]["id"] if ready_sorted else None

    return {
        "course": kg["course"],
        "course_id": kg["course_id"],
        "graph_version": kg["version"],
        "nodes": nodes,
        "edges": kg["edges"],
        "detail_edges": kg["detail_edges"],
        "next_kp": next_kp,
        "generated_by": generated_by,
        "algorithm": "bkt_plus_forgetting_zpd_v1",
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def is_current_course_path(path: dict | None) -> bool:
    """Reject persisted course snapshots built from an older or mixed graph."""
    if not isinstance(path, dict) or path.get("generated_by") == "conversation_history":
        return False
    kg = load_kg()
    node_ids = {
        str(node.get("id") or "")
        for node in path.get("nodes", [])
        if isinstance(node, dict)
    }
    return (
        path.get("course_id") == kg["course_id"]
        and int(path.get("graph_version") or 0) == kg["version"]
        and node_ids == set(kg["nodes"])
    )


def _reason(kp: str, m: float, status: str, is_goal: bool, pref: str) -> str:
    if status == "done":
        return f"掌握度 {m:.0%},已达标"
    if status == "locked":
        return "先修未达 60%,暂缓"
    bits = [f"掌握度 {m:.0%}"]
    if is_goal:
        bits.append("命中学习目标")
    bits.append("循序渐进优先低难" if pref == "循序渐进" else "挑战式优先高难")
    return ",".join(bits)


def save_path(user_id: str, path: dict) -> None:
    if current_space():
        with session() as db:
            row = profile_row(db, user_id)
            row.path = path
            db.commit()
        return
    init_db()
    with session() as s:
        row = s.get(PathPlan, user_id)
        if row is None:
            s.add(PathPlan(user_id=user_id, data=path))
        else:
            row.data = path
        profile = s.get(Profile, user_id)
        nodes = list(path.get("nodes") or [])
        next_node = next(
            (node for node in nodes if node.get("id") == path.get("next_kp")),
            {},
        )
        profile_data = dict(profile.data) if profile and isinstance(profile.data, dict) else {}
        s.add(PersonalizationDecision(
            user_id=user_id,
            kind="learning_path",
            profile_version=int(profile.version if profile else 0),
            inputs={
                "knowledge_mastery": profile_data.get("knowledge_mastery", {}),
                "difficulty_pref": profile_data.get("difficulty_pref", ""),
                "error_prone": profile_data.get("error_prone", []),
            },
            output={
                "next_kp": path.get("next_kp"),
                "generated_by": path.get("generated_by", "rule"),
                "top_ready": [
                    {"id": node.get("id"), "score": node.get("score")}
                    for node in sorted(
                        (node for node in nodes if node.get("status") == "ready"),
                        key=lambda item: int(item.get("order") or 9999),
                    )[:5]
                ],
            },
            reason=str(next_node.get("reason") or "no ready knowledge point"),
        ))
        s.commit()


def get_path(user_id: str) -> dict | None:
    init_db()
    with session() as s:
        if current_space():
            row = profile_row(s, user_id)
            return dict(row.path or {})
        row = s.get(PathPlan, user_id)
        return dict(row.data) if row else None


def list_decisions(user_id: str, limit: int = 20) -> list[dict]:
    init_db()
    with session() as s:
        rows = (
            s.query(PersonalizationDecision)
            .filter(PersonalizationDecision.user_id == user_id)
            .order_by(PersonalizationDecision.created_at.desc())
            .limit(max(1, min(limit, 100)))
            .all()
        )
        return [{
            "id": row.id,
            "kind": row.kind,
            "profile_version": row.profile_version,
            "inputs": row.inputs,
            "output": row.output,
            "reason": row.reason,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        } for row in rows]
