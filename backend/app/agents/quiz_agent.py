"""题库智能体(Quiz Agent):按画像难度生成结构化习题组(单选/填空/判断/设计/复杂度分析),
每题挂 kp 与 error_tags(易错点标签),供 Eval Agent 做 BKT 更新与错因画像回写。"""
from __future__ import annotations

import json
import re
import uuid
from difflib import SequenceMatcher
from pathlib import Path

from ..config import is_demo
from ..llm.spark_client import llm_complete, parse_json
from ..prompt_templates import render_quiz_prompt_call
from ..rag.retriever import retrieve
from ..services.knowledge_graph import infer_kp_id, resolve_topic
from .emitter import agent_end, agent_start, emit

_TYPES = {"single", "fill", "judge", "design", "complexity"}
_TARGET_QUESTIONS = 8
_MIN_QUESTIONS = 6
_SEED_QUIZ_PATH = Path(__file__).resolve().parents[1] / "data" / "seed_quiz.json"


def _stem_key(value: object) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", str(value or "").lower())


def _reuses_stem(stem: object, forbidden_stems: list[str]) -> bool:
    """Reject copied or cosmetically rewritten stems in transfer retests."""
    candidate = _stem_key(stem)
    if not candidate:
        return True
    for forbidden in forbidden_stems:
        original = _stem_key(forbidden)
        if not original:
            continue
        if candidate == original or (len(original) >= 12 and (candidate in original or original in candidate)):
            return True
        if min(len(candidate), len(original)) >= 12 and SequenceMatcher(
            None, candidate, original, autojunk=False,
        ).ratio() >= 0.82:
            return True
    return False

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


def _clean_source_claim(value: object, limit: int = 220) -> str:
    text = str(value or "")
    text = re.sub(r"[\x00-\x1f\ufffd\ue000-\uf8ff]", " ", text)
    text = re.split(r"(?:答案|参考答案|解析)\s*[:：]", text, maxsplit=1)[0]
    text = re.sub(r"(?:^|\s)[A-D][.、:：]\s*", " ", text, flags=re.IGNORECASE)
    text = " ".join(text.split()).strip(" -•")
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] or text[:limit]
    return text.strip()


def _validate(q: dict, kp: str) -> dict | None:
    if not isinstance(q, dict) or q.get("type") not in _TYPES or not q.get("stem"):
        return None
    stem = " ".join(str(q.get("stem") or "").split())
    if (
        len(stem) > 320
        or re.search(r"(?:参考?答案|正确答案|解析)\s*[:：]", stem)
        or len(re.findall(r"(?:^|\s)\(?\d{1,2}\)?[.、)]", stem)) >= 3
    ):
        return None
    q["stem"] = re.sub(r"^(?:Q\d+|第\s*\d+\s*题)\s*[.、:：-]*\s*", "", stem, flags=re.IGNORECASE)
    source_grounded = bool(q.pop("_source_grounded", False) or q.pop("_trusted_topic", False))
    detected_kp = infer_kp_id(f"{q.get('stem', '')} {q.get('explain', q.get('explanation', ''))}")
    if not source_grounded and detected_kp and detected_kp != kp:
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


def _source_fallback_questions(
    chunks: list[dict],
    kp: str,
    difficulty: int,
    *,
    topic_name: str = "当前主题",
    target_questions: int = _TARGET_QUESTIONS,
) -> list[dict]:
    """Create traceable questions without exposing raw excerpts or their answers."""
    candidates: list[tuple[str, str]] = []
    for chunk in chunks:
        text = _clean_source_claim(chunk.get("text") or "", 360)
        citation = str(chunk.get("citation") or chunk.get("source") or "所选资料")
        if text:
            candidates.append((text, citation))
            candidates.extend(
                (_clean_source_claim(part, 220), citation)
                for part in re.split(r"[。！？；\n]", text)
                if len(part.strip()) >= 18
            )
    prompts = [
        f"用自己的话概括「{topic_name}」在这段资料中的核心结论，并说明一个成立条件。",
        f"资料怎样解释「{topic_name}」的关键步骤？请按先后顺序写出要点。",
        f"为「{topic_name}」设计一个最小例子，并指出每一步对应的概念。",
        f"资料中有哪些容易混淆的概念或做法？请写出区分依据。",
        f"说明「{topic_name}」的适用边界：什么情况下能用，什么情况下需要换方法？",
        f"如果要检查自己是否掌握「{topic_name}」，可以观察哪两个学习证据？",
        f"把资料里的这一要点讲给零基础同学：先给结论，再给一句原因。",
        f"结合资料说明「{topic_name}」的一个常见错误，并给出修正办法。",
    ]
    unique_candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for excerpt, citation in candidates:
        key = re.sub(r"\s+", "", excerpt).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique_candidates.append((excerpt, citation))

    output: list[dict] = []
    for index in range(min(target_questions, len(prompts))):
        if not unique_candidates:
            break
        excerpt, citation = unique_candidates[index % len(unique_candidates)]
        output.append({
            "_source_grounded": True,
            "type": "design",
            "stem": prompts[index],
            "options": [],
            "answer": excerpt,
            "explain": f"核对依据：{citation}。参考要点会在提交后显示。",
            "kp": kp,
            "difficulty": difficulty,
            "error_tags": ["遗漏条件"],
        })
    return output


def _custom_topic_fallback_questions(name: str, kp: str, difficulty: int) -> list[dict]:
    """Keep degraded/offline quizzes on topic without inventing domain facts."""
    base = [
        ("single", f"开始学习“{name}”时，最合理的第一步是什么？",
         ["A 明确它的定义与使用场景", "B 改学其他旧主题", "C 忽略主题直接背答案", "D 只记术语不看例子"],
         "A", "先建立主题边界，避免把其他课程内容混进来。"),
        ("fill", f"请用一句自己的话说明“{name}”主要研究或解决什么问题。", [],
         "围绕主题给出清楚、具体且不偷换概念的说明。", "答案应紧扣当前主题。"),
        ("design", f"列出学习“{name}”时你最想掌握的三个问题。", [],
         "定义、典型场景、实际应用（可按个人目标调整）。", "问题清单能帮助后续讲解保持同一主题。"),
        ("judge", f"学习“{name}”时，可以用完全无关的旧课程内容替代当前主题。", [],
         "错误", "资源必须围绕当前主题，不能回退到其他旧内容。"),
        ("design", f"为“{name}”设计一个最小学习案例，并写出你要观察的关键点。", [],
         "案例应足够小，并明确对象、步骤、结果与边界。", "最小案例用于检查是否真正理解。"),
        ("design", f"写出“{name}”中两个容易混淆的概念或步骤，并说明准备怎样区分。", [],
         "按当前学习内容作答，至少写出区别和适用场景。", "对照能暴露概念边界。"),
        ("design", f"如果要把“{name}”讲给零基础同学，你会按什么顺序讲？", [],
         "一句话结论、生活场景、最小例子、正式概念、常见误区。", "由浅入深比堆叠术语更容易理解。"),
        ("design", f"完成本轮后，你会用哪三个证据判断自己掌握了“{name}”？", [],
         "能复述定义、能独立完成例子、能识别常见边界。", "掌握应由可观察的学习证据判断。"),
    ]
    return [
        {"_trusted_topic": True, "type": qtype, "stem": stem, "options": options, "answer": answer,
         "explain": explain, "kp": kp, "difficulty": difficulty,
         "error_tags": ["主题边界"]}
        for qtype, stem, options, answer, explain in base
    ]


async def run(state: dict) -> dict:
    requested = state.get("kinds") or []
    if requested and "quiz" not in requested:
        return {}
    goal = state.get("learning_goal") or ""
    kp, name, custom_topic = resolve_topic(
        state.get("knowledge_points"), goal, state.get("topic_label")
    )
    profile = state.get("student_profile") or {}
    source_ids = [str(x) for x in (state.get("source_ids") or []) if str(x).strip()]
    guided = bool(state.get("guided_learning"))
    remediation = bool(state.get("transfer_retest"))
    requested_target = int(state.get("target_questions") or 3)
    target_questions = max(1, min(5, requested_target)) if remediation else 5 if guided else _TARGET_QUESTIONS
    min_questions = target_questions if remediation else 4 if guided else _MIN_QUESTIONS
    diff = min(3, _difficulty_of(profile, kp)) if remediation else (
        min(2, _difficulty_of(profile, kp)) if guided else _difficulty_of(profile, kp)
    )
    forbidden_stems = [
        str(stem).strip() for stem in (state.get("avoid_stems") or []) if str(stem).strip()
    ]
    required_terms = [
        str(term).strip() for term in (state.get("required_retrieval_terms") or []) if str(term).strip()
    ]
    await agent_start("quiz", "题库智能体", f"「{name}」难度档 {diff},生成 {target_questions} 题并本地校验")

    chunks = [] if custom_topic and not source_ids else retrieve(
        f"{name} 易错点 经典题 {goal}",
        final_k=6,
        source_ids=source_ids,
        kp=None if source_ids else kp,
        required_terms=required_terms or None,
        user_id=state.get("user_id", "demo_user"),
    )
    if source_ids and not chunks:
        await agent_end("quiz", "所选资料无可用片段,已阻止无依据出题")
        return {
            "generated_resources": {},
            "safety_flags": [{"agent": "quiz", "type": "source_scope_empty",
                              "detail": "所选资料没有可检索内容"}],
        }
    ctx = "\n---\n".join(c["text"][:280] for c in chunks) or "(无)"
    prompt_call = render_quiz_prompt_call(
        kp=name,
        kpid=kp,
        difficulty=diff,
        context=ctx,
        guided=guided,
        general_knowledge=custom_topic and not source_ids,
        remediation=remediation,
        target_questions=target_questions,
        misconception=str(state.get("misconception") or ""),
        forbidden_stems="\n".join(f"- {stem}" for stem in forbidden_stems),
    )
    if is_demo():
        items = []
    else:
        try:
            raw = await llm_complete(
                prompt_call.prompt,
                system=prompt_call.system,
                role="reasoner",
                temperature=0.4 if custom_topic else 0.6,
                max_tokens=1800 if custom_topic else 3000,
                json_mode=True,
                allow_mock_fallback=not custom_topic,
            )
            data = parse_json(raw)
            items = data.get("questions", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        except Exception:  # noqa: BLE001
            items = []
    questions = []
    seen_stems: set[str] = set()
    source_fallback = _source_fallback_questions(
        chunks, kp, diff, topic_name=name, target_questions=target_questions
    )
    fallback_items = (
        source_fallback if source_ids else
        _custom_topic_fallback_questions(name, kp, diff) if custom_topic else
        [*_seed_questions(kp), *source_fallback]
    )
    for item in [*items, *fallback_items]:
        valid = _validate(dict(item), kp) if isinstance(item, dict) else None
        if valid and remediation and _reuses_stem(valid.get("stem"), forbidden_stems):
            continue
        stem_key = re.sub(r"\s+", "", str((valid or {}).get("stem", ""))).lower()
        if valid and stem_key and stem_key not in seen_stems:
            questions.append(valid)
            seen_stems.add(stem_key)
        if len(questions) >= target_questions:
            break
    if not questions:
        raise ValueError(f"{name}没有可用的同主题题目，已阻止生成无关测验")

    rid = uuid.uuid4().hex[:12]
    resource = {"id": rid, "kind": "quiz", "kp": kp,
                "title": f"{name}·智能习题组({len(questions)} 题)",
                "payload": {"questions": questions, "difficulty": diff,
                            "source_ids": source_ids,
                            "learning_goal": goal,
                            "topic_label": name,
                            "custom_topic": custom_topic,
                            "transfer_retest": remediation,
                            "prompt_skill": prompt_call.metadata()},
                "citations": [c.get("citation", "") for c in chunks]}
    await emit({"type": "resource", "resource": resource})
    tags = sorted({t for q in questions for t in q.get("error_tags", [])})
    count_note = "达到标准题量" if len(questions) >= min_questions else "已安全降级"
    await agent_end("quiz", f"{len(questions)} 题通过校验({count_note}),覆盖易错点:{('、'.join(tags) or '—')}",
                    {"id": rid, "n": len(questions), "target": target_questions})
    return {"generated_resources": {rid: resource}}
