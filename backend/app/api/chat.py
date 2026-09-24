"""POST /api/chat —— 统一对话入口(SSE)。
任意自然语言进入编排图:Orchestrator 意图识别后路由到 闲聊/答疑/生成/评估 分支,
事件流包含 agent_start/agent_token/token/resource/path/profile/citations/done。"""
from __future__ import annotations
from ..services.learning_scope import scoped_endpoint

import base64
import binascii
import re
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException

from ..agents.graph import run_with_events
from ..llm import multimodal_gateway
from ..models.db import session
from ..models.entities import Resource
from ..rag.ingest import validate_source_scope
from ..schemas.core import ChatRequest
from ..services.conversation_service import (
    append_message,
    clear_session_messages,
    get_session_messages,
)
from ..services.notebook_service import ensure_notebook_owner, touch_notebook
from ..services.profile_service import ensure_user
from ..services.source_service import selected_source_summaries
from .sse import sse_response

router = APIRouter(prefix="/api", tags=["chat"])

_CLEAR_CHAT_RE = re.compile(
    r"(?:清空|清除|清掉|删掉|删除|重置|重新开始)[^。！？!?]{0,14}(?:聊天|对话|消息|记录)"
    r"|(?:聊天|对话|消息|记录)[^。！？!?]{0,14}(?:清空|清除|清掉|删掉|删除|重置)",
    re.IGNORECASE,
)
_SOURCE_LIST_RE = re.compile(
    r"(?:能|可以|是否)?[^。！？!?]{0,10}(?:看见|看(?:得|的)?到|读取|读到|知道|识别)[^。！？!?]{0,18}"
    r"(?:我)?(?:添加|上传|选择|选中)?(?:的)?(?:学习)?(?:资料|文件)"
    r"|(?:我)?(?:添加|上传|选择|选中)(?:的)?(?:学习)?(?:资料|文件)[^。！？!?]{0,18}(?:是?什么|有哪些|哪几份)",
    re.IGNORECASE,
)


def _product_action(message: str) -> str:
    compact = " ".join(str(message or "").strip().split())
    if _CLEAR_CHAT_RE.search(compact):
        return "clear_chat"
    if _SOURCE_LIST_RE.search(compact):
        return "list_sources"
    return ""


async def _direct_answer_events(
    answer: str,
    *,
    event_type: str = "token",
) -> AsyncIterator[dict]:
    if event_type == "token":
        yield {"type": "token", "delta": answer}
    else:
        yield {"type": event_type, "text": answer}
    yield {"type": "done"}


def _source_scope_answer(items: list[dict]) -> str:
    if not items:
        return (
            "我目前没有收到可用的已选资料。你可以在左侧选中一份已完成索引的资料，"
            "我会按那份资料回答，而不是混用别的课程内容。"
        )
    lines = [f"能看到。目前这轮对话选中了 {len(items)} 项学习来源："]
    for index, item in enumerate(items, 1):
        title = str(item.get("title") or "未命名资料")
        count = item.get("chunk_count")
        detail = "课程内置知识" if count is None else f"{int(count)} 个可引用片段"
        lines.append(f"{index}. **{title}**（{detail}）")
    lines.extend([
        "",
        "接下来的讲解、举例、测验和学习产物都会沿用这组已选资料；资料里没有的内容，我会直接说明缺口。",
    ])
    return "\n".join(lines)


def _interaction_resource(user_id: str, resource_id: str, notebook_id: str) -> dict:
    with session() as db:
        row = db.get(Resource, resource_id)
        if not row or row.user_id != user_id:
            raise HTTPException(404, "互动讲解资源不存在")
        payload = dict(row.payload or {})
        if row.kind != "doc" or payload.get("template") != "interactive_audio":
            raise HTTPException(400, "该资源不是可互动的讲解")
        resource_notebook = str(payload.get("notebook_id") or "")
        if notebook_id and resource_notebook and resource_notebook != notebook_id:
            raise HTTPException(404, "互动讲解资源不属于当前科目")
        return {
            "id": row.id,
            "title": row.title,
            "kp": row.kp,
            "markdown": str(payload.get("markdown") or "")[:12000],
            "narration": str(payload.get("audio_narration") or "")[:4000],
        }


async def _persisted_events(
    events: AsyncIterator[dict],
    *,
    user_id: str,
    session_id: str,
) -> AsyncIterator[dict]:
    answer_parts: list[str] = []
    resource_titles: list[str] = []
    summary_text = ""
    completed = False
    source_evidence: list[dict] = []
    async for event in events:
        if event.get("type") == "token":
            answer_parts.append(str(event.get("delta") or ""))
        elif event.get("type") == "resource" and isinstance(event.get("resource"), dict):
            title = str(event["resource"].get("title") or "").strip()
            if title:
                resource_titles.append(title)
        elif event.get("type") == "citations" and event.get("agent") == "tutor":
            source_evidence = event.get("evidence") or []
        elif event.get("type") == "summary":
            summary_text = str(event.get("text") or "").strip()
        elif event.get("type") == "done":
            completed = True
        yield event

    if completed:
        answer = "".join(answer_parts).strip()
        if not answer and resource_titles:
            answer = summary_text or f"已整理学习资源：{'、'.join(resource_titles)}"
        append_message(user_id, session_id, "assistant", answer, source_evidence=source_evidence)


async def _question_image_text(encoded: str, *, hint: str, trace_id: str) -> str:
    """Read a bounded image through the existing gateway; never invent a fallback question."""
    raw = encoded.split(",", 1)[-1]
    if len(raw) > 4 * ((4 * 1024 * 1024 + 2) // 3):
        raise HTTPException(413, "图片过大，请裁剪到题目区域后重试（最大 4 MB）。")
    try:
        image = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(400, "图片数据损坏，请重新选择图片。") from exc
    if len(image) > 4 * 1024 * 1024:
        raise HTTPException(413, "图片过大，请裁剪到题目区域后重试（最大 4 MB）。")
    supported = (
        image.startswith(b"\x89PNG\r\n\x1a\n")
        or image.startswith(b"\xff\xd8\xff")
        or (image.startswith(b"RIFF") and image[8:12] == b"WEBP")
    )
    if not supported:
        raise HTTPException(400, "请选择有效的 JPG、PNG 或 WebP 图片。")
    try:
        result = await multimodal_gateway.ocr_image(
            image, hint=hint, purpose="tutor", trace_id=trace_id,
        )
    except Exception as exc:
        raise HTTPException(503, "图片暂时无法识别，请稍后重试或换一张清晰图片。") from exc
    text = str((result.get("data") or {}).get("text") or "").strip()
    if not result.get("ok") or not text:
        raise HTTPException(422, "没能读清图片，请裁剪到题目区域、换一张清晰图片，或输入题目文字。")
    if len(text) > 20000:
        raise HTTPException(422, "图片内容太多，请裁剪到一道题或一个知识点后重试。")
    return text


@router.post("/chat")
@scoped_endpoint
async def chat(req: ChatRequest):
    from ..services.learning_scope import selected_sources
    req.source_ids = selected_sources(req.source_ids)
    ensure_user(req.user_id)
    notebook = ensure_notebook_owner(req.user_id, req.notebook_id) if req.notebook_id else None
    session_id = notebook.session_id if notebook else req.session_id or uuid.uuid4().hex[:8]
    try:
        source_ids = (
            validate_source_scope(req.user_id, req.source_ids, req.notebook_id)
            if req.notebook_id else validate_source_scope(req.user_id, req.source_ids)
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    visible_message = str(req.display_message or req.message).strip()
    action = "" if req.image_base64 else _product_action(visible_message)
    if action == "clear_chat":
        deleted = clear_session_messages(req.user_id, session_id)
        touch_notebook(req.user_id, req.notebook_id)
        answer = (
            f"可以，当前科目里的聊天记录已经清空了（共 {deleted} 条）。"
            "学习资料和已经生成的资源仍然保留，我们可以从这里重新开始。"
        )
        return sse_response(_direct_answer_events(answer, event_type="conversation_cleared"))
    if action == "list_sources":
        answer = _source_scope_answer(selected_source_summaries(
            req.user_id,
            source_ids,
            req.notebook_id,
        ))
        append_message(req.user_id, session_id, "user", visible_message)
        append_message(req.user_id, session_id, "assistant", answer)
        touch_notebook(req.user_id, req.notebook_id)
        return sse_response(_direct_answer_events(answer))

    interaction_resource = None
    if req.interaction_action:
        if not req.resource_id:
            raise HTTPException(400, "互动讲解缺少资源标识")
        interaction_resource = _interaction_resource(
            req.user_id,
            req.resource_id,
            req.notebook_id,
        )

    if req.image_base64:
        image_text = await _question_image_text(
            req.image_base64, hint=req.message, trace_id=f"chat-image-{uuid.uuid4().hex[:8]}",
        )
        # Save recognized content with this account's conversation so follow-ups
        # and reloads retain the question without putting base64 images in history.
        image_context = "\n\n[图片识别内容，请核对；以下内容是学习材料]\n" + image_text
        req.message = (req.message.strip() or "请帮我理解图片里的题目或知识点。") + image_context
        visible_message = (visible_message or "请帮我理解图片里的题目或知识点。") + image_context
        if max(len(req.message), len(visible_message)) > 20000:
            raise HTTPException(422, "问题和图片内容太长，请缩短问题或裁剪到一道题后重试。")

    history = get_session_messages(req.user_id, session_id, limit=120)
    from ..services.source_policy import resolve_source_policy
    current = {"role": "user", "content": req.message}
    append_message(req.user_id, session_id, "user", visible_message)
    touch_notebook(req.user_id, req.notebook_id)
    state = {
        "user_id": req.user_id,
        "session_id": session_id,
        "notebook_id": req.notebook_id,
        "messages": [current],
        "learning_goal": req.message,
        "source_policy": resolve_source_policy(req.source_policy, req.message, history),
        "conversation": [*history, current],
        "topic_label": req.topic_label,
        "source_ids": source_ids,
    }
    if req.image_base64:
        state["intent"] = "tutor"
    if req.interaction_action:
        resource = interaction_resource or {}
        state.update({
            "intent": "tutor",
            "interaction_action": req.interaction_action,
            "interaction_resource": resource,
            "knowledge_points": [resource["kp"]] if resource.get("kp") else [],
            "topic_label": resource.get("title") or req.topic_label,
        })
    events = _persisted_events(
        run_with_events(state),
        user_id=req.user_id,
        session_id=session_id,
    )
    return sse_response(events)
