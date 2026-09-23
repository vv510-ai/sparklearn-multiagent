"""Prepare material-grounded learning scopes, separate from video recommendations."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import re
import time

from fastapi import HTTPException

from ..data.course_packs import PACKS, build_pack
from ..llm.spark_client import llm_complete, parse_json
from ..llm.failures import failure_code, MESSAGES
from ..models.db import session
from ..models.entities import LearningSpace, AssessmentSession
from ..prompt_templates import invoke_learning_prompt
from ..rag.ingest import chunks_for_source, validate_source_scope, COURSE_SCOPE_ID
from .learning_scope import ensure_space

log = logging.getLogger("sparklearn.course_learning")


def catalogue() -> list[dict]:
    return [{"id": "ds_algo", "title": "数据结构与算法", "description": "16 个知识点，可分次全面摸底"},
        *[{"id": k, "title": v["title"], "description": v.get("description", "4 个入门知识点，12 道自编起点题")} for k, v in PACKS.items()],
        {"id": "custom", "title": "其他课程或主题", "description": "输入主题，或围绕你的资料检查学习起点"}]


def public_course(course: dict) -> dict:
    return {k: copy.deepcopy(course.get(k)) for k in ("title", "kind", "revision", "source_ids", "sources", "boundary", "coverage_note", "textbook", "exam_reference", "quality_review")} | {
        "outline": [{"id": n["id"], "name": n["name"], "objective": n.get("desc", "")}
                    for n in course.get("graph", {}).get("nodes", [])],
        "question_count": len(course.get("bank", [])),
        "practice_available": bool(course.get("practice_bank")),
    }


def material_snapshot(user_id: str, notebook_id: str, source_ids: list[str]) -> tuple[list[dict], list[dict]]:
    try:
        valid = validate_source_scope(user_id, source_ids, notebook_id)
    except ValueError as exc:
        raise HTTPException(400, "所选资料尚未解析完成或不属于这门课程，请重新选择") from exc
    if COURSE_SCOPE_ID in valid:
        raise HTTPException(422, "起点资料请选择实际上传文件；内置课程请在课程选项中选择")
    sources, sample = [], []
    for source_id in valid:
        chunks = chunks_for_source(source_id, user_id)
        if not chunks:
            raise HTTPException(409, "资料没有可用正文，请等待解析完成或更换文件")
        digest = hashlib.sha256("\n".join(c["text"] for c in chunks).encode()).hexdigest()
        # Evenly sample the document, and report the exact sampling boundary.
        count = min(6, len(chunks))
        indices = sorted({round(i * (len(chunks) - 1) / max(1, count - 1)) for i in range(count)})
        sampled = [{**chunks[i], "evidence_id": f"s{len(sources)+1}c{i+1}", "text": chunks[i]["text"][:1600]} for i in indices]
        sample.extend(sampled)
        sources.append({"id": source_id, "title": chunks[0]["source"], "sha256": digest,
                        "total_chunks": len(chunks), "sampled_chunks": len(sampled),
                        "locations": [c.get("page") for c in sampled],
                        "location_kind": "页" if str(chunks[0].get("source_type", "")).endswith("pdf") else "片段"})
    return sources, sample


class DraftValidationError(ValueError):
    """Only application-authored messages may reach the learner."""
    def __init__(self, code: str, message: str, *, repair_issue: str = ""):
        self.code = code
        self.repair_issue = repair_issue or message
        super().__init__(message)


def validate_draft(raw: dict, title: str, chunks: list[dict]) -> dict:
    topics = raw.get("topics") if isinstance(raw, dict) else None
    if not isinstance(topics, list) or not 1 <= len(topics) <= 3:
        raise DraftValidationError("topic_count", "需要 1–3 个有依据且互不重复的起点知识点")
    by_id = {c["evidence_id"]: c for c in chunks}
    nodes, bank, lessons, evidence, stems = [], [], {}, {}, set()
    names: set[str] = set()
    for index, topic in enumerate(topics):
        if not isinstance(topic, dict):
            raise DraftValidationError("topic_format", "知识点格式无效")
        kp = f"topic_{index+1}"
        name, objective = str(topic.get("name") or "").strip(), str(topic.get("objective") or "").strip()
        if not name or len(name) > 80 or not objective or not str(topic.get("lesson") or "").strip():
            raise DraftValidationError("topic_fields", "知识点名称、目标和讲义不能为空")
        if name in names:
            raise DraftValidationError("duplicate_topic", "知识点名称重复，请合并而不是凑数量")
        names.add(name)
        cited = topic.get("chunk_ids") or []
        if not isinstance(cited, list) or any(not isinstance(k, str) for k in cited):
            raise DraftValidationError("citation_format", "资料片段编号应为字符串数组")
        # Provenance is bound by validated IDs to our stored originals. Asking
        # the model to recopy a quote creates a second, unreliable source of truth.
        if (chunks and not cited) or any(k not in by_id for k in cited):
            raise DraftValidationError("citation_mismatch", "引用片段编号未能与当前资料对应")
        evidence[kp] = [{"source": by_id[k]["source"], "source_id": by_id[k]["source_id"],
            "page": by_id[k].get("page"), "text": by_id[k]["text"],
            "location_kind": "页" if str(by_id[k].get("source_type", "")).endswith("pdf") else "片段"} for k in cited if k in by_id]
        questions = topic.get("questions") or []
        if not isinstance(questions, list) or len(questions) != 3 or any(not isinstance(q, dict) for q in questions):
            raise DraftValidationError("question_count", "每个知识点需要三道不同题")
        if not any(q.get("type") == "multiple" for q in questions):
            raise DraftValidationError("missing_multiple", "每个知识点需要至少一道多选辨析题")
        for qi, q in enumerate(questions):
            options, answer = q.get("options"), q.get("answer")
            stem = str(q.get("stem") or "").strip()
            if not stem or stem in stems or len(stem) > 1500 or not isinstance(options, list) or not 2 <= len(options) <= 5:
                raise DraftValidationError("stem_or_options", "题目重复或选项格式不完整")
            if any(not isinstance(o, str) or not o.strip() for o in options) or len(set(options)) != len(options):
                raise DraftValidationError("duplicate_options", "题目选项必须互不重复且非空")
            keys = answer if isinstance(answer, list) else [answer]
            if not keys or len(set(keys)) != len(keys) or any(k not in list("ABCDE"[:len(options)]) for k in keys):
                raise DraftValidationError("answer_labels", "答案不在选项范围内")
            if q.get("type") == "multiple" and (not isinstance(answer, list) or not 2 <= len(answer) < len(options)):
                raise DraftValidationError("multiple_answer_count", f"知识点 {index+1} 第 {qi+1} 题：多选题需要至少两个正确选项和一个错误选项，请重新设计选项，不能把错误选项加入答案")
            if q.get("type") not in ("single", "multiple") or (q["type"] == "single" and not isinstance(answer, str)):
                raise DraftValidationError("question_type", "题型和答案格式不一致")
            explanation = str(q.get("explain") or "").strip()
            if len(explanation) < 8:
                raise DraftValidationError("explanation", "题目缺少可核对的解释")
            stems.add(stem)
            bank.append({"id": f"{kp}-{qi+1}", "kp": kp, "stem": stem, "type": q["type"],
                "options": options, "answer": answer, "explain": explanation, "evidence_ids": list(cited), "difficulty": min(3, max(1, int(q.get("difficulty", 1)))),
                "citations": [{k: v for k, v in item.items() if k != "text"} for item in evidence[kp]]})
        nodes.append({"id": kp, "name": name, "desc": objective[:240], "difficulty": 1, "chapter": name})
        lessons[kp] = str(topic["lesson"])[:5000]
    return {"title": title, "kind": "generated", "bank": bank, "lessons": lessons, "evidence": evidence,
        "graph": {"course_id": "generated", "course": title, "version": 1, "nodes": nodes, "edges": []},
        "boundary": "模型生成的起点检查，答案及难度尚未经教研标定；只描述已测内容。发现题目有问题可以跳过，不据此判定整门课的能力。"}


async def review_course_questions(course: dict, chunks: list[dict]) -> None:
    """Independently solve without showing generated keys; still fallible model review."""
    bank = course["bank"]
    questions = [{**{k: q[k] for k in ("id", "stem", "type", "options")},
        "evidence_ids": q.get("evidence_ids", [])} for q in bank]
    context = json.dumps({"title": course["title"], "materials": [
        {"id": c["evidence_id"], "text": c["text"]} for c in chunks]}, ensure_ascii=False)
    call = invoke_learning_prompt("assessment.course_check", context=context,
        draft=json.dumps(questions, ensure_ascii=False))
    raw = await llm_complete(call.prompt, system=call.system, role="reasoner", temperature=0,
        max_tokens=4500, json_mode=True, json_object=True, reasoning_mode="disabled", allow_mock_fallback=False)
    result = parse_json(raw)
    rows = result.get("questions") if isinstance(result, dict) else None
    if (not isinstance(rows, list) or len(rows) != len(bank)
            or any(not isinstance(row, dict) for row in rows)
            or [row.get("id") for row in rows] != [q["id"] for q in bank]):
        raise DraftValidationError("review_incomplete", "题库独立复核没有覆盖全部题目")
    issues = []
    for q, row in zip(bank, rows):
        labels = list("ABCDE"[:len(q["options"])])
        options = row.get("options")
        complete = (isinstance(options, list) and len(options) == len(labels)
            and all(isinstance(o, dict) for o in options)
            and [o.get("label") for o in options] == labels
            and all(type(o.get("correct")) is bool and str(o.get("reason") or "").strip() for o in options))
        solved = [o["label"] for o in options if o["correct"]] if complete else []
        expected = q["answer"] if isinstance(q["answer"], list) else [q["answer"]]
        if (not complete or row.get("conditions_sufficient") is not True
                or row.get("supported") is not True or set(solved) != set(expected)):
            # Review comments are repair data only, never serialized into HTTP errors.
            issues.append({"id": q["id"], "original_key": expected, "review": row})
    if issues:
        raise DraftValidationError("answer_review", "题目答案、条件或资料支持未通过独立复核",
            repair_issue="请重新设计以下不可靠题目，不能只改字母凑数：" + json.dumps(issues, ensure_ascii=False)[:5000])
    # Never publish the draft's unchecked explanation after reviewing the keys.
    # Reuse the reasons that actually supported the independent option judgments.
    for q, row in zip(bank, rows):
        q["explain"] = "\n".join(
            f"{o['label']}（{'应选' if o['correct'] else '不选'}）：{str(o['reason']).strip()}"
            for o in row["options"])
    course["quality_review"] = {"verification": "model_review", "reviewed_questions": len(bank)}


async def generate_valid_course(prompt, title: str, chunks: list[dict]) -> dict:
    """Repair once after validation; transport policy stays gateway-owned."""
    async def generate():
        call = prompt
        for attempt in range(2):
            raw = await llm_complete(call.prompt, system=call.system, role="reasoner",
                temperature=0.2, max_tokens=6500, json_mode=True, json_object=True,
                reasoning_mode="disabled", allow_mock_fallback=False)
            try:
                course = validate_draft(parse_json(raw), title, chunks)
                await review_course_questions(course, chunks)
                return course
            except (ValueError, TypeError, KeyError) as exc:
                log.warning("Course draft validation rejected attempt %d (%s)", attempt + 1, exc.code if isinstance(exc, DraftValidationError) else "json_or_format")
                if attempt:
                    raise
                call = invoke_learning_prompt("assessment.course_repair", base_request=prompt.prompt,
                    draft=raw, validation_issue=exc.repair_issue if isinstance(exc, DraftValidationError) else "JSON 或字段格式不正确，请按 schema 重写")
        raise ValueError("未取得可核对题目")
    return await asyncio.wait_for(generate(), timeout=110)


async def prepare(user_id: str, notebook_id: str, *, title: str, course_key: str, source_ids: list[str], survey: dict) -> dict:
    ensure_space(user_id, notebook_id)
    survey = {**survey, "notebook_id": notebook_id, "course_key": course_key, "course_title": title, "source_ids": source_ids}
    sources, chunks = material_snapshot(user_id, notebook_id, source_ids)
    intake = {k: v for k, v in survey.items() if k not in ("course_revision", "target_kps")}
    fingerprint = hashlib.sha256(json.dumps([title, course_key, sources, intake], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with session() as db:
        row = db.get(LearningSpace, notebook_id)
        if row.course.get("request_fingerprint") == fingerprint:
            return public_course(row.course)
        active = db.query(AssessmentSession).filter(AssessmentSession.user_id == user_id).all()
        if any(a.data.get("notebook_id") == notebook_id and a.data.get("status") == "active" for a in active):
            raise HTTPException(409, "这门课有未完成的测评，请先继续作答；新课程可以另建学习空间")
    if not source_ids and course_key == "ds_algo":
        from .assessment_service import question_bank, DATA, LESSONS
        from .knowledge_graph import _load_builtin_kg
        graph = _load_builtin_kg()
        course = {"title": graph["course"], "kind": "ds_algo", "bank": question_bank(),
            "lessons": {kp: (DATA / "seed_corpus" / name).read_text(encoding="utf-8").split("---", 2)[-1].strip() for kp, name in LESSONS.items()},
            "graph": {**graph, "nodes": list(graph["nodes"].values())}, "boundary": "自编课程题；未测知识点保持待测，需要换题和延迟复测。"}
    elif not source_ids and course_key in PACKS:
        course = build_pack(course_key)
    else:
        prompt = invoke_learning_prompt("assessment.course_draft", title=title,
            survey=json.dumps(survey, ensure_ascii=False), context=json.dumps([
                {"evidence_id": c["evidence_id"], "source": c["source"], "text": c["text"]}
                for c in chunks], ensure_ascii=False) if chunks else "未提供资料；仅根据明确主题生成初步检查")
        started = time.monotonic()
        try:
            course = await generate_valid_course(prompt, title, chunks)
        except Exception as exc:
            code = "invalid_draft" if isinstance(exc, (ValueError, TypeError, KeyError)) else failure_code(exc)
            log.warning("Course preparation failed code=%s elapsed_ms=%d", code, (time.monotonic() - started) * 1000)
            detail = "题目、题型或原文引用未通过检查，未保存这份题库。" if code == "invalid_draft" else MESSAGES[code]
            raise HTTPException(422 if code == "invalid_draft" else 503,
                detail + (f"原因：{exc}。" if isinstance(exc, DraftValidationError) else "")
                + "原资料和选择已保留，可缩小学习主题后重试。", headers={
                    "X-Learning-Failure": code,
                    "X-Learning-Validation": exc.code if isinstance(exc, DraftValidationError) else "",
                }) from None
        log.info("Course preparation completed elapsed_ms=%d topics=%d", (time.monotonic() - started) * 1000, len(course["graph"]["nodes"]))
    course.update(source_ids=source_ids, sources=sources, request_fingerprint=fingerprint,
        coverage_note="基于所列解析片段选取代表性知识点，未覆盖全文。" if sources else course.get("coverage_note", "只覆盖下面列出的知识点。"))
    course["revision"] = hashlib.sha256(json.dumps(course, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    with session() as db:
        row = db.query(LearningSpace).filter_by(notebook_id=notebook_id, user_id=user_id).with_for_update().one()
        # A concurrent start wins over an in-flight generation.
        active = db.query(AssessmentSession).filter(AssessmentSession.user_id == user_id).all()
        if any(a.data.get("notebook_id") == notebook_id and a.data.get("status") == "active" for a in active):
            raise HTTPException(409, "测评已开始，保留当前题目范围；请继续作答")
        data = copy.deepcopy(row.data)
        data["learning_intake"] = survey
        data["learning_topic"] = course["title"]
        old_kind = row.course.get("kind")
        if (old_kind != course["kind"] or row.course.get("title") != course["title"]
                or sources != row.course.get("sources", []) or row.course.get("bank") != course["bank"]
                or row.course.get("graph") != course["graph"]):
            from .profile_service import default_profile
            data["knowledge_mastery"] = {}
            for key in ("error_prone", "metacognition", "evidence"):
                data[key] = default_profile()[key]
            data.pop("baseline_assessment", None)
            data.pop("baseline_assessment_applied_kps", None)
            row.path = {}
        row.data, row.course, row.version = data, course, row.version + 1
        db.commit()
    return public_course(course)


def context_summary() -> dict | None:
    from .learning_scope import current_space, learning_user
    from .learning_intake import context_reasons
    space = current_space()
    if not space:
        if not learning_user():
            return None
        from .profile_service import get_profile
        profile = get_profile(learning_user())
        if not profile.get("learning_intake"):
            return None
        space = {"notebook_id": "", "profile": profile, "course": {"title": "数据结构与算法", "sources": []}}
    profile, course = space["profile"], space["course"]
    survey = profile.get("learning_intake") or {}
    return {"course": course["title"], "course_revision": course.get("revision"), "notebook_id": space["notebook_id"],
        "goal": survey.get("goal", profile.get("goal")), "goals": survey.get("goals", []),
        "stage": survey.get("stage"), "prior_experience": survey.get("prior_experience"),
        "daily_minutes": survey.get("daily_minutes"), "study_days": survey.get("study_days", []),
        "target_date": survey.get("target_date"), "adaptations": context_reasons(survey),
        "support": survey.get("support", ""), "mastery": profile.get("knowledge_mastery", {}),
        "evidence": profile.get("baseline_assessment", {}).get("skills", []),
        "bound_sources": [{"title": s["title"], "version": s["sha256"][:12]} for s in course.get("sources", [])],
        "textbook": course.get("textbook"), "assessment_boundary": course.get("boundary"),
        "exam_reference": course.get("exam_reference")}
