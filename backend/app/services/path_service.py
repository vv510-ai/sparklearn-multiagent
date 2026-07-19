"""路径服务:基于知识图谱依赖 + BKT 掌握度 + 难度偏好,规划动态个性化学习路径(DAG)。

算法(Path Agent 调用):
1. 拓扑排序得到合法学习序;
2. 节点状态:done(掌握度≥0.8)/ ready(先修达标 0.6)/ locked;
3. 排序权重 score = w1·(1-mastery) + w2·目标相关 + w3·易错点命中 − w4·难度惩罚,
   难度惩罚方向由 difficulty_pref 决定(循序渐进惩罚高难;挑战式奖励高难);
4. 评估(/api/eval)后掌握度变化 → 触发重排,实现"随评估结果重排"闭环。
"""
from __future__ import annotations

import datetime as dt
import hashlib

from ..models.db import init_db, session
from ..models.entities import PathPlan, PersonalizationDecision, Profile
from .knowledge_graph import kp_name, load_kg, prerequisites, topological_order

DONE_T, READY_T = 0.8, 0.6


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
              generated_by: str = "rule") -> dict:
    mastery: dict[str, float] = profile.get("knowledge_mastery", {})
    pref = profile.get("difficulty_pref", "循序渐进")
    errors = set(profile.get("error_prone", []))
    goal_kps = set(goal_kps or [])
    kg = load_kg()

    order = topological_order()
    nodes = []
    for kp in order:
        m = float(mastery.get(kp, 0.3))
        pres = prerequisites(kp)
        if m >= DONE_T:
            status = "done"
        elif all(mastery.get(p, 0.0) >= READY_T for p in pres):
            status = "ready"
        else:
            status = "locked"
        diff = kg["nodes"][kp].get("difficulty", 3)
        diff_term = (-0.06 * diff) if pref == "循序渐进" else (0.04 * diff)
        score = (1 - m) * 1.0 \
            + (0.5 if kp in goal_kps else 0.0) \
            + (0.3 if any(kp in e or kp_name(kp) in e for e in errors) else 0.0) \
            + diff_term
        nodes.append({
            "id": kp, "name": kp_name(kp), "mastery": round(m, 3), "status": status,
            "difficulty": diff, "score": round(score, 3),
            "chapter": str(kg["nodes"][kp].get("chapter") or "课程知识点"),
            "desc": str(kg["nodes"][kp].get("desc") or ""),
            "reason": _reason(kp, m, status, kp in goal_kps, pref),
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
        "next_kp": next_kp,
        "generated_by": generated_by,
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
