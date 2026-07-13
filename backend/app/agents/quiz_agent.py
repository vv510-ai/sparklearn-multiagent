"""题库智能体(Quiz Agent):按画像难度生成结构化习题组(单选/填空/判断/设计/复杂度分析),
每题挂 kp 与 error_tags(易错点标签),供 Eval Agent 做 BKT 更新与错因画像回写。"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from ..llm.spark_client import llm_complete, parse_json
from ..rag.retriever import retrieve
from ..services.knowledge_graph import kp_name
from .emitter import agent_end, agent_start, emit

_TYPES = {"single", "fill", "judge", "design", "complexity"}
_TARGET_QUESTIONS = 8
_MIN_QUESTIONS = 6
_SEED_QUIZ_PATH = Path(__file__).resolve().parents[1] / "data" / "seed_quiz.json"

_PROMPT = (
    "TASK=quiz\n"
    "请围绕知识点「{kp}」恰好生成 8 道习题,难度档={difficulty}(1易~5难)。"
    "题型至少包含 3 道 single(单选,4 选项)、1 道 fill(填空)、1 道 judge(判断)、"
    "1 道 complexity(复杂度分析)、1 道 design(简答设计),剩余 1 道自选。"
    "single 以及带选项的 complexity 的 answer 必须只填 A/B/C/D,每题解释控制在 80 字以内。"
    "结合参考资料命题,易错点优先。只输出 JSON:\n"
    '{{"questions":[{{"type":"single","stem":"...","options":["A...","B...","C...","D..."],'
    '"answer":"A","explain":"...","kp":"{kpid}","difficulty":3,"error_tags":["边界条件"]}}]}}\n'
    "\n参考资料:\n{ctx}\n"
)

_FALLBACK = {
    "type": "judge", "stem": "任何递归算法都可以改写为迭代实现。", "options": [],
    "answer": "对", "explain": "递归可借助显式栈改写为迭代,这是栈与递归等价性的经典结论。",
    "difficulty": 2, "error_tags": ["概念混淆"],
}


def _difficulty_of(profile: dict, kp: str) -> int:
    m = float((profile.get("knowledge_mastery") or {}).get(kp, 0.3))
    base = 1 + round(m * 4)                                   # 0.3→2,0.8→4
    if profile.get("difficulty_pref") in {"挑战式", "挑战型"}:
        base += 1
    return max(1, min(5, base))


def _seed_questions(kp: str) -> list[dict]:
    try:
        with _SEED_QUIZ_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return []
    items = data.get("questions", []) if isinstance(data, dict) else []
    return [dict(item) for item in items if isinstance(item, dict) and item.get("kp") == kp]


def _choice_answer(options: list[str], answer: object) -> str:
    raw = str(answer or "").strip()
    direct = re.match(r"^([A-D])(?:[.、:：\s]|$)", raw, re.IGNORECASE)
    if direct:
        return direct.group(1).upper()
    expected = re.sub(r"\s+", "", re.sub(r"^[A-D][.、:：\s]*", "", raw, flags=re.IGNORECASE)).lower()
    for index, option in enumerate(options):
        clean = re.sub(r"\s+", "", re.sub(r"^[A-D][.、:：\s]*", "", option, flags=re.IGNORECASE)).lower()
        if clean == expected:
            return chr(65 + index)
    return ""


def _validate(q: dict, kp: str) -> dict | None:
    if not isinstance(q, dict) or q.get("type") not in _TYPES or not q.get("stem"):
        return None
    q["kp"] = kp
    raw_options = q.get("options", [])
    if isinstance(raw_options, str):
        raw_options = [raw_options]
    options = (
        [str(option).strip() for option in raw_options if str(option or "").strip()]
        if isinstance(raw_options, list)
        else []
    )
    if len(options) == 1 and "「, 」" in options[0]:
        options = [part.strip() for part in options[0].split("「, 」") if part.strip()]
    q["options"] = options
    q.setdefault("explain", q.get("explanation", ""))
    raw_tags = q.get("error_tags")
    tags = [raw_tags] if isinstance(raw_tags, str) else raw_tags if isinstance(raw_tags, list) else []
    q["error_tags"] = list(dict.fromkeys(
        str(tag).strip() for tag in tags if len(str(tag or "").strip()) >= 2
    ))[:8]
    q["difficulty"] = int(q.get("difficulty", 3) or 3)
    if q["type"] == "single" and len(q["options"]) < 2:
        return None
    if str(q.get("answer", "")).strip() == "":
        return None
    if q["type"] == "single" or (q["type"] == "complexity" and q["options"]):
        q["answer"] = _choice_answer(q["options"], q["answer"])
        if not q["answer"]:
            return None
    q["id"] = uuid.uuid4().hex[:10]
    return q


async def run(state: dict) -> dict:
    requested = state.get("kinds") or []
    if requested and "quiz" not in requested:
        return {}
    kp = (state.get("knowledge_points") or ["binary_tree"])[0]
    name = kp_name(kp)
    profile = state.get("student_profile") or {}
    source_ids = [str(x) for x in (state.get("source_ids") or []) if str(x).strip()]
    goal = state.get("learning_goal") or ""
    diff = _difficulty_of(profile, kp)
    await agent_start("quiz", "题库智能体", f"「{name}」难度档 {diff},生成 {_TARGET_QUESTIONS} 题并本地校验")

    chunks = retrieve(
        f"{name} 易错点 经典题 {goal}",
        final_k=3,
        source_ids=source_ids,
        kp=kp,
    )
    ctx = "\n---\n".join(c["text"][:280] for c in chunks) or "(无)"
    try:
        raw = await llm_complete(_PROMPT.format(kp=name, kpid=kp, difficulty=diff, ctx=ctx),
                                 role="ultra", temperature=0.6, max_tokens=3000)
        data = parse_json(raw)
        items = data.get("questions", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    except Exception:  # noqa: BLE001
        items = []
    questions = []
    seen_stems: set[str] = set()
    for item in [*items, *_seed_questions(kp)]:
        valid = _validate(dict(item), kp) if isinstance(item, dict) else None
        stem_key = re.sub(r"\s+", "", str((valid or {}).get("stem", ""))).lower()
        if valid and stem_key and stem_key not in seen_stems:
            questions.append(valid)
            seen_stems.add(stem_key)
        if len(questions) >= _TARGET_QUESTIONS:
            break
    if not questions:                                          # 兜底:保证演示链路不空
        fb = dict(_FALLBACK, kp=kp, id=uuid.uuid4().hex[:10])
        questions = [fb]

    rid = uuid.uuid4().hex[:12]
    resource = {"id": rid, "kind": "quiz", "kp": kp,
                "title": f"{name}·智能习题组({len(questions)} 题)",
                "payload": {"questions": questions, "difficulty": diff},
                "citations": [c.get("citation", "") for c in chunks]}
    await emit({"type": "resource", "resource": resource})
    tags = sorted({t for q in questions for t in q.get("error_tags", [])})
    count_note = "达到标准题量" if len(questions) >= _MIN_QUESTIONS else "已安全降级"
    await agent_end("quiz", f"{len(questions)} 题通过校验({count_note}),覆盖易错点:{('、'.join(tags) or '—')}",
                    {"id": rid, "n": len(questions), "target": _TARGET_QUESTIONS})
    return {"generated_resources": {rid: resource}}
