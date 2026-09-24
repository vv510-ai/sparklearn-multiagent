"""文档智能体(Doc Agent):基于 RAG 的图文教程生成,带 [^n] 引用溯源,
经 grounding_check(X2 答案-证据一致性)与 safety_filter 双层防幻觉校验。
泛化承担文本资源与显式复习 PPT:doc(图文教程)/ code(代码示例)/
reading(拓展阅读)/ ppt(讯飞智能 PPT 异步任务)。"""
from __future__ import annotations

from ..services.model_preferences import resolve

import asyncio
import json
import re
import uuid

from ..config import is_demo
from ..llm import multimodal_gateway
from ..llm.spark_client import llm_complete, parse_json
from ..llm.failures import failure_code, generation_details, MESSAGES
from ..prompt_templates import invoke_learning_prompt, render_learning_prompt_call
from ..rag.citation import build_context, used_indices
from ..rag.retriever import retrieve
from ..safety.grounding import grounding_check, grounding_check_local
from ..safety.guard import safety_filter
from ..services.knowledge_graph import infer_kp_ids, resolve_topic
from ..services.learner_content import plain_learning_text, without_source_code
from ..services.one_page_renderer import render_one_page
from ..services.knowledge_map_layout import map_plan
from ..services.topic_scope import focus_chunks_on_topic, topic_terms
from ..services.learning_context import supplemental_context
from .emitter import agent_end, agent_start, emit

_STYLE = {
    "doc": ("学习笔记", "doc.complete_notes"),
    "code": ("代码示例", "doc.code"),
    "reading": ("拓展阅读", "doc.reading"),
    "ppt": ("复习PPT", "doc.complete_notes"),
    "flashcards": ("闪卡", "doc.flashcards"),
    "infographic": ("信息图", "doc.infographic"),
    "data_table": ("数据表", "doc.data_table"),
}

_STRUCTURED_KINDS = {"flashcards", "infographic", "data_table"}

_DOC_TIMEOUT_S = 75
_GROUNDING_TIMEOUT_S = 12


def _persona(profile: dict) -> str:
    return (f"认知风格={profile.get('cognitive_style', '视觉型')},"
            f"难度偏好={profile.get('difficulty_pref', '循序渐进')},"
            f"节奏={profile.get('pace', '常规')}")


def _conversation_text(state: dict, limit: int = 10000) -> str:
    items = state.get("conversation") or state.get("messages") or []
    lines = [
        f"{('学习者' if item.get('role') == 'user' else '小知')}：{str(item.get('content') or '').strip()}"
        for item in items
        if str(item.get("content") or "").strip()
    ]
    text = "\n".join(lines)
    return "（较早对话超出本次整理范围，以下是最近的可用对话；不得声称涵盖全部历史。）\n" + text[-limit:] if len(text) > limit else text


def _compact(text: str, limit: int = 180) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _plain_excerpt(text: str, limit: int = 150) -> str:
    return plain_learning_text(text, limit)


def _fallback_structured(kind: str, name: str, chunks: list[dict]) -> dict:
    excerpts = [
        _plain_excerpt(chunk.get("text", ""), 190)
        for chunk in chunks[:6]
        if _plain_excerpt(chunk.get("text", ""), 190)
    ]
    if not excerpts:
        excerpts = [
            f"先用一句白话说明「{name}」是什么，再确认它解决什么问题。",
            "按对象、条件、步骤和边界四个位置建立理解框架。",
            "完成一个最小例子后，再用反例检查是否真正理解。",
        ]

    if kind == "flashcards":
        prompts = ["核心定义", "关键机制", "最小例子", "容易混淆的边界", "复习检查"]
        cards = []
        for index, excerpt in enumerate(excerpts[:5]):
            label = prompts[index] if index < len(prompts) else f"要点 {index + 1}"
            cards.append({
                "id": f"card-{index + 1}",
                "front": f"{name}的{label}是什么？",
                "back": excerpt,
                "hint": "先回忆关键词，再翻面核对。",
                "source_index": index + 1 if index < len(chunks) else None,
            })
        return {"title": f"{name}·记忆闪卡", "cards": cards}

    if kind == "infographic":
        section_names = ["先看结论", "理解结构", "走一遍过程", "检查边界", "三分钟回顾"]
        sections = [
            {
                "title": section_names[index] if index < len(section_names) else f"要点 {index + 1}",
                "body": excerpt,
                "source_index": index + 1 if index < len(chunks) else None,
            }
            for index, excerpt in enumerate(excerpts[:5])
        ]
        return {
            "title": f"一图看懂{name}",
            "summary": f"从定义、机制、步骤到边界，快速建立「{name}」的整体图景。",
            "sections": sections,
            "steps": ["认清对象", "抓住规则", "走完例子", "检查边界"],
        }

    rows = []
    for index, excerpt in enumerate(excerpts[:6]):
        rows.append([
            f"要点 {index + 1}",
            excerpt,
            "能否不用原文复述？" if index % 2 == 0 else "能否举出一个最小例子？",
        ])
    return {
        "title": f"{name}·知识数据表",
        "columns": ["对照项", "核心内容", "复习检查"],
        "rows": rows,
    }


def _normalize_structured(kind: str, value: object, name: str, chunks: list[dict]) -> dict:
    fallback = _fallback_structured(kind, name, chunks)
    if not isinstance(value, dict):
        return fallback
    if kind == "flashcards":
        cards = []
        for index, card in enumerate(value.get("cards") or []):
            if not isinstance(card, dict):
                continue
            front = _plain_excerpt(card.get("front", ""), 100)
            back = _plain_excerpt(card.get("back", ""), 260)
            if front and back:
                cards.append({
                    "id": str(card.get("id") or f"card-{index + 1}"),
                    "front": front,
                    "back": back,
                    "hint": _plain_excerpt(card.get("hint", ""), 100),
                    "source_index": card.get("source_index"),
                })
        return {"title": _plain_excerpt(value.get("title", ""), 80) or fallback["title"],
                "cards": cards[:10] or fallback["cards"]}
    if kind == "infographic":
        sections = []
        for section in value.get("sections") or []:
            if not isinstance(section, dict):
                continue
            title = _plain_excerpt(section.get("title", ""), 50)
            body = _plain_excerpt(section.get("body", ""), 220)
            if title and body:
                sections.append({"title": title, "body": body,
                                 "source_index": section.get("source_index")})
        steps = [_plain_excerpt(step, 40) for step in value.get("steps") or []]
        return {
            "title": _plain_excerpt(value.get("title", ""), 80) or fallback["title"],
            "summary": _plain_excerpt(value.get("summary", ""), 180) or fallback["summary"],
            "sections": sections[:6] or fallback["sections"],
            "steps": [step for step in steps if step][:6] or fallback["steps"],
        }
    columns = [_plain_excerpt(column, 40) for column in value.get("columns") or []]
    columns = [column for column in columns if column][:6]
    rows = []
    for row in value.get("rows") or []:
        if not isinstance(row, list):
            continue
        cells = [_plain_excerpt(cell, 220) for cell in row[:len(columns)]]
        if columns and any(cells):
            rows.append(cells + [""] * (len(columns) - len(cells)))
    return {
        "title": _plain_excerpt(value.get("title", ""), 80) or fallback["title"],
        "columns": columns or fallback["columns"],
        "rows": rows[:12] or fallback["rows"],
    }


async def _fit_one_page(name: str, markdown: str, request: str) -> str:
    """One bounded layout repair; final source checks still run on the result."""
    if map_plan(name, markdown) is not None:
        return markdown
    call = invoke_learning_prompt("doc.one_page_repair", base_request=request, draft=markdown)
    try:
        compact = await asyncio.wait_for(llm_complete(call.prompt, system=call.system, role="reasoner",
            temperature=0, max_tokens=1800, reasoning_mode="disabled", allow_mock_fallback=False), timeout=25)
        # Preserve every branch/request facet; never treat a reduced subset as success.
        headings = lambda text: re.findall(r"(?m)^##\s+(.+)$", text)
        if map_plan(name, compact) is not None and headings(compact) == headings(markdown):
            return compact
    except Exception:
        pass  # Rendering will honestly retain the full text when repair fails.
    return markdown


def _one_page_visual(name: str, chunks: list[dict], markdown: str) -> dict:
    excerpts = [
        _plain_excerpt(chunk.get("text", ""), 125)
        for chunk in chunks[:4]
        if _plain_excerpt(chunk.get("text", ""), 125)
    ]
    if not excerpts:
        paragraphs = [
            _plain_excerpt(part, 125)
            for part in re.split(r"\n\s*\n", markdown)
            if not part.lstrip().startswith("#") and _plain_excerpt(part, 125)
        ]
        excerpts = paragraphs[:4]
    return {
        "title": name,
        "center": name,
        "nodes": [
            {"label": f"资料摘录 {index + 1}", "text": excerpt}
            for index, excerpt in enumerate(excerpts[:4])
        ],
        "steps": [],
    }


def _unsupported_one_page_durations(markdown: str, chunks: list[dict]) -> list[str]:
    """A heading is still a claim: do not invent a source-backed time budget.

    This is a narrow deterministic check, alongside the semantic judge. It
    intentionally falls back to excerpts for unproven conversions/derivations.
    """
    pattern = r"[0-9零〇一二两三四五六七八九十百千万]+(?:\.[0-9]+)?\s*(?:毫秒|秒钟|分钟|小时|个月|秒|天|周|年)"
    def mentions(text: str) -> set[str]:
        return {re.sub(r"\s+", "", value) for value in re.findall(pattern, text)}
    source = "\n".join(str(chunk.get("text") or "") for chunk in chunks)
    return sorted(mentions(markdown) - mentions(source))


def _one_page_parts(markdown: str) -> list[str]:
    """Split dense maps at a section boundary, retaining every section."""
    explicit = re.search(r"(?m)^#{1,3}\s+0?2[.、：\s].*(?:应用|复习)", markdown)
    if explicit:
        return [markdown[:explicit.start()].strip(), markdown[explicit.start():].strip()]
    if len(markdown) <= 1800:
        return [markdown]
    boundaries = [m.start() for m in re.finditer(r"(?m)^#{1,3}\s+", markdown) if m.start() > 0]
    if not boundaries:
        return [markdown]
    split = min(boundaries, key=lambda index: abs(index - len(markdown) / 2))
    return [markdown[:split].strip(), markdown[split:].strip()]


def _one_page_image_prompt(name: str, markdown: str) -> str:
    """Render the source-grounded visual brief kept in the prompt catalog."""
    content = re.sub(r"\[\^\d+\]", "", str(markdown or ""))
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    if len(content) > 9000:
        content = content[:9000].rstrip() + "\n（内容已按图片文字预算截断，请只保留主干。）"
    return invoke_learning_prompt(
        "image.one_page",
        topic=name or "当前主题",
        content=content or "（没有可用于生图的正文，请输出清晰的资料不足提示。）",
    ).prompt


def _clean_source_excerpt(value: object, limit: int = 180) -> str:
    """Turn PDF/OCR fragments into readable learning notes instead of raw dumps."""
    text = without_source_code(value)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]", " ", text)
    text = re.sub(r"[\ue000-\uf8ff]", " ", text)
    text = re.split(r"(?:答案|参考答案|解析)\s*[:：]", text, maxsplit=1)[0]
    text = " ".join(text.split())
    if len(re.findall(r"(?:^|\s)[A-D][.、:：]", text, flags=re.IGNORECASE)) >= 2:
        text = re.split(r"(?:^|\s)A[.、:：]", text, maxsplit=1, flags=re.IGNORECASE)[0]
    parts = [part.strip(" -•\t") for part in re.split(r"(?<=[。！？；])", text)]
    readable = [
        part for part in parts
        if 8 <= len(part) <= 220
        and len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", part)) >= max(4, len(part) // 3)
    ]
    clean = "".join(readable[:2]).strip() or text.strip()
    return _compact(clean, limit)


def _content_on_topic(value: object, topic_name: str, kp: str) -> bool:
    """Reject successful-looking artifacts that silently changed topics."""

    raw = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
    output = re.sub(r"\s+", "", raw).lower()
    candidates = topic_terms(topic_name)
    if kp and kp != "custom_topic":
        candidates.append(str(kp).strip().lower())
    terms = {
        re.sub(r"\s+", "", candidate)
        for candidate in candidates
        if str(candidate or "").strip()
    }
    allowed = set(infer_kp_ids(str(topic_name or "")))
    if kp and kp != "custom_topic":
        allowed.add(kp)
    observed = set(infer_kp_ids(raw))
    if kp != "custom_topic" and observed - allowed:
        return False
    # A natural question is not a phrase the answer must repeat verbatim.
    # Match its course concepts and their aliases while rejecting a switch
    # to an unrelated concept (for example reading -> listening).
    if allowed & observed and not observed - allowed:
        return True
    return any(len(term) >= 2 and term in output for term in terms)


def _unexpected_topic_ids(
    value: object,
    topic_name: str,
    kp: str,
    chunks: list[dict],
) -> set[str]:
    """Find course topics present in one artifact item but absent from its scope."""

    # Broad source chapters may mention many other knowledge points. They are
    # evidence, not permission to leak those topics into the current item.
    allowed = set(infer_kp_ids(str(topic_name or "")))
    if kp and kp != "custom_topic":
        allowed.add(kp)
    raw = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
    return set(infer_kp_ids(raw)) - allowed


def _sanitize_structured_topics(
    kind: str,
    artifact: dict,
    topic_name: str,
    kp: str,
    chunks: list[dict],
) -> tuple[dict, bool, bool]:
    """Remove individual stale-topic cards/sections/rows, then safely backfill."""

    key = {"flashcards": "cards", "infographic": "sections", "data_table": "rows"}[kind]
    original = list(artifact.get(key) or [])
    clean = [
        item for item in original
        if not _unexpected_topic_ids(item, topic_name, kp, chunks)
    ]
    if len(clean) == len(original):
        return artifact, False, False

    fallback = _fallback_structured(kind, topic_name, chunks)
    fully_replaced = bool(original and not clean)
    target = min(len(original), 10 if kind != "infographic" else 6)
    for item in fallback.get(key) or []:
        if len(clean) >= target:
            break
        if item not in clean and not _unexpected_topic_ids(item, topic_name, kp, chunks):
            clean.append(item)
    sanitized = dict(artifact)
    sanitized["title"] = fallback["title"]
    sanitized[key] = clean or list(fallback.get(key) or [])
    if kind == "flashcards":
        sanitized["cards"] = [
            {**card, "id": f"card-{index + 1}"}
            for index, card in enumerate(sanitized["cards"])
        ]
    elif kind == "infographic":
        if _unexpected_topic_ids(sanitized.get("summary"), topic_name, kp, chunks):
            sanitized["summary"] = fallback["summary"]
        safe_steps = [
            step for step in (sanitized.get("steps") or [])
            if not _unexpected_topic_ids(step, topic_name, kp, chunks)
        ]
        sanitized["steps"] = safe_steps or fallback["steps"]
    return sanitized, True, fully_replaced


def _remediation_on_topic(markdown: str, topic_name: str, kp: str) -> bool:
    """Backward-compatible name for the topic gate used by older tests."""

    return _content_on_topic(markdown, topic_name, kp)


def _rag_fallback_doc(name: str, chunks: list[dict], kind: str) -> str:
    title = "原文导读" if kind == "doc" else "学习资料"
    lines = [
        f"# {name}·{title}",
        "",
        "> 完整讲解暂未生成成功，先阅读下面的来源原文，再尝试用自己的话复述。",
        "",
        "## 核心教材片段",
    ]
    if not chunks:
        lines += ["", "- 当前知识库没有检索到可用片段，请补充课程资料后重新生成。"]
    else:
        for i, chunk in enumerate(chunks[:5], 1):
            raw = str(chunk.get("text") or "")
            terms = topic_terms(name)
            paragraphs = [part.strip() for part in raw.splitlines() if part.strip()]
            selected: set[int] = set()
            for index, paragraph in enumerate(paragraphs):
                if any(term in re.sub(r"\s+", "", paragraph).casefold() for term in terms):
                    selected.add(index)
                    # Short plain-text headings need their explanatory paragraph.
                    if len(paragraph) < 40 and index + 1 < len(paragraphs):
                        selected.add(index + 1)
            excerpt = without_source_code("\n".join(paragraphs[j] for j in sorted(selected)) if selected else raw)
            excerpt = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]", "", excerpt).strip()
            if len(excerpt) > 1000:
                excerpt = excerpt[:1000].rstrip() + "…"
            if excerpt:
                lines.extend(f"> {line}" for line in excerpt.splitlines())
                lines.append(f"> [^{i}]\n")
    lines += [
        "",
        "## 学习建议",
        f"- 先按上面的教材片段梳理「{name}」的定义、关键关系与适用条件。",
        "- 用自己的话复述，再完成一道新题，核对概念区别。",
        "- 阅读后标出仍不理解的一步；稍后可重新生成完整讲解。",
    ]
    return "\n".join(lines)


def _conversation_fallback_doc(name: str, conversation: str, chunks: list[dict]) -> str:
    dialog_lines = [line.strip() for line in conversation.splitlines() if line.strip()]
    user_lines = [
        line.removeprefix("学习者：")
        for line in dialog_lines
        if line.startswith("学习者：") and not any(word in line for word in ("整理", "总结", "个人笔记"))
    ]
    assistant_lines = [line.removeprefix("小知：") for line in dialog_lines if line.startswith("小知：")]
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
        lines += [
            f"- {_clean_source_excerpt(chunk.get('text', ''), 220)} [^{index}]"
            for index, chunk in enumerate(chunks[:5], 1)
            if _clean_source_excerpt(chunk.get("text", ""), 220)
        ]
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
        "当前为离线安全版本；连接已配置的语言模型后会补全同主题讲解，也可以上传资料生成可引用版本。",
    ])


def _narration_text(name: str, markdown: str, limit: int = 900) -> str:
    text = re.sub(r"```.*?```", "", markdown, flags=re.S)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[\^\d+\]", "", text)
    text = re.sub(r"[#>*_`|~-]+", " ", text)
    text = _clean_source_excerpt(text, limit=max(limit - 16, 120))
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


def _ppt_query(name: str, goal: str, persona: str, context: str, *, source_bound: bool, conversation: str = "") -> str:
    scope = (
        "只允许使用下方所选资料与课程片段，不得补写资料外的事实。"
        if source_bound
        else "围绕当前主题使用可靠的通用知识，不得切换到其他课程或旧会话主题。"
    )
    material = without_source_code(context).strip() or "（本次没有选定资料，请紧扣当前主题制作基础复习版。）"
    return (
        f"请为学习者制作一份讲解完整、可独立复习的中文 PPT，通常约 8—12 页。\n"
        f"主题：{name}\n学习目标：{goal or f'复习{name}'}\n学习偏好：{persona}\n"
        f"约束：{scope} 不联网搜索；表达亲切、准确、适合学生复习；不展示源码、伪代码、函数定义、程序语句或系统实现信息，算法改写为白话步骤。\n"
        "教学要求：明确目标、概念与条件、完整例题与推理、易混概念对照、独立自测和答案解析；详细讲解写入演讲者备注。\n"
        f"最近学习对话（只用于保持学习焦点，不作为课程来源）：\n{without_source_code(conversation)}\n"
        f"可用学习资料：\n{material}"
    )


async def _gen_ppt_resource(
    *,
    name: str,
    kp: str,
    profile: dict,
    goal: str,
    chunks: list[dict],
    citations: list[dict],
    source_ids: list[str],
    trace_id: str,
    source_policy: str = "",
    conversation: str = "",
) -> dict:
    source_scope_missing = bool((source_ids or source_policy == "strict") and not chunks)
    flags: list[dict] = []
    if source_scope_missing:
        ppt = {
            "status": "blocked",
            "error": "当前选中的资料没有可检索内容，请更换资料后再生成复习 PPT。",
            "provider": "none",
        }
        flags.append({
            "agent": "doc",
            "kind": "ppt",
            "type": "source_scope_empty",
            "detail": "所选资料没有可检索内容，已阻止无依据生成 PPT",
        })
    else:
        context, ppt_citations = build_context(chunks)
        result = await multimodal_gateway.ppt_create(
            _ppt_query(
                name,
                goal,
                _persona(profile),
                context,
                source_bound=bool(chunks),
                conversation=conversation,
            ),
            trace_id=trace_id,
            citations=ppt_citations,
        )
        if result.get("ok"):
            ppt = dict(result.get("data") or {})
        else:
            error = str(result.get("error") or "PPT 服务暂时不可用")[:240]
            ppt = {"status": "failed", "error": error, "provider": str((result.get("data") or {}).get("provider") or "unavailable")}
            flags.append({
                "agent": "doc",
                "kind": "ppt",
                "type": "ppt_provider_error",
                "detail": error,
            })

    rid = uuid.uuid4().hex[:12]
    payload = {
        "template": "review_ppt",
        "explicit_only": True,
        "source_bound": bool(chunks),
        "ppt": ppt,
        "generation_mode": "unavailable" if ppt.get("status") in {"blocked", "failed"} else "model",
        "blocked_reason": "source_scope_empty" if source_scope_missing else "generation_failed" if ppt.get("status") == "failed" else "",
    }
    if ppt.get("cover_url"):
        payload["cover_url"] = ppt["cover_url"]
    resource = {
        "id": rid,
        "kind": "ppt",
        "kp": kp,
        "title": f"{name}·复习PPT",
        "payload": payload,
        "citations": [item["citation"] for item in citations[:5]],
    }
    await emit({"type": "resource", "resource": resource})
    if resource["citations"]:
        await emit({"type": "citations", "agent": "doc", "items": resource["citations"]})
    return {"resource": resource, "flags": flags}


async def _gen_structured_resource(
    *,
    kind: str,
    name: str,
    kp: str,
    profile: dict,
    goal: str,
    chunks: list[dict],
    citations: list[dict],
    source_ids: list[str],
    custom_topic: bool,
    source_policy: str = "",
) -> dict:
    label, capability = _STYLE[kind]
    source_scope_missing = bool((source_ids or source_policy == "strict") and not chunks)
    flags: list[dict] = []
    prompt_call = invoke_learning_prompt(
        capability,
        topic=name,
        goal=goal or f"复习{name}",
        persona=_persona(profile),
        context=build_context(chunks)[0] or "（没有检索到可用资料）",
        **({"source_rules": "仅使用当前自定义主题的通用知识，不混入旧会话主题。"}
           if custom_topic and not source_ids else {}),
    )
    if source_scope_missing:
        artifact = _fallback_structured(kind, name, [])
        artifact["blocked"] = True
        artifact["blocked_reason"] = "当前选中的资料没有可检索内容，请更换资料后重新生成。"
        flags.append({
            "agent": "doc",
            "kind": kind,
            "type": "source_scope_empty",
            "detail": "所选资料没有可检索内容，已阻止资料范围外生成",
        })
    elif (is_demo() and resolve(prompt_call.prompt) is None):
        artifact = _fallback_structured(kind, name, chunks)
    else:
        try:
            raw = await asyncio.wait_for(
                llm_complete(
                    prompt_call.prompt,
                    system=prompt_call.system,
                    role="reasoner",
                    temperature=0.35,
                    max_tokens=1600,
                    allow_mock_fallback=False,
                ),
                timeout=_DOC_TIMEOUT_S,
            )
            artifact = _normalize_structured(kind, parse_json(raw), name, chunks)
        except Exception as exc:  # noqa: BLE001
            artifact = _fallback_structured(kind, name, chunks)
            flags.append({
                "agent": "doc",
                "kind": kind,
                "type": "llm_fallback",
                "detail": f"结构化学习工件生成失败，已使用资料片段安全降级：{exc}",
            })
        else:
            artifact, removed_stale_items, fully_replaced = _sanitize_structured_topics(
                kind, artifact, name, kp, chunks,
            )
            if removed_stale_items:
                flags.append({
                    "agent": "doc",
                    "kind": kind,
                    "type": "topic_contamination",
                    "detail": f"{label}中夹带的旧知识点已逐项移除并按当前问题补齐",
                })
            if fully_replaced:
                flags.append({
                    "agent": "doc",
                    "kind": kind,
                    "type": "topic_drift",
                    "detail": f"{label}整体偏离当前问题「{name}」，已替换为同主题安全版本",
                })
            if not _content_on_topic(artifact, name, kp):
                artifact = _fallback_structured(kind, name, chunks)
                flags.append({
                    "agent": "doc",
                    "kind": kind,
                    "type": "topic_drift",
                    "detail": f"{label}未命中当前问题「{name}」，已替换为同主题安全版本",
                })

    rid = uuid.uuid4().hex[:12]
    payload = {
        kind: artifact,
        "generation_mode": "unavailable" if source_scope_missing else "source_guide" if flags else "model",
        "blocked_reason": "source_scope_empty" if source_scope_missing else "",
        "template": kind,
        "source_bound": bool(source_ids),
        "grounded": bool(chunks) or (custom_topic and not source_ids) or source_scope_missing,
        "prompt_skill": prompt_call.metadata(),
        "topic_label": name,
        "source_ids": source_ids,
        "source_evidence": citations[:6],
    }
    resource = {
        "id": rid,
        "kind": kind,
        "kp": kp,
        "title": f"{name}·{label}",
        "payload": payload,
        "citations": [item["citation"] for item in citations[:6]],
    }
    await emit({"type": "resource", "resource": resource})
    if resource["citations"]:
        await emit({"type": "citations", "agent": "doc", "items": resource["citations"]})
    return {"resource": resource, "flags": flags}


def _doc_label(default: str, template_key: str) -> str:
    return {
        "one_page": "一图看懂",
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
    user_id: str = "demo_user",
    skip_multimodal: bool = False,
    required_retrieval_terms: list[str] | None = None,
    source_policy: str = "",
) -> dict:
    name = topic_name or resolve_topic([kp])[1]
    label, capability = _STYLE.get(kind, _STYLE["doc"])
    if kind == "doc":
        label = _doc_label(label, prompt_template)
    interactive_audio = kind == "doc" and prompt_template == "interactive_audio"
    if interactive_audio:
        await emit({"type": "progress", "agent": "doc", "stage": "resource_content",
                    "text": "正在整理刚才的学习内容，生成短讲解…"})
    supplement = source_policy == "supplement" and kind == "doc" and prompt_template not in {"remediation", "conversation_notes", "question_review"}
    chunks = [] if custom_topic and not source_ids else retrieve(
        f"{goal}\n当前主题：{name}" if goal else name,
        final_k=8 if re.search(r"框架|总览|考点|占分|对比|比较", goal) else 5,
        source_ids=source_ids,
        # The course-library sentinel is selected by default in the UI.  Source
        # scoping and topic scoping are independent: uploaded chunks without a
        # kp tag remain eligible, while unrelated tagged course chunks are
        # rejected by the retriever.
        kp=None if custom_topic else kp,
        required_terms=required_retrieval_terms,
        user_id=user_id,
    )
    chunks = focus_chunks_on_topic(chunks, kp, name)
    if supplement:
        chunks.extend(supplemental_context(goal))
    ctx, citations = build_context(chunks)
    if kind in _STRUCTURED_KINDS:
        return await _gen_structured_resource(
            kind=kind,
            name=name,
            kp=kp,
            profile=profile,
            goal=goal,
            chunks=chunks,
            citations=citations,
            source_ids=source_ids,
            custom_topic=custom_topic,
            source_policy=source_policy,
        )
    if kind == "ppt":
        return await _gen_ppt_resource(
            name=name,
            kp=kp,
            profile=profile,
            goal=goal,
            chunks=chunks,
            citations=citations,
            source_ids=source_ids,
            trace_id=trace_id,
            source_policy=source_policy,
            conversation=conversation,
        )
    if kind == "doc":
        prompt_call = render_learning_prompt_call(
            prompt_template,
            topic=name,
            goal=goal,
            persona=_persona(profile),
            context=ctx,
            conversation=conversation,
            general_knowledge=custom_topic and not source_ids,
            source_policy="supplement" if supplement else "strict",
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
    demo_fallback = (is_demo() and resolve(prompt_call.prompt) is None)
    source_scope_missing = bool((source_ids or source_policy == "strict") and not chunks and not supplement)
    if source_scope_missing:
        fallback = True
        md = (
            f"# {name}·一图看懂未生成\n\n"
            "> 当前资料中未找到与这次问题相关的内容，尚未开始生成图片。\n\n"
            "请把问题写得更具体，或选择包含该主题的资料后重试。"
        ) if kind == "doc" and prompt_template == "one_page" else (
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
                    # Reasoning and final text share the completion budget.
                    # Notes already have a source-grounded teaching outline;
                    # reserve this bounded call for the actual explanation.
                    max_tokens=3200 if kind == "doc" else 1800,
                    reasoning_mode="disabled" if kind == "doc" else "",
                    # The generic offline completion is a fixed binary-tree
                    # sample. It is unsafe for a diagnosed remediation target
                    # because it can silently change the concept while keeping
                    # the current citations. Let the exception fall through to
                    # the target-scoped RAG fallback instead.
                    allow_mock_fallback=False,
                ),
                timeout=_DOC_TIMEOUT_S,
            )
            if not str(md or "").strip():
                from ..llm.failures import ModelFailure
                raise ModelFailure("empty_response")
        except Exception as exc:  # noqa: BLE001
            fallback = True
            remediation_rag_fallback = prompt_template == "remediation"
            conversation_fallback = kind == "doc" and prompt_template == "conversation_notes"
            md = (
                _conversation_fallback_doc(name, conversation, chunks)
                if conversation_fallback
                else _rag_fallback_doc(name, chunks, kind)
            )
            code = failure_code(exc)
            flags.append({"agent": "doc", "kind": kind, "type": "llm_fallback",
                          "reason_code": code, "detail": MESSAGES[code]})

    if kind == "doc" and prompt_template == "one_page" and not fallback:
        md = await _fit_one_page(name, md, prompt)

    notes_template = kind == "doc" and prompt_template in {"", "complete_notes", "conversation_notes"}
    if kind != "code" and not notes_template:
        md = without_source_code(md, keep_mermaid=True)

    if (kind == "doc" and not fallback and not source_scope_missing
            and not _content_on_topic(md, name, kp)):
        fallback = True
        remediation_rag_fallback = prompt_template == "remediation"
        conversation_fallback = prompt_template == "conversation_notes"
        md = (
            _conversation_fallback_doc(name, conversation, chunks)
            if conversation_fallback else _rag_fallback_doc(name, chunks, kind)
        )
        flags.append({
            "agent": "doc",
            "kind": kind,
            "type": "topic_drift",
            "detail": f"正文未命中当前问题「{name}」,已改用同主题安全版本",
        })

    if interactive_audio:
        await emit({"type": "progress", "agent": "doc", "stage": "resource_check",
                    "text": "正在检查讲解内容与资料范围…"})
    # Citation bounds are deterministic and independent of the semantic judge.
    citation_check = grounding_check_local(md, [c["text"] for c in chunks], allow_supplement=True)
    # 防幻觉第一层:答案-证据一致性(X2 深度推理)
    if source_scope_missing:
        ground = {"grounded": True, "unsupported": [], "verdict": "没有越过所选资料范围生成事实"}
    elif not fallback and not citation_check.get("accepted"):
        ground = citation_check
    elif supplement and not fallback:
        ground = citation_check
    elif custom_topic and not chunks:
        ground = {"grounded": True, "unsupported": [],
                  "verdict": "自定义主题使用模型通用知识生成，未声明虚构资料引用。"}
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
        ground = {"grounded": bool(chunks), "unsupported": [],
                  "verdict": "完整讲解未通过生成检查，当前展示来源原文导读。"}
    else:
        try:
            ground = await asyncio.wait_for(
                grounding_check(md, [c["text"] for c in chunks]),
                timeout=_GROUNDING_TIMEOUT_S,
            )
            ground["verification"] = "model_judge"
        except Exception as exc:  # noqa: BLE001
            ground = {"grounded": False, "unsupported": [],
                      "verdict": f"grounding 校验超时或失败:{exc}"}
            flags.append({"agent": "doc", "kind": kind, "type": "grounding_timeout",
                          "detail": ground["verdict"]})
    # Never deliver fabricated citations, including when no source was retrieved.
    invalid_citations = not fallback and not citation_check.get("accepted")
    if invalid_citations:
        flags.append({"agent": "doc", "kind": kind, "type": "invalid_citation",
                      "detail": "模型使用了不存在的资料引用，已拒绝该正文"})
        fallback = True
        md = _rag_fallback_doc(name, chunks, kind)
        ground = {"grounded": bool(chunks), "unsupported": [], "verdict": "无效引用正文已拒绝，仅保留可用资料"}
    unavailable = source_scope_missing or (fallback and not chunks and not demo_fallback
                                           and not (prompt_template == "conversation_notes" and conversation.strip()))
    if unavailable and not source_scope_missing:
        md = f"# {name}·未生成\n\n本次讲解未能生成可用正文，也没有可展示的相关资料。请重试，或选择相关资料后再生成。"
    one_page = kind == "doc" and prompt_template == "one_page"
    content_status = "supplemented" if supplement and chunks and not fallback else "general_knowledge" if not chunks else "checked"
    unsupported_durations = _unsupported_one_page_durations(md, chunks) if one_page and chunks and not supplement else []
    if one_page and chunks and (fallback or not (ground.get("grounded") or ground.get("accepted")) or "```" in md or unsupported_durations):
        flags.append({"agent": "doc", "kind": kind, "type": "one_page_source_excerpt",
                      "detail": "扩写未通过检查，改为本次检索资料的原文摘录",
                      "rejected_check": ground, "unsupported_durations": unsupported_durations})
        # Keep complete retrieved paragraphs, including negations and examples.
        # No summarizer, image model, truncation, or generic learning tips here.
        md = f"# {name}\n\n" + "\n\n".join(
            f"## 资料片段 {index}\n" + "\n".join(f"> {line}" for line in str(chunk['text']).splitlines()) + f"\n[^{index}]"
            for index, chunk in enumerate(chunks, 1)
        )
        fallback = True
        content_status = "source_excerpt"
        ground = {"grounded": True, "unsupported": [], "verdict": "直接引用本次检索片段，未采用未通过检查的扩写"}
    # 防幻觉第二层:内容安全过滤(本地词表 + 讯飞审核挂接)
    safety = safety_filter(md)
    if not unavailable and not ground.get("grounded", True) and not ground.get("accepted", False):
        flags.append({"agent": "doc", "kind": kind, "type": "grounding",
                      "detail": ground.get("verdict", ""), "unsupported": ground.get("unsupported", [])})
        md += "\n\n> ⚠️ 溯源提示:以上个别表述未在教材语料中找到直接依据,已标记供复核。"
    if not safety.get("safe", True):
        flags.append({"agent": "doc", "kind": kind, "type": "safety", "detail": safety.get("hits", [])})

    used = used_indices(md, len(citations))
    cite_used = [citations[i - 1] for i in used if 0 < i <= len(citations)]
    rid = uuid.uuid4().hex[:12]
    payload = {
        "markdown": md,
        "generation_mode": "unavailable" if unavailable else "demo" if demo_fallback else "source_guide" if fallback else "model",
        "blocked_reason": "source_scope_empty" if source_scope_missing else "generation_failed" if unavailable else "",
        "grounded": ground.get("grounded", True),
        "template": prompt_template,
        "reusable_note": prompt_template == "conversation_notes",
        "prompt_skill": prompt_call.metadata(),
        "topic_label": name,
        "source_ids": source_ids,
        "source_policy": "supplement" if supplement else "strict",
        "source_evidence": cite_used,
    }
    payload["verification"] = ground.get("verification", "source_excerpt" if fallback and chunks else "unverified")
    payload["generation_details"] = generation_details(flags, mode=payload["generation_mode"], source_empty=source_scope_missing)
    if notes_template or supplement:
        payload["notes_scope"] = (
            "本次资料优先，允许通用补充；补充部分未经资料逐项核验。" if supplement and chunks else
            f"本次依据 {len(chunks)} 个相关资料片段和可用对话整理，未对整份课件逐页核验。"
            if chunks else "本次没有可用的资料片段；内容依据可用对话或通用知识，不代表已核验课程原文。"
        )
    if one_page and not unavailable:
        payload["grounded"] = bool(chunks) and bool(ground.get("grounded"))
        payload["one_page_visual"] = _one_page_visual(name, chunks, md)
        try:
            payload["one_page_visual"].update(render_one_page(name, md, content_status=content_status))
        except Exception as exc:  # Keep source text accessible if local rendering fails.
            payload["one_page_visual"].update(image_status="fallback", image_error=str(exc)[:240])
            flags.append({"agent": "doc", "kind": kind, "type": "image_degraded", "detail": "知识图排版失败，已保留正文"})
    if interactive_audio:
        md = re.sub(
            r"口播脚本\s*[（(][^）)\n]*[）)]",
            "口播脚本（约 60—90 秒，以播放器实际时长为准）",
            md,
        )
        payload["markdown"] = md
    narration = _narration_text(name, md, limit=720 if interactive_audio else 320)
    if interactive_audio and not unavailable:
        payload["audio_narration"] = narration
    if (kind == "doc" and not unavailable
            and prompt_template not in {"conversation_notes", "one_page"} and not skip_multimodal):
        if interactive_audio:
            await emit({"type": "progress", "agent": "doc", "stage": "resource_audio",
                        "text": "正在生成语音，完成后即可边听边问…"})
        media_jobs = [multimodal_gateway.tts(narration, trace_id=trace_id)]
        # A decorative image can take minutes; it is not part of a spoken lesson.
        # Keep cover generation for the other document formats that use it.
        if not interactive_audio:
            media_jobs.append(multimodal_gateway.text_to_image(
                _cover_prompt(name, source_bound=bool(source_ids), custom_topic=custom_topic),
                width=768,
                height=768,
                trace_id=trace_id,
            ))
        media_results = await asyncio.gather(*media_jobs, return_exceptions=True)
        audio = media_results[0]
        cover = media_results[1] if len(media_results) > 1 else None
        if isinstance(audio, dict) and audio.get("ok"):
            payload["audio_url"] = audio["data"]["audio_url"]
            if interactive_audio:
                payload["audio"] = {
                    "status": "ready",
                    "provider": str(audio["data"].get("provider") or "spark_tts"),
                    "model": str(audio["data"].get("model") or ""),
                    "ai_generated": True,
                    "error": str(audio.get("error") or "")[:240],
                    "retryable": bool(audio.get("degraded")),
                    "degraded": bool(audio.get("degraded")),
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
            user_id=state.get("user_id", "demo_user"),
            skip_multimodal=skip_multimodal,
            required_retrieval_terms=required_retrieval_terms,
            source_policy=str(state.get("source_policy") or ""),
        )
        resources[out["resource"]["id"]] = out["resource"]
        flags += out["flags"]
    n_cite = sum(len(r["citations"]) for r in resources.values())
    await agent_end("doc", f"产出 {len(resources)} 份文本资源,共 {n_cite} 条引用,"
                           f"{'校验通过' if not flags else f'{len(flags)} 处待复核'}")
    return {"generated_resources": resources, "safety_flags": flags,
            "citations": [c for r in resources.values() for c in r["citations"]]}
