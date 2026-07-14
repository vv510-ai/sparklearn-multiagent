"""答疑导师智能体(Tutor Agent):多模态随问随答。
图片(拍照搜题)→ 讯飞 OCR 还原题面 → RAG 检索教材 → 流式逐 token 输出讲解
(启发式苏格拉底风格,先思路后答案)→ grounding 溯源 + 引用事件。"""
from __future__ import annotations

import asyncio
import base64

from ..config import is_demo
from ..llm import multimodal_gateway
from ..llm.spark_client import llm_stream
from ..rag.citation import build_context
from ..rag.retriever import retrieve
from ..safety.grounding import grounding_check
from ..safety.guard import safety_filter
from ..services.note_service import recent_note_chunks
from .emitter import agent_end, agent_start, agent_token, emit

_SYSTEM = (
    "你是《数据结构与算法》课程的 AI 导师「星火学伴」。你的首要任务不是显得专业，"
    "而是让零基础学习者真正听懂并能自己做题。先用日常语言，再引入术语；"
    "先给最小例子，再逐层增加难度。同一主题中的生活化类比要沿用同一个场景，"
    "并明确指出类比角色与知识概念的对应关系。适合结构、流程或因果关系时生成一个"
    "3—7 节点的 Mermaid 小图，图必须服务于理解。口诀、故事或谐音只能作为记忆钩子，"
    "随后必须还原为准确表述。严格区分一个概念与它的特殊类型：例如二叉树不等于"
    "二叉搜索树，前者本身没有大小顺序。类比只能帮助理解已有性质，不能凭空增加"
    "排序、方向、因果或数量关系。输出前逐条对照参考资料自检定义与边界。"
    "依据参考资料作答，事实性表述标注 [^n]；"
    "资料不足时明确说不知道，不能补写。对追问只解决当前卡点，不重复整篇教材。"
)


def _build_prompt(
    question: str,
    profile: dict,
    context: str,
    source_ids: list[str],
    *,
    conversation: list[dict] | None = None,
    guided: bool = False,
) -> str:
    source_scope = (
        "仅使用用户本次选中的知识库资料"
        if source_ids
        else "使用课程内置教材知识库和已沉淀的个人学习笔记"
    )
    dialog = "\n".join(
        f"{('用户' if item.get('role') == 'user' else '学伴')}: {str(item.get('content') or '').strip()}"
        for item in (conversation or [])[-10:]
        if str(item.get("content") or "").strip()
    ) or "（这是本主题的第一次交流）"
    mode_rules = (
        """
这是一次新主题的引导式学习，请严格按下面顺序输出：
## 一句话先懂
用一句没有专业术语的话说明它是什么、解决什么问题。
## 从资料里抓重点
只提炼 2—4 个最重要的点，每点先白话、后术语。
## 生活里的它
选一个熟悉的生活场景做连贯类比，并写明对应关系。
## 最小例子
给一个能手算、手推或在脑中演示的简单例子，再轻微变化一次说明边界。
## 一张小图
适合时给出 3—7 个节点的 Mermaid flowchart；不适合时用简短步骤代替。
## 记忆钩子
用一句顺口溜、关键词串联或小故事总结，然后还原正式说法。
## 接下来怎么练
告诉用户下方会出现基础练习卡，先作答再看解析。不要提前泄露练习答案。

第一轮禁止堆砌历史背景、复杂证明和未经解释的术语。后续追问再进入更深层。
""".strip()
        if guided
        else (
            "这是一次追问或答疑。先判断用户具体卡在哪里，沿用历史对话中已经建立的比喻，"
            "用最短路径解释清楚；如果用户给出了答案，先判断对错和错因，再补最小反例。"
        )
    )
    return (
        f"TASK=tutor\nMODE={'guided' if guided else 'followup'}\n"
        f"当前学习需求：\n{question}\n\n"
        f"学生画像：认知风格={profile.get('cognitive_style', '视觉型')},"
        f"难度偏好={profile.get('difficulty_pref', '循序渐进')},"
        f"学习节奏={profile.get('pace', '常规')}\n"
        f"资料范围：{source_scope}\n\n"
        f"最近学习对话：\n{dialog}\n\n"
        f"本轮教学方式：\n{mode_rules}\n\n"
        f"参考资料：\n{context or '(没有检索到可用片段)'}\n\n"
        "没有资料支持的事实不要补写；资料中的事实用 [^n] 标注对应编号。"
        "不要把当前主题偷换成更特殊的概念；类比、例子与图里的每个性质也必须能在资料中找到依据。"
    )


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
    prompt = _build_prompt(
        question,
        profile,
        ctx,
        source_ids,
        conversation=state.get("conversation") or state.get("messages") or [],
        guided=guided,
    )

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
                system=_SYSTEM,
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
