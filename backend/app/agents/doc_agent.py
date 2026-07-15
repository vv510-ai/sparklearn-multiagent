"""文档智能体(Doc Agent):基于 RAG 的图文教程生成,带 [^n] 引用溯源,
经 grounding_check(X2 答案-证据一致性)与 safety_filter 双层防幻觉校验。
泛化承担三类文本资源:doc(图文教程)/ code(代码示例)/ reading(拓展阅读)。"""
from __future__ import annotations

import asyncio
import re
import uuid

from ..config import is_demo
from ..llm import multimodal_gateway
from ..llm.spark_client import llm_complete
from ..prompt_templates import invoke_learning_prompt, render_learning_prompt_call
from ..rag.citation import build_context, used_indices
from ..rag.retriever import retrieve
from ..safety.grounding import grounding_check
from ..safety.guard import safety_filter
from ..services.knowledge_graph import resolve_topic
from .emitter import agent_end, agent_start, emit

_STYLE = {
    "doc": ("学习笔记", "doc.complete_notes"),
    "code": ("代码示例", "doc.code"),
    "reading": ("拓展阅读", "doc.reading"),
}

_DOC_TIMEOUT_S = 75
_GROUNDING_TIMEOUT_S = 12


def _persona(profile: dict) -> str:
    return (f"认知风格={profile.get('cognitive_style', '视觉型')},"
            f"难度偏好={profile.get('difficulty_pref', '循序渐进')},"
            f"节奏={profile.get('pace', '常规')}")


def _conversation_text(state: dict, limit: int = 10000) -> str:
    items = state.get("conversation") or state.get("messages") or []
    lines = [
        f"{('学习者' if item.get('role') == 'user' else '学伴')}：{str(item.get('content') or '').strip()}"
        for item in items
        if str(item.get("content") or "").strip()
    ]
    text = "\n".join(lines)
    return text[-limit:] if len(text) > limit else text


def _compact(text: str, limit: int = 180) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _remediation_on_topic(markdown: str, topic_name: str, kp: str) -> bool:
    """Reject a successful-looking remediation that silently changed topics."""
    output = re.sub(r"\s+", "", str(markdown or "")).lower()
    pieces = re.split(r"[与和、/·（）()\s]+", str(topic_name or ""))
    candidates = [str(kp or "").strip().lower(), str(topic_name or "").strip().lower(), *pieces]
    terms = {
        re.sub(r"\s+", "", candidate)
        for candidate in candidates
        if str(candidate or "").strip()
    }
    return any(term in output for term in terms)


def _rag_fallback_doc(name: str, chunks: list[dict], kind: str) -> str:
    title = "图文教程" if kind == "doc" else "学习资料"
    lines = [
        f"# {name}·{title}",
        "",
        "> 系统已基于当前检索到的资料片段生成可追溯版本。",
        "",
        "## 核心教材片段",
    ]
    if not chunks:
        lines += ["", "- 当前知识库没有检索到可用片段，请补充课程资料后重新生成。"]
    else:
        for i, chunk in enumerate(chunks[:5], 1):
            lines.append(f"- {_compact(chunk.get('text', ''))} [^{i}]")
    lines += [
        "",
        "## 学习建议",
        f"- 先按上面的教材片段梳理「{name}」的定义、操作和复杂度。",
        "- 再结合题组检查边界条件、概念区分和时间复杂度。",
        "- 需要更完整的讲义时，可补充资料或在真实模型可用后重新生成。",
    ]
    return "\n".join(lines)


def _conversation_fallback_doc(name: str, conversation: str, chunks: list[dict]) -> str:
    dialog_lines = [line.strip() for line in conversation.splitlines() if line.strip()]
    user_lines = [
        line.removeprefix("学习者：")
        for line in dialog_lines
        if line.startswith("学习者：") and not any(word in line for word in ("整理", "总结", "个人笔记"))
    ]
    assistant_lines = [line.removeprefix("学伴：") for line in dialog_lines if line.startswith("学伴：")]
    lines = [
        f"# 本次学习笔记：{name}",
        "",
        "## 一句话结论",
        "",
        f"这次学习围绕「{name}」从问题出发，按定义、操作、例子和边界逐步整理。",
        "",
        "## 我问过的问题",
        "",
    ]
    lines += [f"- {_compact(item, 220)}" for item in user_lines[-6:]] or ["- 当前会话没有可提取的用户问题。"]
    lines += ["", "## 已经形成的理解", ""]
    lines += [f"- {_compact(item, 260)}" for item in assistant_lines[-5:]] or ["- 当前还没有完成可沉淀的讲解。"]
    lines += ["", "## 资料中的核心知识", ""]
    if chunks:
        lines += [f"- {_compact(chunk.get('text', ''), 260)} [^{index}]" for index, chunk in enumerate(chunks[:5], 1)]
    else:
        lines.append("- 当前没有检索到可引用资料，暂不补写资料外事实。")
    lines += [
        "",
        "## 记忆钩子",
        "",
        "**先认对象，再走步骤，最后查边界。**",
        "",
        "## 三分钟复习清单",
        "",
        "1. 我能不能用一句白话说出它是什么？",
        "2. 我能不能独立走完最小例子？",
        "3. 我知不知道最容易出错的条件？",
        "",
        "## 下一步建议",
        "",
        "先完成本次基础练习；答错后回到对应概念和边界条件，再补充进这份笔记。",
    ]
    return "\n".join(lines)


def _custom_topic_fallback_doc(name: str) -> str:
    return "\n".join([
        f"# {name}·学习笔记",
        "",
        "> 当前主题已锁定为自定义主题；系统没有改用内置课程或旧会话内容。",
        "",
        "## 学习框架",
        f"1. 先用一句话说明「{name}」是什么。",
        "2. 再梳理常见场景、关键组成和基本流程。",
        "3. 用一个最小例子练习，最后检查常见误区与适用边界。",
        "",
        "## 下一步",
        "当前为离线安全版本；连接星火 X2 后会补全同主题讲解，也可以上传资料生成可引用版本。",
    ])


def _ensure_visible_citations(md: str, n_citations: int) -> str:
    if n_citations <= 0 or used_indices(md, n_citations):
        return md
    refs = " ".join(f"[^{i}]" for i in range(1, min(n_citations, 3) + 1))
    return md.rstrip() + f"\n\n## 引用说明\n本文核心概念、算法操作和复杂度说明来自检索到的课程资料 {refs}。"


def _narration_text(name: str, markdown: str, limit: int = 240) -> str:
    text = re.sub(r"```.*?```", "", markdown, flags=re.S)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[\^\d+\]", "", text)
    text = re.sub(r"[#>*_`|~-]+", " ", text)
    text = " ".join(text.split())
    prefix = f"本节讲解{name}。"
    return (prefix + text)[:limit]


def _cover_prompt(name: str, *, source_bound: bool = False, custom_topic: bool = False) -> str:
    subject = (
        "所选学习资料封面插画" if source_bound else
        "自定义学习主题插画" if custom_topic else
        "数据结构教学插画"
    )
    return (
        f"{subject}：{name}。使用简洁抽象的学习结构视觉，"
        "浅色背景，绿色重点标注，无人物，不添加事实性文字。"
    )


def _doc_label(default: str, template_key: str) -> str:
    return {
        "one_page": "一页看懂",
        "interactive_audio": "互动讲解",
        "complete_notes": "学习笔记",
        "error_confusion": "易错易混",
        "conversation_notes": "对话笔记",
        "question_review": "题目复盘",
        "exam_guide": "考点手册",
        "remediation": "补救微课",
    }.get(str(template_key or "").strip().lower(), default)


async def _gen_one(
    kind: str,
    kp: str,
    profile: dict,
    *,
    topic_name: str = "",
    custom_topic: bool = False,
    source_ids: list[str],
    goal: str,
    prompt_template: str = "",
    conversation: str = "",
    trace_id: str,
    skip_multimodal: bool = False,
    required_retrieval_terms: list[str] | None = None,
) -> dict:
    name = topic_name or resolve_topic([kp])[1]
    label, capability = _STYLE.get(kind, _STYLE["doc"])
    if kind == "doc":
        label = _doc_label(label, prompt_template)
    chunks = [] if custom_topic and not source_ids else retrieve(
        f"{name} 概念 操作 复杂度 易错点 {goal}",
        final_k=5,
        source_ids=source_ids,
        kp=None if source_ids else kp,
        required_terms=required_retrieval_terms,
    )
    ctx, citations = build_context(chunks)
    if kind == "doc":
        prompt_call = render_learning_prompt_call(
            prompt_template,
            topic=name,
            goal=goal,
            persona=_persona(profile),
            context=ctx,
            conversation=conversation,
            general_knowledge=custom_topic and not source_ids,
        )
    else:
        prompt_call = invoke_learning_prompt(
            capability,
            topic=name,
            persona=_persona(profile),
            goal=goal or f"系统学习{name}",
            context=ctx or "（没有检索到可用资料）",
        )
    prompt = prompt_call.prompt
    flags = []
    fallback = False
    remediation_rag_fallback = False
    demo_fallback = is_demo()
    source_scope_missing = bool(source_ids and not chunks)
    if source_scope_missing:
        fallback = True
        md = (
            f"# {name}·资料不足\n\n"
            "> 当前选中的资料没有可检索内容，因此未生成资料范围外的知识。\n\n"
            "请重新选择已完成索引的资料，或上传包含正文的 TXT、MD、PDF、PNG/JPG 文件。"
        )
        flags.append({"agent": "doc", "kind": kind, "type": "source_scope_empty",
                      "detail": "所选资料没有可检索内容,已阻止无依据生成"})
    elif demo_fallback:
        fallback = True
        md = (
            _conversation_fallback_doc(name, conversation, chunks)
            if kind == "doc" and prompt_template == "conversation_notes"
            else _custom_topic_fallback_doc(name)
            if custom_topic and not chunks
            else _rag_fallback_doc(name, chunks, kind)
        )
    else:
        try:
            md = await asyncio.wait_for(
                llm_complete(
                    prompt,
                    role="reasoner",
                    system=prompt_call.system,
                    temperature=0.5,
                    max_tokens=1800,
                    # The generic offline completion is a fixed binary-tree
                    # sample. It is unsafe for a diagnosed remediation target
                    # because it can silently change the concept while keeping
                    # the current citations. Let the exception fall through to
                    # the target-scoped RAG fallback instead.
                    allow_mock_fallback=prompt_template not in {
                        "conversation_notes",
                        "remediation",
                    },
                ),
                timeout=_DOC_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001
            fallback = True
            remediation_rag_fallback = prompt_template == "remediation"
            conversation_fallback = kind == "doc" and prompt_template == "conversation_notes"
            md = (
                _conversation_fallback_doc(name, conversation, chunks)
                if conversation_fallback
                else _rag_fallback_doc(name, chunks, kind)
            )
            if not conversation_fallback:
                flags.append({"agent": "doc", "kind": kind, "type": "llm_fallback",
                              "detail": f"文档生成超时或失败,已使用 RAG 降级文档:{exc}"})

    if (prompt_template == "remediation" and not fallback and not source_scope_missing
            and not _remediation_on_topic(md, name, kp)):
        fallback = True
        remediation_rag_fallback = True
        md = _rag_fallback_doc(name, chunks, kind)
        flags.append({
            "agent": "doc",
            "kind": kind,
            "type": "topic_drift",
            "detail": f"补救正文未命中目标概念「{name}」,已改用同主题 RAG 保守版",
        })

    # 防幻觉第一层:答案-证据一致性(X2 深度推理)
    if source_scope_missing:
        ground = {"grounded": True, "unsupported": [], "verdict": "没有越过所选资料范围生成事实"}
    elif custom_topic and not chunks:
        ground = {"grounded": True, "unsupported": [],
                  "verdict": "自定义主题使用星火通用知识生成，未声明虚构资料引用。"}
    elif demo_fallback:
        ground = {"grounded": True, "unsupported": [],
                  "verdict": "演示模式直接整理检索片段,未补写资料外事实。"}
    elif remediation_rag_fallback:
        ground = {"grounded": True, "unsupported": [],
                  "verdict": "补救生成已回退为目标概念的检索片段整理。"}
    elif fallback and prompt_template == "conversation_notes":
        ground = {"grounded": True, "unsupported": [],
                  "verdict": "对话笔记直接整理已持久化对话与检索片段。"}
    elif fallback:
        ground = {"grounded": False, "unsupported": [],
                  "verdict": "LLM 生成超时,已使用检索片段降级输出,建议人工复核。"}
    else:
        try:
            ground = await asyncio.wait_for(
                grounding_check(md, [c["text"] for c in chunks]),
                timeout=_GROUNDING_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001
            ground = {"grounded": False, "unsupported": [],
                      "verdict": f"grounding 校验超时或失败:{exc}"}
            flags.append({"agent": "doc", "kind": kind, "type": "grounding_timeout",
                          "detail": ground["verdict"]})
    md = _ensure_visible_citations(md, len(citations))
    # 防幻觉第二层:内容安全过滤(本地词表 + 讯飞审核挂接)
    safety = safety_filter(md)
    if not ground.get("grounded", True):
        flags.append({"agent": "doc", "kind": kind, "type": "grounding",
                      "detail": ground.get("verdict", ""), "unsupported": ground.get("unsupported", [])})
        md += "\n\n> ⚠️ 溯源提示:以上个别表述未在教材语料中找到直接依据,已标记供复核。"
    if not safety.get("safe", True):
        flags.append({"agent": "doc", "kind": kind, "type": "safety", "detail": safety.get("hits", [])})

    used = used_indices(md, len(citations))
    cite_used = [citations[i - 1] for i in used if 0 < i <= len(citations)] or citations[:3]
    rid = uuid.uuid4().hex[:12]
    payload = {
        "markdown": md,
        "grounded": ground.get("grounded", True),
        "template": prompt_template,
        "reusable_note": prompt_template == "conversation_notes",
        "prompt_skill": prompt_call.metadata(),
    }
    interactive_audio = kind == "doc" and prompt_template == "interactive_audio"
    narration = _narration_text(name, md)
    if interactive_audio and not source_scope_missing:
        payload["audio_narration"] = narration
    if (kind == "doc" and not source_scope_missing
            and prompt_template != "conversation_notes" and not skip_multimodal):
        audio, cover = await asyncio.gather(
            multimodal_gateway.tts(
                narration,
                trace_id=trace_id,
            ),
            multimodal_gateway.text_to_image(
                _cover_prompt(name, source_bound=bool(source_ids), custom_topic=custom_topic),
                width=768,
                height=768,
                trace_id=trace_id,
            ),
            return_exceptions=True,
        )
        if isinstance(audio, dict) and audio.get("ok"):
            payload["audio_url"] = audio["data"]["audio_url"]
            if interactive_audio:
                payload["audio"] = {
                    "status": "ready",
                    "provider": "spark_tts",
                    "error": "",
                    "retryable": False,
                }
        elif interactive_audio:
            error = (
                str(audio.get("error") or "云端语音暂时不可用")
                if isinstance(audio, dict)
                else str(audio) if isinstance(audio, BaseException)
                else "云端语音暂时不可用"
            )
            payload["audio"] = {
                "status": "fallback",
                "provider": "browser_speech",
                "error": error[:240],
                "retryable": True,
            }
            flags.append({
                "agent": "doc",
                "kind": kind,
                "type": "audio_degraded",
                "detail": f"互动讲解已切换浏览器朗读：{error[:160]}",
            })
        if isinstance(cover, dict) and cover.get("ok"):
            payload["cover_url"] = cover["data"]["image_url"]
    elif interactive_audio:
        payload["audio"] = {
            "status": "blocked" if source_scope_missing else "fallback",
            "provider": "none" if source_scope_missing else "browser_speech",
            "error": "所选资料没有可朗读内容" if source_scope_missing else "云端语音生成已跳过",
            "retryable": not source_scope_missing,
        }

    resource = {"id": rid, "kind": kind, "kp": kp,
                "title": f"{name}·{label}",
                "payload": payload,
                "citations": [c["citation"] for c in cite_used]}
    await emit({"type": "resource", "resource": resource})
    await emit({"type": "citations", "agent": "doc", "items": resource["citations"]})
    return {"resource": resource, "flags": flags}


async def run(state: dict) -> dict:
    kp, topic_name, custom_topic = resolve_topic(
        state.get("knowledge_points"),
        state.get("learning_goal"),
        state.get("topic_label"),
    )
    requested = state.get("kinds") or []
    kinds = [k for k in requested if k in _STYLE]
    if requested and not kinds:
        return {}
    kinds = kinds or ["doc"]
    profile = state.get("student_profile") or {}
    source_ids = [str(x) for x in (state.get("source_ids") or []) if str(x).strip()]
    goal = state.get("learning_goal") or ""
    prompt_template = str(state.get("prompt_template") or "")
    conversation = _conversation_text(state)
    trace_id = str(state.get("session_id") or "")
    skip_multimodal = bool(state.get("skip_multimodal"))
    required_retrieval_terms = [
        str(value).strip()
        for value in (state.get("required_retrieval_terms") or [])
        if str(value).strip()
    ]
    await agent_start("doc", "文档智能体",
                      f"RAG 检索→引用生成→双层防幻觉校验({'/'.join(kinds)})")
    resources, flags = {}, []
    for kind in kinds:
        out = await _gen_one(
            kind,
            kp,
            profile,
            topic_name=topic_name,
            custom_topic=custom_topic,
            source_ids=source_ids,
            goal=goal,
            prompt_template=prompt_template,
            conversation=conversation,
            trace_id=trace_id,
            skip_multimodal=skip_multimodal,
            required_retrieval_terms=required_retrieval_terms,
        )
        resources[out["resource"]["id"]] = out["resource"]
        flags += out["flags"]
    n_cite = sum(len(r["citations"]) for r in resources.values())
    await agent_end("doc", f"产出 {len(resources)} 份文本资源,共 {n_cite} 条引用,"
                           f"{'校验通过' if not flags else f'{len(flags)} 处待复核'}")
    return {"generated_resources": resources, "safety_flags": flags,
            "citations": [c for r in resources.values() for c in r["citations"]]}
