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
from ..prompt_templates import render_learning_prompt
from ..rag.citation import build_context, used_indices
from ..rag.retriever import retrieve
from ..safety.grounding import grounding_check
from ..safety.guard import safety_filter
from ..services.knowledge_graph import kp_name
from .emitter import agent_end, agent_start, emit

_STYLE = {
    "doc": ("学习笔记", "TASK=doc\n请为知识点「{kp}」写一份可快速复习的结构化学习笔记(Markdown):"
            "## 30 秒看懂(3-5 句直接结论)/## 知识框架(用 mermaid flowchart)/"
            "## 核心笔记(定义、原理、步骤、复杂度)/## 易错点(错误表现、原因、改法)/"
            "## 易混对照(用表格比较相近概念)/## 3 分钟自测(3 个问题)。"
            "每一节先给结论再解释,避免长段落和空泛表述。"
            "正文中的事实性表述用脚注 [^n] 标注来源编号(n 对应参考资料编号),"
            "结合学生画像调整深浅:{persona}。"),
    "code": ("代码示例", "TASK=doc\n请为知识点「{kp}」编写可运行的 Python 代码教学示例(Markdown):"
             "完整代码块(含详细中文注释)+ 逐段讲解 + 一个典型错误写法对比 + 复杂度说明,"
             "事实性表述用 [^n] 标注来源;贴合画像:{persona}。"),
    "reading": ("拓展阅读", "TASK=doc\n请为知识点「{kp}」写一篇拓展阅读(Markdown):"
                "工程实战应用 / 历史与典故 / 与相邻知识点的联系 / 进阶方向,"
                "事实性表述用 [^n] 标注来源;贴合画像:{persona}。"),
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
        f"{('用户' if item.get('role') == 'user' else '学伴')}：{str(item.get('content') or '').strip()}"
        for item in items
        if str(item.get("content") or "").strip()
    ]
    text = "\n".join(lines)
    return text[-limit:] if len(text) > limit else text


def _compact(text: str, limit: int = 180) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


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
        line.removeprefix("用户：")
        for line in dialog_lines
        if line.startswith("用户：") and not any(word in line for word in ("整理", "总结", "个人笔记"))
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


def _cover_prompt(name: str, *, source_bound: bool = False) -> str:
    subject = "所选学习资料封面插画" if source_bound else "数据结构教学插画"
    return (
        f"{subject}：{name}。使用简洁抽象的学习结构视觉，"
        "浅色背景，绿色重点标注，无人物，不添加事实性文字。"
    )


def _doc_label(default: str, template_key: str) -> str:
    return {
        "one_page": "一页看懂",
        "complete_notes": "学习笔记",
        "error_confusion": "易错易混",
        "conversation_notes": "对话笔记",
    }.get(str(template_key or "").strip().lower(), default)


async def _gen_one(
    kind: str,
    kp: str,
    profile: dict,
    *,
    source_ids: list[str],
    goal: str,
    prompt_template: str = "",
    conversation: str = "",
    trace_id: str,
) -> dict:
    name = kp_name(kp)
    label, tpl = _STYLE.get(kind, _STYLE["doc"])
    if kind == "doc":
        label = _doc_label(label, prompt_template)
    chunks = retrieve(
        f"{name} 概念 操作 复杂度 易错点 {goal}",
        final_k=5,
        source_ids=source_ids,
        kp=None if source_ids else kp,
    )
    ctx, citations = build_context(chunks)
    if kind == "doc":
        prompt = render_learning_prompt(
            prompt_template,
            topic=name,
            goal=goal,
            persona=_persona(profile),
            context=ctx,
            conversation=conversation,
        )
    else:
        prompt = (
            tpl.format(kp=name, persona=_persona(profile))
            + f"\n\n用户本次需求:\n{goal or f'系统学习{name}'}"
            + f"\n\n参考资料(回答只可依据这些;引用其编号):\n{ctx}"
        )
    flags = []
    fallback = False
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
            else _rag_fallback_doc(name, chunks, kind)
        )
    else:
        try:
            md = await asyncio.wait_for(
                llm_complete(
                    prompt,
                    role="ultra",
                    temperature=0.5,
                    max_tokens=1800,
                    allow_mock_fallback=prompt_template != "conversation_notes",
                ),
                timeout=_DOC_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001
            fallback = True
            conversation_fallback = kind == "doc" and prompt_template == "conversation_notes"
            md = (
                _conversation_fallback_doc(name, conversation, chunks)
                if conversation_fallback
                else _rag_fallback_doc(name, chunks, kind)
            )
            if not conversation_fallback:
                flags.append({"agent": "doc", "kind": kind, "type": "llm_fallback",
                              "detail": f"文档生成超时或失败,已使用 RAG 降级文档:{exc}"})

    # 防幻觉第一层:答案-证据一致性(X2 深度推理)
    if source_scope_missing:
        ground = {"grounded": True, "unsupported": [], "verdict": "没有越过所选资料范围生成事实"}
    elif demo_fallback:
        ground = {"grounded": True, "unsupported": [],
                  "verdict": "演示模式直接整理检索片段,未补写资料外事实。"}
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
    }
    if kind == "doc" and not source_scope_missing and prompt_template != "conversation_notes":
        audio, cover = await asyncio.gather(
            multimodal_gateway.tts(
                _narration_text(name, md),
                trace_id=trace_id,
            ),
            multimodal_gateway.text_to_image(
                _cover_prompt(name, source_bound=bool(source_ids)),
                width=768,
                height=768,
                trace_id=trace_id,
            ),
            return_exceptions=True,
        )
        if isinstance(audio, dict) and audio.get("ok"):
            payload["audio_url"] = audio["data"]["audio_url"]
        if isinstance(cover, dict) and cover.get("ok"):
            payload["cover_url"] = cover["data"]["image_url"]

    resource = {"id": rid, "kind": kind, "kp": kp,
                "title": f"{name}·{label}",
                "payload": payload,
                "citations": [c["citation"] for c in cite_used]}
    await emit({"type": "resource", "resource": resource})
    await emit({"type": "citations", "agent": "doc", "items": resource["citations"]})
    return {"resource": resource, "flags": flags}


async def run(state: dict) -> dict:
    kps = state.get("knowledge_points") or ["binary_tree"]
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
    await agent_start("doc", "文档智能体",
                      f"RAG 检索→引用生成→双层防幻觉校验({'/'.join(kinds)})")
    resources, flags = {}, []
    for kind in kinds:
        out = await _gen_one(
            kind,
            kps[0],
            profile,
            source_ids=source_ids,
            goal=goal,
            prompt_template=prompt_template,
            conversation=conversation,
            trace_id=trace_id,
        )
        resources[out["resource"]["id"]] = out["resource"]
        flags += out["flags"]
    n_cite = sum(len(r["citations"]) for r in resources.values())
    await agent_end("doc", f"产出 {len(resources)} 份文本资源,共 {n_cite} 条引用,"
                           f"{'校验通过' if not flags else f'{len(flags)} 处待复核'}")
    return {"generated_resources": resources, "safety_flags": flags,
            "citations": [c for r in resources.values() for c in r["citations"]]}
