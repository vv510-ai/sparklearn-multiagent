"""评估智能体(Eval Agent):并行 fan-in 汇聚点。
1) 汇总各生成节点的 safety_flags 做整体质检结论;
2) 资源批量落库(Resource 表),记录 EventLog;
3) 产出本轮生成总结(emit summary),为前端 done 事件提供收尾文案。
(答题评估→BKT→路径重排的"学习闭环"在 /api/eval/submit 中复用本模块的 evaluate_answers。)"""
from __future__ import annotations



from ..models.db import session
from ..models.entities import Resource
from ..services.bkt import mastery_level
from ..services.diagnosis_service import apply_diagnosis_to_path, diagnose_answers
from ..services.knowledge_graph import kp_name
from ..services.metacognition_service import (apply_metacognition_calibration,
                                               calibration_signal,
                                               normalize_confidence)
from ..services.ownership_service import sync_resource_ownership
from ..services.path_service import plan_path, save_path
from ..services.profile_service import get_profile, log_event, update_mastery
from .emitter import agent_end, agent_start, emit


_ARTIFACT_READY_TEXT = {
    "interactive_audio": "互动讲解已经准备好了，点开下面的卡片就能边听边问。",
    "one_page": "一图看懂已经整理好了，打开下面的卡片即可回顾。",
    "framework": "知识框架已经整理好了，打开下面的导图查看。",
    "complete_notes": "学习笔记已经整理好了，打开下面的卡片查看。",
    "error_confusion": "易错易混要点已经整理好了，打开下面的卡片查看。",
    "quiz": "巩固练习已经准备好了，可以直接在下面开始作答。",
    "video": "讲解内容已经准备好了，打开下面的卡片开始学习。",
}


def _learner_summary(resources: dict, flags: list, prompt_template: str = "") -> str:
    """Return a learner-facing handoff; technical checks remain in trace evidence."""
    if not resources:
        return "这次还没有生成可用内容，可以换一种说法或重新选择学习资料后再试。"
    unavailable = [resource for resource in resources.values()
                   if (resource.get("payload") or {}).get("generation_mode") == "unavailable"
                   or (resource.get("payload") or {}).get("blocked_reason")]
    if unavailable:
        if len(unavailable) == len(resources):
            if prompt_template == "one_page":
                reasons = {(r.get("payload") or {}).get("blocked_reason") for r in unavailable}
                if "topic_missing" in reasons:
                    return "请说明要画的课程或章节，或先选择相关资料；本次尚未调用小云雀。"
                if "topic_mismatch" in reasons:
                    return "知识内容未通过本次主题核对，本次尚未调用小云雀。请查看卡片中的原因后重试。"
                if "generation_failed" in reasons:
                    return "知识底稿生成失败，本次尚未调用小云雀。请查看卡片中的具体原因后重试。"
            if any((resource.get("payload") or {}).get("blocked_reason") == "generation_failed" for resource in unavailable):
                return "这次没有生成可用的学习内容：生成失败，且没有可展示的相关资料。请重试或检查模型连接。"
            if prompt_template == "one_page":
                return "一图看懂未生成：当前资料未找到与这次问题相关的内容。请细化问题或选择相关资料后重试。"
            return "这次没有生成可用的学习内容。当前资料未找到相关依据；可以选择相关资料，或允许补充通用知识后重试。"
        return "部分学习内容未生成。已保留可用内容，未完成的项目已说明原因。"
    if any(flag.get("type") == "source_scope_empty" for flag in flags):
        return "部分学习内容未生成：相关资料不足。已保留本次可用内容。"
    if prompt_template == "one_page":
        payloads = [resource.get("payload") or {} for resource in resources.values()]
        if all(payload.get("generation_mode") == "unavailable" for payload in payloads):
            return "一图看懂未生成：当前资料未找到与这次问题相关的内容。请细化问题或选择相关资料后重试。"
        visuals = [payload["one_page_visual"] for payload in payloads if payload.get("one_page_visual")]
        pages = [page for visual in visuals for page in (visual.get("pages") or [visual])]
        if pages and any(page.get("image_status") != "ready" for page in pages):
            return "部分图片未生成，已保留可用图片和文字内容。" if any(page.get("image_status") == "ready" for page in pages) else "图片未生成，已保留文字内容与出处，可先阅读文字版后重试。"
        if any(page.get("renderer") in {"xiaoyunque-infographic-v1", "chatgpt-web-infographic-v1"} and
               (page.get("verification") or {}).get("status") != "passed" for page in pages):
            return "知识图已生成，但自动核对仍有未确认项。请先查看图上的提示，并结合文字版与出处核对。"
        if pages and all(page.get("renderer") in {"xiaoyunque-infographic-v1", "chatgpt-web-infographic-v1"} for page in pages):
            return "知识图已生成并完成自动核对，可打开图片并对照文字版与出处阅读。"
        if any(visual.get("layout") == "text_excerpt" for visual in visuals):
            return "关系图尚未生成，已保留完整文字摘要与出处。可打开卡片阅读。"
        if any(visual.get("content_status") == "source_excerpt" for visual in visuals):
            return "本次扩写未通过核对，已保留资料摘录与出处，关系图尚未生成。"
    text = _ARTIFACT_READY_TEXT.get(
        prompt_template,
        "学习内容已经准备好了，打开下面的卡片继续学习。",
    )
    if flags:
        text += " 有需要留意的地方已在卡片里标出。"
    return text


def _refresh_mindmap_labels(user_id: str, affected_kps: set[str], profile: dict) -> dict:
    """Best-effort relabeling; never block quiz grading or path replan."""
    if not affected_kps:
        return {"updated": 0, "skipped": 0}
    try:
        from .mindmap_agent import refresh_markmap_labels
    except Exception:
        return {"updated": 0, "skipped": 0}

    updated = 0
    skipped = 0
    with session() as s:
        rows = (
            s.query(Resource)
            .filter(Resource.user_id == user_id, Resource.kind == "mindmap")
            .all()
        )
        for row in rows:
            try:
                payload = row.payload if isinstance(row.payload, dict) else {}
                from ..services.learning_scope import event_in_scope
                if not event_in_scope(payload):
                    continue
                if payload.get("conversation_map"):
                    # 会话全景导图的标题表达学习顺序，不应被单知识点掌握度重写。
                    continue
                markmap = payload.get("markmap")
                if not isinstance(markmap, str) or not markmap.strip():
                    skipped += 1
                    continue

                outline = payload.get("outline_node_ids")
                node_ids = set()
                if isinstance(outline, list):
                    for item in outline:
                        if isinstance(item, dict) and item.get("id"):
                            node_ids.add(str(item["id"]))
                        elif isinstance(item, str):
                            node_ids.add(item)
                if row.kp:
                    node_ids.add(row.kp)
                if node_ids and not (node_ids & affected_kps):
                    continue

                new_markmap, changed = refresh_markmap_labels(
                    markmap,
                    row.kp,
                    profile,
                    outline_node_ids=outline if isinstance(outline, list) else None,
                )
                if changed:
                    new_payload = dict(payload)
                    new_payload["markmap"] = new_markmap
                    row.payload = new_payload
                    updated += 1
            except Exception:
                skipped += 1
                continue
        s.commit()
    return {"updated": updated, "skipped": skipped}


async def run(state: dict) -> dict:
    resources: dict = state.get("generated_resources") or {}
    flags: list = state.get("safety_flags") or []
    user_id = state.get("user_id", "demo_user")
    await agent_start("eval", "评估智能体", f"质检 {len(resources)} 份资源并落库")

    with session() as s:
        for rid, r in resources.items():
            payload = dict(r.get("payload", {}) or {})
            if state.get("notebook_id"):
                payload["notebook_id"] = str(state["notebook_id"])
                from ..services.course_learning_service import context_summary
                payload["learning_context"] = context_summary()
                payload["course_revision"] = (payload["learning_context"] or {}).get("course_revision")
            payload["generation_scope"] = {
                "notebook_id": str(state.get("notebook_id") or ""),
                "session_id": str(state.get("session_id") or ""),
                "conversation_focus": str(state.get("conversation_focus") or ""),
                "source_ids": [str(value) for value in (state.get("source_ids") or [])],
                "artifact_scope": str(state.get("artifact_scope") or "current_topic"),
            }
            r["payload"] = payload
            s.merge(Resource(id=rid, user_id=user_id, kind=r.get("kind", "doc"),
                             kp=r.get("kp", ""), title=r.get("title", ""),
                             payload=payload,
                             citations=r.get("citations", []) or [],
                             safety={"flags": [f for f in flags
                                               if f.get("agent") == r.get("kind")
                                               or f.get("kind") == r.get("kind")]}))
        s.commit()
    for rid, resource in resources.items():
        sync_resource_ownership(user_id, rid, resource.get("payload", {}) or {})
    log_event(user_id, "generate_done",
              {"n": len(resources), "kinds": sorted({r.get("kind") for r in resources.values()})})

    summary = _learner_summary(resources, flags, str(state.get("prompt_template") or ""))
    await emit({"type": "summary", "agent": "eval", "text": summary,
                "n_resources": len(resources), "n_flags": len(flags)})
    await agent_end("eval", summary)
    return {"progress_events": [{"agent": "eval", "summary": summary}]}


def _calendar_evidence(answers: list[dict]) -> list[dict]:
    from ..services.assessment_service import evidence_key
    return [{"key": evidence_key(str(a["kp"]), str(a["stem"])), "kp": a["kp"],
             "correct": bool(a.get("correct")), "support_level": a.get("support_level", "independent")}
            for a in answers if a.get("stem") and a.get("kp")]


def evaluate_answers(user_id: str, answers: list[dict]) -> dict:
    """答题闭环:BKT 逐题更新掌握度 → 错因标签回写画像 → 路径重排 → 评估报告。
    answers: [{question_id, kp, correct, mastery_correct?, error_tags?, type?, difficulty?}]

    ``correct`` is the raw grading result. ``mastery_correct`` is the learning
    evidence used by BKT, so an answer seen via reveal cannot inflate mastery.
    """
    per_kp: dict[str, dict] = {}
    error_counter: dict[str, int] = {}
    items: list[dict] = []
    affected_kps: set[str] = set()
    for a in answers:
        kp, correct = a.get("kp", ""), bool(a.get("correct"))
        mastery_correct = bool(a.get("mastery_correct", correct))
        if not kp:
            continue
        affected_kps.add(kp)
        support_level = str(a.get("support_level") or ("revealed" if a.get("revealed") else "hinted" if a.get("hint_used") else "independent"))
        new_m = update_mastery(user_id, kp, mastery_correct, item_type=str(a.get("type") or ""),
                               options=len(a.get("options") or []), support=support_level)
        d = per_kp.setdefault(
            kp,
            {"kp": kp, "name": kp_name(kp), "n": 0, "right": 0,
             "mastery_right": 0, "supported": 0},
        )
        d["n"] += 1
        d["right"] += int(correct)
        d["mastery_right"] += int(mastery_correct)
        d["supported"] += int(support_level != "independent")
        confidence = normalize_confidence(a.get("confidence"))
        calibration_eligible = bool(confidence) and support_level == "independent"
        signal = (calibration_signal(confidence, correct) if calibration_eligible else
                  "supported" if confidence else "unrecorded")
        d["confidence_recorded"] = d.get("confidence_recorded", 0) + int(calibration_eligible)
        d["confident_wrong"] = d.get("confident_wrong", 0) + int(signal == "confident_wrong")
        d["uncertain_correct"] = d.get("uncertain_correct", 0) + int(signal == "uncertain_correct")
        d["mastery"] = round(new_m, 3)
        d["level"] = mastery_level(new_m)
        items.append({
            "review_item_id": a.get("review_item_id"),
            "quiz_resource_id": a.get("quiz_resource_id", ""),
            "question_id": a.get("question_id", ""),
            "kp": kp,
            "correct": correct,
            "mastery_correct": mastery_correct,
            "answer": a.get("answer", ""),
            "expected": a.get("expected", ""),
            "type": a.get("type", ""),
            "difficulty": a.get("difficulty", 0),
            "explain": a.get("explain", ""),
            "error_tags": a.get("error_tags") or [],
            "hint_used": bool(a.get("hint_used")),
            "revealed": bool(a.get("revealed")),
            "misconception": a.get("misconception", ""),
            "support_level": support_level,
            "evidence_phase": a.get("evidence_phase", "initial"),
            "seconds": a.get("seconds", 0),
            "confidence": confidence,
            "calibration_signal": signal,
            "mastery": round(new_m, 3),
            "level": mastery_level(new_m),
        })
        if not mastery_correct:
            for t in a.get("error_tags") or ["未归因"]:
                error_counter[t] = error_counter.get(t, 0) + 1

    profile = get_profile(user_id)
    if error_counter:                                    # 错因画像回写(取频次最高的前 3)
        top = sorted(error_counter.items(), key=lambda x: -x[1])[:3]
        merged = list(dict.fromkeys((profile.get("error_prone") or []) + [t for t, _ in top]))[:6]
        from ..services.profile_service import merge_profile
        profile = merge_profile(user_id, {"error_prone": merged})

    calibration, profile = apply_metacognition_calibration(user_id, answers, profile)

    diagnosis = diagnose_answers(items, profile)
    path = apply_diagnosis_to_path(
        plan_path(profile),
        diagnosis,
    )                                                   # 据诊断结果插入补救或继续路径
    save_path(user_id, path)
    mindmap_refresh = _refresh_mindmap_labels(user_id, affected_kps, profile)
    log_event(user_id, "quiz_eval", {"per_kp": per_kp, "errors": error_counter,
                                     "learning_evidence": _calendar_evidence(answers),
                                     "evidence_phases": sorted({
                                         str(a.get("evidence_phase", "initial")) for a in answers
                                     }),
                                     "diagnosis": diagnosis,
                                     "calibration": calibration,
                                     "mindmap_refresh": mindmap_refresh})

    total = sum(d["n"] for d in per_kp.values()) or 1
    right = sum(d["right"] for d in per_kp.values())
    weakest = min(per_kp.values(), key=lambda d: d.get("mastery", 1.0)) if per_kp else None
    suggestions = []
    if weakest and weakest.get("mastery", 1) < 0.6:
        suggestions.append(f"「{weakest['name']}」掌握度 {weakest['mastery']:.0%},"
                           f"建议回看图文教程并重练易错题。")
    if diagnosis.get("status") == "needed":
        suggestions.insert(0, str(diagnosis.get("reason") or "建议先完成补救学习。"))
    for t, _ in sorted(error_counter.items(), key=lambda x: -x[1])[:2]:
        suggestions.append(f"错因「{t}」出现较多,已加入你的易错画像,后续出题将针对强化。")
    if not suggestions:
        suggestions.append("正确率良好,可沿路径解锁下一知识点,尝试挑战难度 +1。")
    return {"accuracy": round(right / total, 3), "per_kp": list(per_kp.values()),
            "items": items,
            "error_tags": error_counter, "suggestions": suggestions,
            "calibration": calibration,
            "diagnosis": diagnosis,
            "path": path, "profile_version": profile.get("_version"),
            "mindmap_refresh": mindmap_refresh}
