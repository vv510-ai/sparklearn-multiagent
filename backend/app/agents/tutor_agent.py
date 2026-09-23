"""答疑导师智能体(Tutor Agent):多模态随问随答。
图片(拍照搜题)→ 讯飞 OCR 还原题面 → RAG 检索教材 → 流式逐 token 输出讲解
(启发式苏格拉底风格,先思路后答案)→ grounding 溯源 + 引用事件。"""
from __future__ import annotations

from ..services.model_preferences import resolve

import base64
import json
import re

from ..config import is_demo
from ..llm import multimodal_gateway
from ..llm.failures import failure_code, MESSAGES
from ..llm.spark_client import llm_stream
from ..prompt_templates import render_tutor_prompt
from ..rag.citation import build_context, used_indices
from ..rag.retriever import retrieve
from ..safety.grounding import grounding_check, grounding_check_local
from ..safety.guard import safety_filter
from ..services.knowledge_graph import infer_kp_ids, kp_retrieval_text, resolve_conversation_topic
from ..services.source_policy import allows_supplement
from ..services.learning_context import supplemental_context
from ..services.note_service import recent_note_chunks
from ..services.topic_scope import focus_chunks_on_topic
from .emitter import agent_end, agent_start, agent_token, emit
from .orchestrator import is_draft_feedback


_SMALL_TALK_RE = re.compile(
    r"^(?:你好|您好|嗨|哈喽|hello|hi|hey|在吗|谢谢|感谢|再见|拜拜)[!！?？。,.，]*$",
    re.IGNORECASE,
)
_OUT_OF_COURSE_SQL_RE = re.compile(
    r"(?:\bSQL\b|\bSELECT\b|\bWHERE\b|\bGROUP\s+BY\b|\bORDER\s+BY\b|\bJOIN\b|多表连接|数据库查询)",
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
    help_question = compact.strip("!！?？。,.，")
    if help_question in _HELP_MARKERS or re.fullmatch(
        r"(?:请问)?(?:这个(?:软件|网站|系统)|学习机|星火学伴|learnloop|sparklearn)(?:怎么用|如何使用|使用说明)",
        help_question,
    ):
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
    return "你好，我是小知。你可以选中资料后问一个具体问题，或者直接说“从零学习某个主题”。"


def _is_short_definition_question(question: str) -> bool:
    compact = re.sub(r"\s+", "", str(question or ""))
    return len(compact) <= 24 and bool(
        re.search(r"(?:^什么是.+|.+是什么[？?。！!]*$|.+的定义[是？?。！!]*$)", compact)
    )


def _normalize_tutor_answer(answer: str, question: str, *, has_context: bool) -> str:
    """把模型误输出的 JSON 自检表还原成面向学习者的直接回答。"""
    text = str(answer or "").strip()
    prompt_markers = (
        "TASK=tutor",
        "MODE=",
        "当前问题：",
        "学习者画像：",
        "资料范围：",
        "最近学习对话：",
        "教学策略：",
        "输出自检：",
    )
    # 小模型在长提示词下偶尔会原样复述内部模板。内部提示不是教学
    # 内容，宁可触发下方的安全降级，也不能把它展示给学习者。
    if sum(marker in text for marker in prompt_markers) >= 2:
        return ""
    if not _is_short_definition_question(question):
        return text

    candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        data = json.loads(candidate)
    except (TypeError, ValueError):
        data = None
    if isinstance(data, dict):
        for key in ("是什么", "定义", "结论", "answer"):
            value = str(data.get(key) or "").strip()
            if value:
                text = value
                break

    if has_context and text and not re.search(r"\[\^\d+\]", text):
        text = f"{text} [^1]"
    return text


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
            "vector_score": chunk.get("vector_score"),
            "lexical_score": chunk.get("lexical_score"),
            "rerank_mode": chunk.get("rerank_mode"),
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


def _beginner_first_chunks(chunks: list[dict]) -> list[dict]:
    """Put definitions and basic concepts before advanced variants in guided turns."""
    basic_markers = ("基本概念", "定义", "是什么", "最多", "至多", "节点", "入门")
    advanced_markers = ("红黑", "平衡因子", "复杂度证明", "线索化", "最优", "摊还")

    def score(item: tuple[int, dict]) -> tuple[int, int]:
        index, chunk = item
        text = " ".join(
            str(chunk.get(key) or "")
            for key in ("chapter", "title", "text")
        )
        priority = sum(marker in text for marker in basic_markers)
        priority -= 2 * sum(marker in text for marker in advanced_markers)
        return (-priority, index)

    return [chunk for _, chunk in sorted(enumerate(chunks), key=score)]


def _resolve_turn_topic(state: dict, question: str) -> tuple[str, str, bool]:
    """Resolve the current turn without permanently binding a conversation to its opening topic."""
    interaction_resource = state.get("interaction_resource") or {}
    if interaction_resource:
        return resolve_conversation_topic(
            str(interaction_resource.get("title") or question),
            [],
            knowledge_points=[str(interaction_resource.get("kp") or "")],
            topic_label=str(interaction_resource.get("title") or ""),
        )
    return resolve_conversation_topic(
        question,
        state.get("conversation"),
        knowledge_points=state.get("knowledge_points"),
        topic_label=state.get("topic_label"),
    )


def _interaction_request(action: str, question: str, resource_title: str) -> str:
    instructions = {
        "rephrase": (
            "把刚才讲解的同一个核心点真正换一种说法：不得复述原句；先用更口语的白话，"
            "再换一个全新的贴切类比，最后用一句正式表述把含义校准。控制在 180—320 字。"
        ),
        "example": (
            "只举一个具体、可跟着走的最小例子。必须逐步指出例子中的对象分别对应概念里的什么，"
            "最后说明这个例子能证明什么、不能推出什么。控制在 180—320 字。"
        ),
        "quiz": (
            "只出一道能够检查刚才核心理解的问题。不要给答案、提示或解析；题目后只说“你先回答，我再帮你判断”。"
            "题目必须能由刚才讲解和所选资料直接回答。"
        ),
        "question": "直接回答学习者在播放中提出的具体问题，先解决卡点，再补最少的必要解释。",
    }
    instruction = instructions.get(action, instructions["question"])
    return (
        f"这是对互动讲解《{resource_title}》的资源级追问。\n"
        f"动作要求：{instruction}\n"
        f"学习者原始请求：{question}"
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
    return render_tutor_prompt(
        question,
        profile,
        context,
        source_ids,
        conversation=conversation,
        guided=guided,
    ).prompt


def _is_learning_strategy_question(question: str) -> bool:
    compact = re.sub(r"\s+", "", str(question or ""))
    return bool(re.search(
        r"(?:怎么学|如何学|怎么开始|如何开始|从哪(?:里)?学|从哪(?:里)?开始|入门|学习顺序|学习路线|学习路径|学习计划)",
        compact,
    ))


def _is_binary_tree_first_lesson(question: str, topic_kp: str, *, guided: bool) -> bool:
    compact = re.sub(r"\s+", "", str(question or ""))
    return bool(
        topic_kp == "binary_tree"
        and (
            len(compact) <= 8
            or re.search(r"(?:二叉树是什么|什么是二叉树)", compact)
            or (
                guided
                and re.search(r"(?:从零|刚开始学|入门|初学)", compact)
            )
        )
    )


def _strategy_answer(topic_name: str) -> str:
    topic = str(topic_name or "这个主题").strip() or "这个主题"
    if "数据结构" in topic:
        steps = [
            "1. **先学数组和链表**：看懂数据怎样排在一起，以及插入、删除为什么有快有慢。",
            "2. **再学栈和队列**：抓住“后进先出”和“先进先出”这两个使用规则。",
            "3. **接着学树和堆**：理解数据为什么要分层组织，以及怎样更快地查找和取出重点。",
            "4. **最后学图**：处理对象之间更自由、更复杂的连接关系。",
            "5. **一路带着复杂度**：每学一种结构，只比较常用操作的时间和空间代价。",
        ]
    else:
        steps = [
            "1. **先认基本对象**：用自己的话说清最核心的几个名词。",
            "2. **再看它怎么运作**：一次只理解一个常用步骤或方法。",
            "3. **用最小例子确认理解**：例子只要小到能在脑中走一遍就够了。",
            "4. **最后比较适用场景**：弄清什么时候该用它，什么时候不该用。",
        ]
    return "\n".join([
        f"可以，先别急着一次学完「{topic}」。把内容全铺开很容易越学越乱，我们按一个清楚的顺序慢慢来。",
        "",
        *steps,
        "",
        f"你今天先做一件事：找到「{topic}」里的第一个基础概念，试着用自己的话说清它是什么、解决什么问题。说顺了，我们再继续下一步。",
    ])


def _strategy_response_ok(answer: str) -> bool:
    text = str(answer or "").strip()
    numbered_steps = len(re.findall(r"(?m)^\s*\d+[.、]", text))
    banned = ("```", "mermaid", "练习", "做题", "出题", "测验", "思维导图", "总结：", "##")
    warm_opening = bool(re.match(r"^(?:可以|别急|先别|不用|其实)", text))
    return 160 <= len(text) <= 650 and 3 <= numbered_steps <= 5 and warm_opening and not any(
        marker.lower() in text.lower() for marker in banned
    )


def _sorting_minimal_answer(question: str, chunks: list[dict]) -> str:
    values = [int(value) for value in re.findall(r"(?<![A-Za-z])\d+", question)[:3]]
    if len(values) < 3:
        values = [3, 1, 2]
    first, second, third = values
    after_second = sorted([first, second]) + [third]
    final = sorted(values)
    cite = next(
        (index for index, chunk in enumerate(chunks[:4], 1) if "排序" in str(chunk.get("text") or "")),
        1 if chunks else None,
    )
    citation = f" [^{cite}]" if cite else ""
    return "\n".join([
        f"**排序**就是按一个明确规则，重新排列同一批元素；例如升序就是从小到大。{citation}",
        "",
        f"只看最小例子：`[{first}, {second}, {third}]`。",
        "",
        f"1. 先看 `{first}`，暂时得到 `[{first}]`。",
        f"2. 把 `{second}` 放到 `{first}` 的正确位置，得到 `{after_second}`。",
        f"3. 再把 `{third}` 放进正确位置，得到 `{final}`。",
        "",
        f"所以这次排序做的事就是：`[{first}, {second}, {third}] → {final}`。元素没有增减，只是顺序变了。",
    ])


def _answer_matches_current_question(answer: str, question: str, topic_kp: str) -> bool:
    """Reject grounded-but-irrelevant answers before they reach the learner."""

    if not str(answer or "").strip():
        return False
    allowed = set(infer_kp_ids(question))
    if topic_kp and topic_kp != "custom_topic":
        allowed.add(topic_kp)
    observed = set(infer_kp_ids(answer))
    # SQL used to be accidentally bundled into this course. Keep a direct
    # boundary guard so an old vector chunk or provider response cannot put it
    # back into a data-structures answer after the taxonomy has been cleaned.
    if (
        topic_kp != "custom_topic"
        and _OUT_OF_COURSE_SQL_RE.search(answer)
        and not _OUT_OF_COURSE_SQL_RE.search(question)
    ):
        return False
    # Mentioning a necessary neighbouring concept is not topic drift. For
    # example, accurately defining a binary tree may contrast it with a BST.
    # Reject only when the answer contains recognised course topics but none
    # of them is the learner's current topic.
    if topic_kp != "custom_topic" and observed and allowed.isdisjoint(observed):
        return False
    if "只用" in question or "只回答" in question:
        requested_numbers = set(re.findall(r"(?<![A-Za-z])\d+", question))
        if requested_numbers - set(re.findall(r"(?<![A-Za-z])\d+", answer)):
            return False
        if len(answer) > 650:
            return False
    return True


def _rag_demo_answer(
    question: str,
    chunks: list[dict],
    *,
    guided: bool = False,
    topic_kp: str | None = None,
) -> str:
    compact_question = re.sub(r"\s+", "", question)
    asks_learning_strategy = _is_learning_strategy_question(compact_question)
    if topic_kp == "sorting_basic" and re.search(r"(?:什么是排序|排序是什么|最小例子|只用)", compact_question):
        return _sorting_minimal_answer(question, chunks)
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
            f"可以，我们先只看{traversal}遍历这一件事。它的意思是：{plain}。先把顺序记成 **{order}**。 [^{traversal_cite}]",
            "",
            "来看一棵只有 3 个节点的小树：",
            "```text",
            "    A",
            "   / \\",
            "  B   C",
            "```",
            "",
            f"按 **{order}** 依次访问，结果是：**{result}**。",
            "",
            f"你可以这样走：从 A 开始，按“{order}”判断下一步；每访问一个节点就立刻写下字母。记忆时只看“根”在顺序中的位置——它决定当前节点什么时候被记录。",
            "",
            f"现在你试着告诉我：如果把 B 和 C 对调，{traversal}结果会变成什么？",
        ])

    if guided and asks_learning_strategy:
        return _strategy_answer(question)

    if guided and topic_kp == "binary_tree":
        cite = next(
            (
                index for index, chunk in enumerate(chunks[:4], 1)
                if re.search(r"(?:最多|至多).{0,8}(?:两个|2个).{0,8}(?:孩子|子节点)", str(chunk.get("text") or ""))
                or "二叉树" in str(chunk.get("text") or "")
            ),
            1 if chunks else None,
        )
        citation = f" [^{cite}]" if cite else ""
        return "\n".join([
            "可以，我们先不背一整页定义。你把二叉树想成一张从上往下展开的家谱：每个成员最多只分出左、右两个位置，这些成员在树里叫“节点”。"
            f"注意“最多两个”也包括 0 个和 1 个，并不是每个节点都必须有两个孩子。{citation}",
            "",
            "比如根节点 A 只有左孩子 B，这仍然是二叉树；A 同时有 B、C 两个孩子，也仍然是二叉树。这里说的是“普通二叉树”，没有“左边一定小、右边一定大”的要求——那是二叉搜索树额外加的规则。",
            "",
            "先抓住这一句就够了：**二叉树是每个节点最多有两个孩子，并区分左、右位置的树。**",
            "",
            "我先问你一个很小的问题确认一下：一个节点只有右孩子、没有左孩子，它还能出现在二叉树里吗？",
        ])

    lines = (
        [
            f"可以，我们先不急着背“{question}”的整套内容。先把最关键的对象认清，再看它怎么运作：",
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
            "你可以把它想成整理一只工具箱：先认清每件工具，再学使用顺序，最后检查什么场景不能用。现在只从资料第一条核心定义出发，画一个只有 2—3 个元素的最小例子；再删掉一个元素，看看定义是否仍然成立。",
            "",
            "先用自己的话复述这条定义给我听就好，我会顺着你的理解继续讲。",
        ]
    else:
        lines += ["", "你可以继续追问其中一个概念、步骤或易错点，我会沿用同一资料范围。"]
    return "\n".join(lines)


async def _emit_answer(answer: str) -> None:
    # Keep deterministic/fallback answers visibly streaming even when the
    # grounded response is short.  Long answers retain the 72-character cap,
    # while short answers are split into at least five UI updates.
    step = max(1, min(72, (len(answer) + 4) // 5))
    for start in range(0, len(answer), step):
        delta = answer[start:start + step]
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
    interaction_action = str(state.get("interaction_action") or "")
    interaction_resource = dict(state.get("interaction_resource") or {})
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

    topic_kp, topic_name, custom_topic = _resolve_turn_topic(state, question)
    await emit({
        "type": "progress",
        "agent": "tutor",
        "stage": "learning_focus",
        "percent": 100,
        "text": topic_name,
        "knowledge_point": topic_kp,
        "detail": f"本轮学习焦点：{topic_name}",
    })
    # Selected sources narrow ownership, but must not disable the current-topic
    # filter. Uploaded chunks without kp metadata still pass hit_matches_kp.
    retrieval_kp = None if custom_topic else topic_kp
    retrieval_query = question
    if interaction_resource:
        retrieval_query = "\n".join(filter(None, [
            str(interaction_resource.get("title") or ""),
            str(interaction_resource.get("narration") or "")[:1200],
            question,
        ]))
    if retrieval_kp:
        retrieval_query = f"{question}\n课程知识点：{kp_retrieval_text(retrieval_kp)}"
    chunks = [] if custom_topic and not source_ids else retrieve(
        retrieval_query,
        final_k=8 if retrieval_kp else 4,
        source_ids=source_ids,
        kp=retrieval_kp,
        user_id=state.get("user_id", "demo_user"),
    )
    chunks = _focused_kp_chunks(chunks, retrieval_kp)
    chunks = focus_chunks_on_topic(chunks, retrieval_kp, topic_name)
    supplement = allows_supplement(state)
    if supplement:
        chunks.extend(supplemental_context(question))
    if guided:
        chunks = _beginner_first_chunks(chunks)
    if not source_ids and not guided and retrieval_kp:
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
        reason="custom_topic_general_knowledge" if custom_topic and not source_ids else "guided_or_knowledge_question",
        knowledge_point=topic_kp,
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
    if (source_ids or state.get("source_policy") == "strict") and not chunks and not interaction_resource and not supplement:
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
    effective_question = (
        _interaction_request(
            interaction_action,
            question,
            str(interaction_resource.get("title") or topic_name),
        )
        if interaction_resource else
        question if topic_name in question
        else f"本轮问题焦点：{topic_name}\n{question}"
    )
    if interaction_resource:
        lecture = str(
            interaction_resource.get("markdown")
            or interaction_resource.get("narration")
            or ""
        ).strip()
        if lecture:
            lecture = re.sub(r"\[\^\d+\]", "", lecture)
            ctx = (
                "[刚才的互动讲解，仅作对话背景，不是编号资料，不得据此编造引用]\n"
                f"{lecture}\n\n"
                "[所选资料检索片段]\n"
                f"{ctx or '（本轮未命中额外片段，请只使用上面的互动讲解原文。）'}"
            )
    prompt_call = render_tutor_prompt(
        effective_question,
        profile,
        ctx,
        source_ids,
        conversation=state.get("conversation") or state.get("messages") or [],
        guided=guided,
        general_knowledge=custom_topic and not source_ids,
        source_policy="supplement" if supplement else "strict",
    )
    prompt = prompt_call.prompt
    task_context = {"question": question, "source_count": len(source_ids), "material_chars": len(ctx),
                    "semantic_depth": state.get("model_depth", "standard")}
    selected_route = resolve(prompt, task_context=task_context)
    draft_feedback = is_draft_feedback(question)
    if draft_feedback:
        prompt += (
            "\n\n本次原稿反馈请简明完整：先指出优点，再选最重要的两到三个原句给出理由与可选修改。"
            "最后必须留下一个由学习者自行修订的具体小任务，并等待回答。不要代写整篇。"
        )
    learning_strategy = guided and _is_learning_strategy_question(question)
    await emit({
        "type": "progress",
        "agent": "tutor",
        "stage": "prompt_skill",
        "percent": 100,
        "detail": f"已加载 {prompt_call.capability}（{prompt_call.version}）",
        "prompt_skill": prompt_call.metadata(),
    })

    grounding_fallback_reason = ""
    answer_scope_fallback_reason = ""
    answer_streamed = False
    model_answer = False
    # Only numbered retrieved chunks define valid citation indices.
    ground_contexts = [str(c.get("text") or "") for c in chunks]
    if (is_demo() and resolve(prompt) is None) and _is_binary_tree_first_lesson(question, topic_kp, guided=guided):
        # Keep the most common first lesson instant, source-grounded and
        # teacher-like instead of paying for a reasoning call to restate a
        # basic definition.
        answer = _rag_demo_answer(
            question, chunks, guided=True, topic_kp="binary_tree",
        )
        ground = {"grounded": True, "unsupported": [], "verdict": "二叉树入门本地讲解"}
    elif learning_strategy and (is_demo() and resolve(prompt) is None):
        # A learning route is deterministic product guidance. Avoid spending a
        # reasoning-model round trip on content that is clearer and faster as
        # a concise teacher-written response.
        answer = _strategy_answer(topic_name)
        ground = {"grounded": True, "unsupported": [], "verdict": "本地教学路线"}
    elif (is_demo() and resolve("CAPABILITY=tutor.followup") is None):
        await emit({
            "type": "progress",
            "agent": "tutor",
            "stage": "fallback",
            "percent": 100,
            "degraded": True,
            "reason": "demo_mode",
            "detail": "演示模式使用确定性资料整理回答",
        })
        answer = (
            _strategy_answer(topic_name)
            if learning_strategy else
            f"「{topic_name}」不在当前课程知识库里；离线演示模式下我不补写无法核对的资料外答案。"
            "连接星火模型后可以直接继续提问，下一轮也可以随时换到别的知识点。"
            if custom_topic and not chunks else
            _rag_demo_answer(question, chunks, guided=guided, topic_kp=topic_kp)
        )
        ground = {"grounded": True, "unsupported": [],
                  "verdict": "自定义主题离线安全回答" if custom_topic and not chunks else "演示模式直接整理检索片段"}
    else:
        raw_parts: list[str] = []
        displayed_parts: list[str] = []
        model_answer = True
        selected_model_failed = False
        try:
            if selected_route:
                await emit({"type": "progress", "agent": "tutor", "stage": "model_route",
                            "detail": "正在结合问题与资料组织回答",
                            "model_route": {key: selected_route.get(key) for key in ("model", "provider", "automatic", "reason")}})
            async for delta in llm_stream(
                prompt,
                role="reasoner",
                system=prompt_call.system,
                temperature=0.25 if guided else 0.45,
                # Keep room for full explanations and the learner's revision task.
                max_tokens=6000 if selected_route and selected_route["provider"] == "kimi" else 2400,
                allow_model_fallback=True,
                allow_mock_fallback=False,
                reasoning_mode="" if selected_route and selected_route["provider"] == "kimi" else "disabled",
                task_context=task_context,
            ):
                raw_parts.append(delta)
                # Validate the entire answer before releasing it: a later token
                # may invent a citation even if the prefix looked plausible.

            raw_answer = "".join(raw_parts)
            answer = (
                "".join(displayed_parts)
                if answer_streamed
                else _normalize_tutor_answer(raw_answer, question, has_context=bool(chunks))
            )
            if not answer:
                raise RuntimeError("模型返回了内部提示模板，已阻止向学习者展示")
            if (
                not interaction_resource
                and not _answer_matches_current_question(answer, question, topic_kp)
            ):
                answer_scope_fallback_reason = f"模型回答未严格围绕当前问题「{topic_name}」"
                await emit({
                    "type": "progress",
                    "agent": "tutor",
                    "stage": "answer_scope",
                    "percent": 100,
                    "degraded": True,
                    "reason": "answer_scope_failed",
                    "detail": (
                        "回答扩展了未提问的知识点，已记录复核"
                        if answer_streamed
                        else "回答扩展了未提问的知识点，已替换为当前问题的最小讲解"
                    ),
                })
                if not answer_streamed:
                    answer = _rag_demo_answer(
                        question, chunks, guided=guided, topic_kp=topic_kp,
                    )
                    model_answer = False
        except Exception as error:  # 所有模型不可用时仍保持资料内教学链路可用
            selected_model_failed = selected_route is not None
            await emit({
                "type": "progress",
                "agent": "tutor",
                "stage": "fallback",
                "percent": 100,
                "degraded": True,
                "reason": failure_code(error),
                "error": MESSAGES[failure_code(error)],
                "detail": MESSAGES[failure_code(error)],
            })
            if answer_streamed:
                interruption = "\n\n连接刚才短暂中断了，前面的讲解已经保留。你回复“继续”，我会从这里接着讲。"
                await _emit_answer(interruption)
                displayed_parts.append(interruption)
                answer = "".join(displayed_parts)
                model_answer = True
            elif resolve(prompt):
                model_answer = False
                answer = "所选模型调用失败，本次没有生成讲解。请打开模型设置检查连接和额度后重试。"
            else:
                model_answer = False
                answer = (
                    f"暂时无法连接讲解模型，并且课程资料中没有「{topic_name}」的可核对内容。请稍后重试。"
                    if custom_topic and not chunks else
                    _rag_demo_answer(question, chunks, guided=guided, topic_kp=topic_kp)
                )

        if model_answer:
            if custom_topic and not chunks and not supplement:
                ground = {
                    "grounded": True,
                    "unsupported": [],
                    "verdict": "自定义主题使用当前文本主脑的通用知识生成，未声明虚构资料引用。",
                }
            else:
                ground = grounding_check_local(
                    answer,
                    ground_contexts,
                    question=question,
                    allow_supplement=supplement,
                )
            if not ground.get("grounded", False) and not ground.get("accepted", False):
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
                    "detail": (
                        "流式回答需要进一步复核"
                        if answer_streamed
                        else "模型回答未通过资料溯源,不会展示原回答"
                    ),
                    "grounding": failed_grounding,
                })
                if not answer_streamed:
                    await emit({
                        "type": "progress",
                        "agent": "tutor",
                        "stage": "fallback",
                        "percent": 100,
                        "degraded": True,
                        "reason": "grounding_failed",
                        "detail": f"已替换为资料内确定性讲解：{grounding_fallback_reason[:100]}",
                    })
                    answer = _rag_demo_answer(question, chunks, guided=guided, topic_kp=topic_kp)
                    ground = {
                        "grounded": True,
                        "unsupported": [],
                        "verdict": "原回答未通过溯源,已替换为资料片段整理",
                    }
        else:
            ground = {
                "grounded": True,
                "unsupported": [],
                "verdict": (
                    "所选模型调用失败，未生成讲解" if selected_model_failed else
                    "模型回答偏离当前问题,已替换为同主题最小讲解"
                    if answer_scope_fallback_reason else
                    "模型不可用,已直接整理检索片段"
                ),
            }
            if selected_model_failed:
                ground["grounded"] = False

    if model_answer and not answer_streamed:
        from ..services.tutor_question_quality import check_question
        answer, question_quality = await check_question(answer, ctx)
        if question_quality:
            await emit({"type": "progress", "agent": "tutor", "stage": "question_quality", "percent": 100,
                "detail": "检查题已进行模型复核，仍可指出有争议的条件" if question_quality["accepted"] else "检查题未通过条件与答案核对，已改为简答",
                "question_quality": question_quality})

    # Release only the complete, checked answer. Local checks are not fact verification.
    if supplement and ground.get("accepted"):
        notice = "\n\n> " + ("以上依据相关资料并允许通用补充；补充部分未经资料逐项核验。" if chunks
                                  else "本次未找到相关资料，以上为通用知识讲解，未经课程资料核验。")
        answer += notice
        if answer_streamed:
            await _emit_answer(notice)
    if not supplement and ground.get("accepted"):
        answer += "\n\n> 本次仅检查了引用编号或资料关联，未逐项核验结论；可展开引用原文核对。"
    safety = safety_filter(answer)
    if not safety.get("passed", safety.get("safe", True)):
        answer = str(safety.get("text") or answer)
        await emit({"type": "safety", "level": "warn", "detail": "命中内容安全规则,已在展示前脱敏"})
    if not answer_streamed:
        await _emit_answer(answer)
    grounding = {
        "grounded": bool(ground.get("grounded", False)),
        "unsupported_count": len(ground.get("unsupported") or []),
        "verdict": ground.get("verdict", ""),
        "verification": ground.get("verification", "source_excerpt" if ground.get("grounded") else "unverified"),
    }
    await emit({
        "type": "progress",
        "agent": "tutor",
        "stage": "grounding",
        "percent": 100,
        "detail": str(ground.get("verdict") or "资料溯源需要复核"),
        "grounding": grounding,
    })
    flags = (
        [{"agent": "tutor", "type": "grounding_fallback", "detail": grounding_fallback_reason}]
        if grounding_fallback_reason else []
    )
    if not ground.get("grounded", True) and not ground.get("accepted", False):
        flags.append({"agent": "tutor", "type": "grounding", "detail": ground.get("verdict", "")})
        await emit({"type": "safety", "level": "warn",
                    "detail": "部分表述未命中教材依据,已提示复核"})
    if answer_scope_fallback_reason:
        flags.append({
            "agent": "tutor",
            "type": "answer_scope",
            "detail": answer_scope_fallback_reason,
        })
    if not safety.get("passed", safety.get("safe", True)):
        flags.append({"agent": "tutor", "type": "safety", "detail": safety.get("hits", [])})

    cited_indices = used_indices(answer, len(citations))
    cites = [citations[index - 1]["citation"] for index in cited_indices]
    await emit({"type": "citations", "agent": "tutor", "items": cites,
                "evidence": [citations[index - 1] for index in cited_indices]})
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
