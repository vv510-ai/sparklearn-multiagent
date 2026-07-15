"""答疑导师智能体(Tutor Agent):多模态随问随答。
图片(拍照搜题)→ 讯飞 OCR 还原题面 → RAG 检索教材 → 流式逐 token 输出讲解
(启发式苏格拉底风格,先思路后答案)→ grounding 溯源 + 引用事件。"""
from __future__ import annotations

import asyncio
import base64

from ..config import is_demo
from ..llm import multimodal_gateway
from ..llm.spark_client import llm_stream
from ..prompt_templates import render_tutor_prompt
from ..rag.citation import build_context
from ..rag.retriever import retrieve
from ..safety.grounding import grounding_check
from ..safety.guard import safety_filter
from ..services.note_service import recent_note_chunks
from .emitter import agent_end, agent_start, agent_token, emit

def _build_prompt(
    question: str,
    profile: dict,
    context: str,
    source_ids: list[str],
    *,
    conversation: list[dict] | None = None,
    guided: bool = False,
) -> str:
    return render_tutor_prompt(
        question,
        profile,
        context,
        source_ids,
        conversation=conversation,
        guided=guided,
    ).prompt


def _rag_demo_answer(question: str, chunks: list[dict], *, guided: bool = False) -> str:
    lines = (
        [
            "## 一句话先懂",
            "",
            f"我们先把“{question}”拆成一个最容易理解的小目标：先认清对象，再看它怎么运作。",
            "",
            "## 从资料里抓重点",
            "",
        ]
        if guided
        else ["我先按当前资料给出可核对的结论：", ""]
    )
    for index, chunk in enumerate(chunks[:4], 1):
        text = " ".join(str(chunk.get("text") or "").split())
        if text:
            lines.append(f"- {text[:260]} [^{index}]")
    if not chunks:
        lines.append("当前知识库没有检索到可用片段，暂不补充资料外内容。")
    if guided:
        lines += [
            "",
            "## 生活里的它",
            "",
            "把学习这个知识点想成整理一只工具箱：先认清每件工具，再学使用顺序，最后检查什么场景不能用。",
            "",
            "## 最小例子",
            "",
            "先从资料中的第一条核心定义出发，自己画出或写出一个只包含 2—3 个元素的例子；再删掉一个元素，检查定义是否仍成立。",
            "",
            "## 一张小图",
            "",
            "```mermaid",
            "flowchart LR",
            "    A[先认对象] --> B[再看操作]",
            "    B --> C[用最小例子演示]",
            "    C --> D[检查边界和易错点]",
            "```",
            "",
            "## 记忆钩子",
            "",
            "**先认、再做、后查错。** 正式地说：先掌握定义，再理解操作流程，最后验证适用条件。",
            "",
            "## 接下来怎么练",
            "",
            "我已在下方准备基础练习卡。先自己作答，再根据解析定位还没理解的地方。",
        ]
    else:
        lines += ["", "你可以继续追问其中一个概念、步骤或易错点，我会沿用同一资料范围。"]
    return "\n".join(lines)

async def run(state: dict) -> dict:
    question = ""
    for m in reversed(state.get("messages") or []):
        if m.get("role") == "user":
            question = m.get("content", "")
            break
    extras = state.get("tutor_extras") or {}

    detail = "文本问答"
    if extras.get("image_base64"):                      # 拍照搜题
        try:
            img = base64.b64decode(extras["image_base64"].split(",")[-1])
            ocr = await multimodal_gateway.ocr_image(
                img,
                hint=question,
                purpose="tutor",
                trace_id=str(state.get("session_id", "")),
            )
            ocr_text = str(ocr["data"].get("text", ""))
            if ocr["ok"] and ocr_text:
                question = (question + "\n\n[图片题面] " + ocr_text).strip()
                detail = "OCR 识题 + 文本问答"
                await emit({"type": "progress", "agent": "tutor", "stage": "ocr",
                            "detail": "图片题面识别完成", "ocr": ocr_text[:120]})
            else:
                await emit({"type": "progress", "agent": "tutor", "stage": "ocr",
                            "percent": 100, "degraded": True,
                            "detail": "图片识别失败,已按文字问题继续作答"})
        except Exception as error:  # base64 输入异常也不得拖垮答疑
            await emit({"type": "progress", "agent": "tutor", "stage": "ocr",
                        "percent": 100, "degraded": True,
                        "detail": f"图片解析失败,已按文字问题继续作答:{str(error)[:80]}"})
    question = question or "请讲讲二叉树的中序遍历"
    await agent_start("tutor", "答疑导师智能体", detail)

    source_ids = [str(x) for x in (state.get("source_ids") or []) if str(x).strip()]
    chunks = retrieve(question, final_k=4, source_ids=source_ids)
    if not source_ids:
        chunks = [*chunks, *recent_note_chunks(state.get("user_id", "demo_user"), question, limit=2)]
    ctx, citations = build_context(chunks)
    if source_ids and not chunks:
        answer = "在你当前选中的资料中没有检索到可用内容，所以我没有补充资料之外的答案。请换一份资料，或检查上传文件是否已完成索引。"
        await agent_token("tutor", answer)
        await emit({"type": "token", "delta": answer})
        await emit({"type": "citations", "agent": "tutor", "items": []})
        await agent_end("tutor", "所选资料无可用片段,已阻止无依据回答")
        return {
            "answer": answer,
            "citations": [],
            "safety_flags": [{"agent": "tutor", "type": "source_scope_empty",
                              "detail": "所选资料没有可检索内容"}],
            "messages": [{"role": "assistant", "content": answer}],
        }
    profile = state.get("student_profile") or {}
    guided = bool(state.get("guided_learning") or state.get("intent") == "learn")
    prompt_call = render_tutor_prompt(
        question,
        profile,
        ctx,
        source_ids,
        conversation=state.get("conversation") or state.get("messages") or [],
        guided=guided,
    )
    prompt = prompt_call.prompt
    await emit({
        "type": "progress",
        "agent": "tutor",
        "stage": "prompt_skill",
        "percent": 100,
        "detail": f"已加载 {prompt_call.capability}（{prompt_call.version}）",
    })

    if is_demo():
        answer = _rag_demo_answer(question, chunks, guided=guided)
        for start in range(0, len(answer), 72):
            delta = answer[start:start + 72]
            await agent_token("tutor", delta)
            await emit({"type": "token", "delta": delta})
        ground = {"grounded": True, "unsupported": [], "verdict": "演示模式直接整理检索片段"}
    else:
        parts: list[str] = []
        try:
            async for delta in llm_stream(
                prompt,
                role="ultra",
                system=prompt_call.system,
                temperature=0.25 if guided else 0.45,
                max_tokens=2200 if guided else 1600,
                allow_model_fallback=not guided,
            ):
                parts.append(delta)
                await agent_token("tutor", delta)
                await emit({"type": "token", "delta": delta})
            answer = "".join(parts)
        except Exception as error:  # 所有模型不可用时仍保持资料内教学链路可用
            await emit({
                "type": "progress",
                "agent": "tutor",
                "stage": "fallback",
                "percent": 100,
                "degraded": True,
                "detail": f"模型暂不可用，已切换资料内讲解：{str(error)[:80]}",
            })
            answer = _rag_demo_answer(question, chunks, guided=guided)
            for start in range(0, len(answer), 72):
                delta = answer[start:start + 72]
                await agent_token("tutor", delta)
                await emit({"type": "token", "delta": delta})

        try:
            ground = await asyncio.wait_for(grounding_check(answer, [c["text"] for c in chunks]), timeout=8)
        except TimeoutError:
            ground = {"grounded": False, "unsupported": [], "verdict": "grounding 校验超时,已标记待复核"}
    safety = safety_filter(answer)
    flags = []
    if not ground.get("grounded", True):
        flags.append({"agent": "tutor", "type": "grounding", "detail": ground.get("verdict", "")})
        await emit({"type": "safety", "level": "warn",
                    "detail": "部分表述未命中教材依据,已提示复核"})
    if not safety.get("safe", True):
        flags.append({"agent": "tutor", "type": "safety", "detail": safety.get("hits", [])})

    cites = [c["citation"] for c in citations]
    await emit({"type": "citations", "agent": "tutor", "items": cites})
    await agent_end("tutor", f"已作答(约 {len(answer)} 字),引用教材 {len(cites)} 处,"
                             f"{'溯源通过' if ground.get('grounded', True) else '溯源提示复核'}")
    return {"answer": answer, "citations": cites, "safety_flags": flags,
            "messages": [{"role": "assistant", "content": answer}]}
