"""答疑导师智能体(Tutor Agent):多模态随问随答。
图片(拍照搜题)→ 讯飞 OCR 还原题面 → RAG 检索教材 → 流式逐 token 输出讲解
(启发式苏格拉底风格,先思路后答案)→ grounding 溯源 + 引用事件。"""
from __future__ import annotations

import asyncio
import base64
import re

from ..config import is_demo
from ..llm import multimodal_gateway
from ..llm.spark_client import llm_stream
from ..prompt_templates import render_tutor_prompt
from ..rag.citation import build_context, used_indices
from ..rag.retriever import retrieve
from ..safety.grounding import grounding_check
from ..safety.guard import safety_filter
from ..services.knowledge_graph import canonical_kp_id, infer_kp_id, kp_retrieval_text
from ..services.note_service import recent_note_chunks
from .emitter import agent_end, agent_start, agent_token, emit


_SMALL_TALK_RE = re.compile(
    r"^(?:你好|您好|嗨|哈喽|hello|hi|hey|在吗|谢谢|感谢|再见|拜拜)[!！?？。,.，]*$",
    re.IGNORECASE,
)
_HELP_MARKERS = ("你能做什么", "可以做什么", "怎么用", "如何使用", "使用说明", "help")


def _needs_retrieval(question: str, *, guided: bool = False, has_image: bool = False) -> bool:
    """Only skip retrieval for deterministic small-talk and product-help turns."""

    if guided or has_image:
        return True
    compact = re.sub(r"\s+", "", str(question or "")).strip().lower()
    if not compact:
        return False
    if _SMALL_TALK_RE.fullmatch(compact):
        return False
    if len(compact) <= 24 and any(marker in compact for marker in _HELP_MARKERS):
        return False
    return True


def _lightweight_chat_answer(question: str) -> str:
    compact = re.sub(r"\s+", "", str(question or "")).lower()
    if any(marker in compact for marker in ("谢谢", "感谢")):
        return "不客气。你可以继续追问当前知识点，或选中一份资料让我按资料范围讲解、出题和整理笔记。"
    if any(marker in compact for marker in ("再见", "拜拜")):
        return "下次见。已经形成的学习笔记可以继续作为后续复习资料。"
    if any(marker in compact for marker in _HELP_MARKERS):
        return "你可以先选择学习资料，再让我从零讲解、针对卡点答疑、生成练习，最后把本次对话整理成可复用笔记。"
    return "你好，我是星火学伴。你可以选中资料后问一个具体问题，或者直接说“从零学习某个主题”。"


def _retrieval_evidence(
    question: str,
    source_ids: list[str],
    chunks: list[dict],
    *,
    needed: bool,
    reason: str,
    knowledge_point: str | None = None,
) -> dict:
    """Build trace evidence without copying retrieved source text into events."""

    items = []
    for chunk in chunks[:6]:
        items.append({
            "chunk_id": chunk.get("chunk_id") or chunk.get("id"),
            "source_id": chunk.get("source_id"),
            "source": chunk.get("source"),
            "chapter": chunk.get("chapter"),
            "page": chunk.get("page"),
            "score": chunk.get("rerank_score", chunk.get("score")),
            "citation": chunk.get("citation"),
        })
    return {
        "needed": needed,
        "reason": reason,
        "query": str(question or "")[:240],
        "source_ids": source_ids,
        "knowledge_point": knowledge_point,
        "count": len(chunks),
        "chunks": items,
    }


def _focused_kp_chunks(chunks: list[dict], kp: str | None, limit: int = 4) -> list[dict]:
    """Prefer chunks narrowly tagged to the planned concept over broad guide pages."""
    if not kp:
        return chunks[:limit]
    specific: list[dict] = []
    matching: list[dict] = []
    for chunk in chunks:
        values = [value.strip() for value in str(chunk.get("kp") or "").split(",") if value.strip()]
        if kp not in values:
            continue
        matching.append(chunk)
        if len(values) <= 3:
            specific.append(chunk)
    return (specific or matching or chunks)[:limit]

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
    compact_question = re.sub(r"\s+", "", question)
    graph_definition_cite = next(
        (
            index for index, chunk in enumerate(chunks[:4], 1)
            if "G=(V,E)" in str(chunk.get("text") or "")
            and "顶点集合" in str(chunk.get("text") or "")
        ),
        None,
    )
    asks_graph_definition = bool(
        re.search(r"(?:^图是什么|什么是图[？?。！!]*$|图的定义)", compact_question)
    )
    if not guided and asks_graph_definition and graph_definition_cite:
        return (
            "图是一种描述“对象以及对象之间关系”的非线性数据结构，通常写成 "
            f"**G=(V,E)**：V 是顶点集合，E 是连接顶点的边集合 [^{graph_definition_cite}]。\n\n"
            "按边的特点，图可以分为有向图/无向图、带权图/无权图。"
            "存储时常用邻接矩阵或邻接表；前者适合稠密图，后者适合稀疏图。"
        )
    traversal = next((name for name in ("前序", "中序", "后序", "层序") if name in compact_question), "")
    traversal_order = {
        "前序": ("根 → 左 → 右", "先看当前节点，再走左子树，最后走右子树", "A → B → C"),
        "中序": ("左 → 根 → 右", "先走左子树，再看当前节点，最后走右子树", "B → A → C"),
        "后序": ("左 → 右 → 根", "先走左右子树，最后回到当前节点", "B → C → A"),
        "层序": ("从上到下、从左到右", "先访问离根近的节点，再逐层向下", "A → B → C"),
    }.get(traversal)
    traversal_cite = next(
        (index for index, chunk in enumerate(chunks[:4], 1)
         if traversal and traversal in str(chunk.get("text") or "")),
        next((index for index, chunk in enumerate(chunks[:4], 1)
              if "遍历" in str(chunk.get("text") or "")), None),
    )

    if guided and traversal_order and traversal_cite:
        order, plain, result = traversal_order
        return "\n".join([
            "## 一句话先懂",
            "",
            f"{traversal}遍历就是：{plain}。记成 **{order}**。 [^{traversal_cite}]",
            "",
            "## 最小例子",
            "",
            "```text",
            "    A",
            "   / \\",
            "  B   C",
            "```",
            "",
            f"按 **{order}** 依次访问，结果是：**{result}**。",
            "",
            "## 手走一遍",
            "",
            f"1. 从根节点 A 开始，严格按“{order}”判断下一步。",
            "2. 每访问一个节点就立刻写下字母，不要等走完再回忆。",
            f"3. 最后检查结果是否为 **{result}**。",
            "",
            "## 记忆钩子",
            "",
            f"**{traversal} = {order}。** “根”出现在哪里，就是当前节点什么时候被记录。",
            "",
            "## 接下来怎么练",
            "",
            "先完成下方基础练习卡；答错时只回到“访问当前节点的时机”这一点，不扩展到别的树结构。",
        ])

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


async def _emit_answer(answer: str) -> None:
    for start in range(0, len(answer), 72):
        delta = answer[start:start + 72]
        await agent_token("tutor", delta)
        await emit({"type": "token", "delta": delta})


async def run(state: dict) -> dict:
    question = ""
    for m in reversed(state.get("messages") or []):
        if m.get("role") == "user":
            question = m.get("content", "")
            break
    extras = state.get("tutor_extras") or {}

    detail = "文本问答"
    has_image = bool(extras.get("image_base64"))
    if has_image:                                      # 拍照搜题
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
    guided = bool(state.get("guided_learning") or state.get("intent") == "learn")
    if not _needs_retrieval(question, guided=guided, has_image=has_image):
        retrieval = _retrieval_evidence(
            question,
            source_ids,
            [],
            needed=False,
            reason="small_talk_or_product_help",
        )
        await emit({
            "type": "progress",
            "agent": "tutor",
            "stage": "retrieval",
            "percent": 100,
            "detail": "轻量对话无需检索资料",
            "retrieval": retrieval,
        })
        answer = _lightweight_chat_answer(question)
        await agent_token("tutor", answer)
        await emit({"type": "token", "delta": answer})
        await emit({"type": "citations", "agent": "tutor", "items": []})
        await agent_end(
            "tutor",
            "轻量对话直接响应,未触发 RAG",
            {"retrieval": retrieval, "grounding": {"status": "not_required"}},
        )
        return {
            "answer": answer,
            "citations": [],
            "safety_flags": [],
            "messages": [{"role": "assistant", "content": answer}],
        }

    knowledge_points = [str(item).strip() for item in (state.get("knowledge_points") or []) if str(item).strip()]
    planned_kp = canonical_kp_id(knowledge_points[0]) if knowledge_points else None
    retrieval_kp = None if source_ids else (planned_kp or infer_kp_id(question))
    retrieval_query = question
    if retrieval_kp:
        retrieval_query = f"{question}\n课程知识点：{kp_retrieval_text(retrieval_kp)}"
    chunks = retrieve(
        retrieval_query,
        final_k=8 if retrieval_kp else 4,
        source_ids=source_ids,
        kp=retrieval_kp,
    )
    chunks = _focused_kp_chunks(chunks, retrieval_kp)
    if not source_ids and not guided:
        chunks = [
            *chunks,
            *recent_note_chunks(
                state.get("user_id", "demo_user"),
                question,
                limit=2,
                knowledge_point=retrieval_kp,
            ),
        ]
    retrieval = _retrieval_evidence(
        question,
        source_ids,
        chunks,
        needed=True,
        reason="guided_or_knowledge_question",
        knowledge_point=retrieval_kp,
    )
    await emit({
        "type": "progress",
        "agent": "tutor",
        "stage": "retrieval",
        "percent": 100,
        "detail": f"检索完成,命中 {len(chunks)} 个片段",
        "retrieval": retrieval,
    })
    ctx, citations = build_context(chunks)
    if source_ids and not chunks:
        answer = "在你当前选中的资料中没有检索到可用内容，所以我没有补充资料之外的答案。请换一份资料，或检查上传文件是否已完成索引。"
        await agent_token("tutor", answer)
        await emit({"type": "token", "delta": answer})
        await emit({"type": "citations", "agent": "tutor", "items": []})
        await agent_end(
            "tutor",
            "所选资料无可用片段,已阻止无依据回答",
            {"retrieval": retrieval, "grounding": {"status": "blocked_no_source"}},
        )
        return {
            "answer": answer,
            "citations": [],
            "safety_flags": [{"agent": "tutor", "type": "source_scope_empty",
                              "detail": "所选资料没有可检索内容"}],
            "messages": [{"role": "assistant", "content": answer}],
        }
    profile = state.get("student_profile") or {}
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
        "prompt_skill": prompt_call.metadata(),
    })

    grounding_fallback_reason = ""
    if is_demo():
        await emit({
            "type": "progress",
            "agent": "tutor",
            "stage": "fallback",
            "percent": 100,
            "degraded": True,
            "reason": "demo_mode",
            "detail": "演示模式使用确定性资料整理回答",
        })
        answer = _rag_demo_answer(question, chunks, guided=guided)
        ground = {"grounded": True, "unsupported": [], "verdict": "演示模式直接整理检索片段"}
    else:
        parts: list[str] = []
        model_answer = True
        try:
            async for delta in llm_stream(
                prompt,
                role="ultra",
                system=prompt_call.system,
                temperature=0.25 if guided else 0.45,
                max_tokens=2200 if guided else 1600,
                allow_model_fallback=not guided,
                allow_mock_fallback=False,
            ):
                parts.append(delta)
            answer = "".join(parts)
        except Exception as error:  # 所有模型不可用时仍保持资料内教学链路可用
            model_answer = False
            await emit({
                "type": "progress",
                "agent": "tutor",
                "stage": "fallback",
                "percent": 100,
                "degraded": True,
                "reason": "llm_unavailable",
                "error": str(error)[:160],
                "detail": f"模型暂不可用，已切换资料内讲解：{str(error)[:80]}",
            })
            answer = _rag_demo_answer(question, chunks, guided=guided)

        if model_answer:
            try:
                ground = await asyncio.wait_for(
                    grounding_check(answer, [c["text"] for c in chunks]),
                    timeout=8,
                )
            except TimeoutError:
                ground = {
                    "grounded": False,
                    "unsupported": [],
                    "verdict": "grounding 校验超时",
                }
            if not ground.get("grounded", False):
                grounding_fallback_reason = str(ground.get("verdict") or "存在资料外表述")
                failed_grounding = {
                    "grounded": False,
                    "unsupported_count": len(ground.get("unsupported") or []),
                    "verdict": grounding_fallback_reason,
                }
                await emit({
                    "type": "progress",
                    "agent": "tutor",
                    "stage": "grounding",
                    "percent": 100,
                    "detail": "模型回答未通过资料溯源,不会展示原回答",
                    "grounding": failed_grounding,
                })
                await emit({
                    "type": "progress",
                    "agent": "tutor",
                    "stage": "fallback",
                    "percent": 100,
                    "degraded": True,
                    "reason": "grounding_failed",
                    "detail": f"已替换为资料内确定性讲解：{grounding_fallback_reason[:100]}",
                })
                answer = _rag_demo_answer(question, chunks, guided=guided)
                ground = {
                    "grounded": True,
                    "unsupported": [],
                    "verdict": "原回答未通过溯源,已替换为资料片段整理",
                }
        else:
            ground = {
                "grounded": True,
                "unsupported": [],
                "verdict": "模型不可用,已直接整理检索片段",
            }

    # Only stream the final answer after grounding and content-safety checks.
    safety = safety_filter(answer)
    if not safety.get("passed", safety.get("safe", True)):
        answer = str(safety.get("text") or answer)
        await emit({"type": "safety", "level": "warn", "detail": "命中内容安全规则,已在展示前脱敏"})
    await _emit_answer(answer)
    grounding = {
        "grounded": bool(ground.get("grounded", False)),
        "unsupported_count": len(ground.get("unsupported") or []),
        "verdict": ground.get("verdict", ""),
    }
    await emit({
        "type": "progress",
        "agent": "tutor",
        "stage": "grounding",
        "percent": 100,
        "detail": "资料溯源通过" if grounding["grounded"] else "资料溯源需要复核",
        "grounding": grounding,
    })
    flags = (
        [{"agent": "tutor", "type": "grounding_fallback", "detail": grounding_fallback_reason}]
        if grounding_fallback_reason else []
    )
    if not ground.get("grounded", True):
        flags.append({"agent": "tutor", "type": "grounding", "detail": ground.get("verdict", "")})
        await emit({"type": "safety", "level": "warn",
                    "detail": "部分表述未命中教材依据,已提示复核"})
    if not safety.get("passed", safety.get("safe", True)):
        flags.append({"agent": "tutor", "type": "safety", "detail": safety.get("hits", [])})

    cited_indices = used_indices(answer, len(citations))
    cites = [citations[index - 1]["citation"] for index in cited_indices]
    await emit({"type": "citations", "agent": "tutor", "items": cites})
    await agent_end(
        "tutor",
        f"已作答(约 {len(answer)} 字),引用教材 {len(cites)} 处,"
        f"{'溯源通过' if ground.get('grounded', True) else '溯源提示复核'}",
        {
            "prompt_skill": prompt_call.metadata(),
            "retrieval": retrieval,
            "grounding": grounding,
        },
    )
    return {"answer": answer, "citations": cites, "safety_flags": flags,
            "messages": [{"role": "assistant", "content": answer}]}
