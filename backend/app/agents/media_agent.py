"""媒体智能体(Media Agent):
1) 星火生成分镜视频脚本(video_script JSON);
2) 首选小云雀文生视频（异步任务 + progress 事件轮询）;
3) 云端视频不可用时优雅降级:生成 Manim 动画场景代码(可本地渲染)+ 讯飞 TTS 旁白音频;
4) 讯飞文生图生成课程封面(可选)。"""
from __future__ import annotations

import asyncio
import ast
import json
import re
import uuid

from ..config import GEN_DIR, is_demo
from ..llm import multimodal_gateway
from ..llm.spark_client import llm_complete, parse_json
from ..prompt_templates import render_manim_prompt_call, render_video_prompt_call
from ..rag.citation import build_context
from ..rag.retriever import retrieve
from ..services.knowledge_graph import infer_kp_ids, resolve_topic
from ..services.topic_scope import focus_chunks_on_topic
from .emitter import agent_end, agent_start, emit

_LOCAL_MANIM_VIDEOS = {
    "binary_tree": "manim_binary_tree_traversal.mp4",
    "bst": "manim_bst_insertion.mp4",
}


def _strip_code_fence(code: str) -> str:
    text = str(code or "").strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines.pop()
    return "\n".join(lines).strip()


def _valid_manim_code(code: str, cls: str) -> bool:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != cls:
            continue
        inherits_scene = any(isinstance(base, ast.Name) and base.id == "Scene" for base in node.bases)
        has_construct = any(isinstance(item, ast.FunctionDef) and item.name == "construct" for item in node.body)
        return inherits_scene and has_construct
    return False


def _fallback_manim_code(cls: str, name: str, *, source_bound: bool = False) -> str:
    if source_bound:
        return f'''from manim import *

class {cls}(Scene):
    def construct(self):
        title = Text({name!r}, font_size=42, color=GREEN).to_edge(UP)
        note = Text("根据所选资料整理", font_size=28, color=BLUE)
        self.play(Write(title))
        self.play(FadeIn(note))
        self.wait(1)
'''
    return f'''from manim import *

class {cls}(Scene):
    def construct(self):
        title = Text({name!r}, font_size=42, color=GREEN).to_edge(UP)
        root = Circle(radius=0.42, color=GREEN).shift(UP * 0.6)
        left = Circle(radius=0.42, color=BLUE).shift(LEFT * 2 + DOWN)
        right = Circle(radius=0.42, color=ORANGE).shift(RIGHT * 2 + DOWN)
        edges = VGroup(Line(root.get_bottom(), left.get_top()), Line(root.get_bottom(), right.get_top()))
        labels = VGroup(Text("ROOT", font_size=20).move_to(root), Text("L", font_size=20).move_to(left), Text("R", font_size=20).move_to(right))
        self.play(Write(title), Create(root), FadeIn(labels[0]))
        self.play(Create(edges), Create(left), Create(right), FadeIn(labels[1:]))
        self.wait(1)
'''


def _normalize_manim_code(
    code: str,
    cls: str,
    name: str,
    *,
    source_bound: bool = False,
) -> str:
    cleaned = _strip_code_fence(code)
    if _valid_manim_code(cleaned, cls):
        return cleaned
    return _fallback_manim_code(cls, name, source_bound=source_bound)


def _scene_class_name(kp: str) -> str:
    pieces = re.findall(r"[A-Za-z0-9]+", str(kp or ""))
    suffix = "".join(piece[:1].upper() + piece[1:] for piece in pieces) or "Learning"
    if suffix[0].isdigit():
        suffix = "Topic" + suffix
    return "Scene" + suffix


def _python_animation_code(name: str, script: dict) -> str:
    captions = [
        str(scene.get("caption") or scene.get("visual") or "").strip()
        for scene in script.get("scenes") or []
        if isinstance(scene, dict) and str(scene.get("caption") or scene.get("visual") or "").strip()
    ] or [name, "建立结构", "走完过程", "检查边界"]
    labels = captions[:8]
    return f'''"""SparkLearn 安全模板：用 Matplotlib 逐步演示学习过程。"""
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

TITLE = {name!r}
STEPS = {labels!r}

fig, ax = plt.subplots(figsize=(10, 5.6))
fig.patch.set_facecolor("#F7FAF8")

def draw(frame):
    ax.clear()
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")
    ax.set_title(TITLE, fontsize=20, fontweight="bold", color="#163E32")
    for index, label in enumerate(STEPS):
        x = 1.1 + index * (7.8 / max(1, len(STEPS) - 1))
        active = index <= frame
        ax.scatter([x], [3], s=900 if active else 650,
                   color="#2F9E73" if active else "#DDE8E1", zorder=2)
        ax.text(x, 3, str(index + 1), ha="center", va="center",
                color="white" if active else "#6B7A71", fontweight="bold")
        ax.text(x, 2.15, label, ha="center", va="top", fontsize=10,
                color="#163E32" if active else "#7C8981", wrap=True)
        if index < len(STEPS) - 1:
            ax.plot([x + 0.35, x + 7.8 / max(1, len(STEPS) - 1) - 0.35], [3, 3],
                    color="#78C6A5" if index < frame else "#DDE8E1", linewidth=4, zorder=1)

animation = FuncAnimation(fig, draw, frames=len(STEPS), interval=1100, repeat=True)
plt.tight_layout()
plt.show()
'''


def _animation_preview(name: str, script: dict) -> dict:
    stages = []
    for index, scene in enumerate(script.get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        stages.append({
            "label": str(scene.get("caption") or f"步骤 {index + 1}"),
            "detail": str(scene.get("visual") or scene.get("caption") or ""),
            "time": str(scene.get("t") or ""),
        })
    if not stages:
        stages = [
            {"label": "认识对象", "detail": f"先看清「{name}」中的对象和关系", "time": "01"},
            {"label": "执行规则", "detail": "让关键规则按顺序发生", "time": "02"},
            {"label": "观察变化", "detail": "对比每一步前后的状态", "time": "03"},
            {"label": "检查边界", "detail": "用边界情况验证理解", "time": "04"},
        ]
    return {"title": name, "stages": stages[:8], "interval_ms": 1500}


def _video_prompt(script: dict, *, source_bound: bool) -> str:
    base = str(script.get("video_prompt") or "").strip()
    if not source_bound:
        return base or str(script.get("title") or "educational animation")
    narration = " ".join(str(script.get("narration") or "").split())[:500]
    captions = "；".join(
        str(scene.get("caption") or "").strip()
        for scene in script.get("scenes") or []
        if isinstance(scene, dict) and str(scene.get("caption") or "").strip()
    )[:300]
    return (
        "Create a clean educational 2D animation. Only visualize the supplied "
        "source-grounded narration and captions. Do not add facts, labels, formulas, "
        "or examples that are not supplied. "
        f"Narration: {narration or 'Use a neutral abstract learning visual.'} "
        f"Captions: {captions or 'No factual on-screen labels.'}"
    )


def _clean_script_text(value: object, limit: int = 360) -> str:
    text = str(value or "")
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"`{1,3}", "", text)
    text = re.sub(r"[\x00-\x1f\ufffd\ue000-\uf8ff]", " ", text)
    text = re.split(r"(?:答案|参考答案|解析)\s*[:：]", text, maxsplit=1)[0]
    text = " ".join(text.split()).strip()
    return text[:limit].rstrip("，；、 ")


def _script_on_topic(script: dict, name: str, kp: str, chunks: list[dict]) -> bool:
    body = {
        "narration": script.get("narration"),
        "scenes": script.get("scenes"),
    }
    text = re.sub(r"\s+", "", json.dumps(body, ensure_ascii=False)).lower()
    topic = re.sub(r"\s+", "", str(name or "")).lower()
    pieces = [part for part in re.split(r"[与和、/·（）()\s]+", topic) if len(part) >= 2]
    # The current topic is the boundary. A broad chapter containing adjacent
    # topics must not make those topics valid for this video's narration.
    allowed = set(infer_kp_ids(name))
    if kp and kp != "custom_topic":
        allowed.add(kp)
    detected = set(infer_kp_ids(text))
    if detected - allowed:
        return False
    return bool(
        topic
        and (
            topic in text
            or any(part in text for part in pieces)
            or bool(detected & allowed)
        )
    )


def _strict_sorting_example_requested(goal: str) -> bool:
    compact = re.sub(r"\s+", "", str(goal or ""))
    return bool(re.search(r"什么是排序|排序是什么|最小例子|只用|3[、,，和与]?1[、,，和与]?2", compact))


def _strict_sorting_example_script() -> dict:
    """A two-minute script that never expands beyond the learner's 3,1,2 question."""

    narration = (
        "先只看一个问题：什么是排序。排序就是按照一个明确规则，重新排列同一批元素。"
        "今天的规则是从小到大，例子只有三个数：3、1、2。先不要想任何算法名称，也不要加入别的数字。"
        "第一步，把最先看到的 3 暂时放好。此时已有的顺序只有一个数，所以可以写成 3。"
        "第二步，看到 1。因为目标是从小到大，1 应该在 3 的前面。把 1 放到前面，当前结果变成 1、3。"
        "注意，数字没有增加，也没有消失，只是 1 和 3 的相对位置符合了从小到大的规则。"
        "第三步，看到 2。先问 2 应该放在哪里。2 比 1 大，所以不能放在 1 前面；2 又比 3 小，所以不能放在 3 后面。"
        "因此 2 正好放在 1 和 3 中间，结果变成 1、2、3。现在从左到右检查：1 小于 2，2 小于 3，满足升序。"
        "再做一次完整复述：输入是 3、1、2，目标是从小到大；先保留 3，再把 1 放到 3 前面，最后把 2 放到 1 和 3 中间。"
        "输出是 1、2、3。输入和输出都包含同样的三个数，因此排序改变的是位置，不是元素本身。"
        "这里最容易犯的错有两个。第一，只顾移动数字，却忘了先说清规则；如果规则改成从大到小，结果就会不同。"
        "第二，得到一个结果后不检查。可靠的检查方法是从左到右逐对比较，并确认元素数量和值都没有变化。"
        "最后做一个十秒自测：不看画面，说出排序的目标、3、1、2 的三步变化，以及为什么最终是 1、2、3。"
        "如果你能完整说出这些，就已经理解了这个问题；暂时不需要扩展到其他排序方法。"
    )
    return {
        "title": "基础排序 2 分钟讲透",
        "narration": narration,
        "scenes": [
            {"visual": "只展示问题、升序规则与输入 3、1、2", "caption": "明确目标：从小到大"},
            {"visual": "画面只保留第一个数 3", "caption": "先放好 3"},
            {"visual": "把 1 移到 3 前面，状态变为 1、3", "caption": "1 放到 3 前面"},
            {"visual": "把 2 放到 1 和 3 中间，状态变为 1、2、3", "caption": "2 放到中间"},
            {"visual": "对照输入输出，逐项确认元素未增减", "caption": "只改变位置"},
            {"visual": "从左到右检查 1<2<3，并给出十秒自测", "caption": "检查规则与边界"},
        ],
        "video_prompt": (
            "Minimal educational animation showing only the numbers 3, 1, 2 being reordered "
            "into 1, 2, 3, large readable cards, no other algorithms or objects"
        ),
    }


def _normalize_script(script: dict, chunks: list[dict], name: str) -> dict:
    normalized = dict(script)
    narration = _clean_script_text(normalized.get("narration"), 820)
    additions = list(dict.fromkeys(
        item
        for item in (_clean_script_text(chunk.get("text"), 210) for chunk in chunks)
        if len(item) >= 24 and item not in narration
    ))
    scaffolds = [
        f"先明确{name}要解决的具体问题，以及输入和输出分别是什么",
        "再把关键对象按顺序摆出来，不跳步骤，也不把多个概念一次塞给初学者",
        "接着用一个最小例子观察状态怎样变化，并在每一步说清为什么这样做",
        "完成例子后回到正式定义，把生活化理解和资料中的术语一一对应",
        "随后检查时间与空间代价，说明这种方法在数据规模变大时会发生什么",
        "还要特别指出一个常见错误，并用成立条件和不成立条件做清楚对照",
        "讲到新术语时先用白话解释，再给正式名称，避免只报概念却没有建立直观认识",
        "演示每一步时同时说明当前看到了什么、准备做什么、做完以后状态发生了什么变化",
        "如果有多种情况，先讲最常见的一种，再单独列出边界情况，不让例外打断主线",
        "最小例子结束后重新从头复述一次关键顺序，让学习者能在没有画面的情况下自己走完",
        "再用一个反例说明哪些条件一旦不满足，刚才的方法就不能直接使用或结论不再成立",
        "把易错点说成可执行的检查动作，例如先检查对象、再检查顺序、最后检查停止条件",
        "如果画面变化较快，就在关键状态停一下，先让学习者看清变化前后分别是什么，再继续下一步",
        "只有资料确实给出了复杂度时才说明数量级，并把复杂度和刚才实际发生的操作次数对应起来",
        "最后把生活类比收回来，明确类比只帮助建立直觉，真正作答仍要使用准确的定义、步骤和边界条件",
        "收束前给学习者一个十秒自测：能否说出目标、关键步骤以及最容易错的那条边界",
        "最后用一句记忆钩子收束：先看目标，再走步骤，用例子验证，按边界检查",
    ]
    if len(narration) < 650:
        parts = [narration.rstrip("。")] if narration else []
        for item in [*additions, *scaffolds]:
            if item and item not in parts and item not in narration:
                parts.append(item.rstrip("。"))
            if len("。".join(parts)) >= 700:
                break
        narration = "。".join(parts).strip("。") + "。"
    if name and name not in narration:
        marker = f"本节主题是{name}。"
        body_budget = max(0, 820 - len(marker) - 1)
        body = narration[:body_budget].rstrip("，；、。 ")
        narration = f"{body}。{marker}" if body else marker
    normalized["narration"] = narration[:820] or f"本节用两分钟讲清{name}的核心概念、最小例子和易错边界。"

    scenes = [scene for scene in normalized.get("scenes") or [] if isinstance(scene, dict)]
    if len(scenes) < 6:
        scenes = [
            {"visual": f"用一句白话呈现{name}要解决的问题", "caption": "先抓核心结论"},
            {"visual": "用生活类比说明对象之间的关系", "caption": "建立直观认识"},
            {"visual": "把最小例子的初始状态完整摆出来", "caption": "看清输入与目标"},
            {"visual": "一次只演示一个关键步骤及状态变化", "caption": "跟着步骤走一遍"},
            {"visual": "把例子重新对应到正式概念和术语", "caption": "回到正式定义"},
            {"visual": "对照正确做法、常见错误和适用边界", "caption": "最后检查边界"},
        ]
    normalized["scenes"] = [
        {**scene, "t": f"{index * 20}-{(index + 1) * 20}s"}
        for index, scene in enumerate(scenes[:6])
    ]
    normalized["target_seconds"] = 120
    normalized["video_clip_seconds"] = 10
    return normalized


def _local_manim_video(kp: str) -> dict | None:
    filename = _LOCAL_MANIM_VIDEOS.get(kp)
    if not filename or not (GEN_DIR / filename).is_file():
        return None
    return {"status": "succeeded", "url": f"/static/gen/{filename}"}


async def run(state: dict) -> dict:
    requested = state.get("kinds") or []
    if requested and not any(k in requested for k in (
        "video", "audio", "image", "manim", "python_animation",
    )):
        return {}
    explicit_kind = (
        "python_animation" if "python_animation" in requested else
        "manim" if "manim" in requested else
        "video"
    )
    kp, name, custom_topic = resolve_topic(
        state.get("knowledge_points"),
        state.get("learning_goal"),
        state.get("topic_label"),
    )
    source_ids = [str(x) for x in (state.get("source_ids") or []) if str(x).strip()]
    # Prefer the exact current question over the broader learning goal created
    # by orchestration. This is what lets a request such as “只用 3、1、2” stay
    # narrower than the surrounding sorting chapter.
    goal = str(
        state.get("conversation_focus")
        or state.get("learning_goal")
        or state.get("goal")
        or ""
    )
    await agent_start("media", "媒体智能体", f"「{name}」分镜脚本 → 文生视频/动画 + TTS")

    chunks = [] if custom_topic and not source_ids else retrieve(
        f"{name} 核心概念 关键步骤 {goal}",
        final_k=5,
        source_ids=source_ids,
        kp=None if custom_topic else kp,
        user_id=state.get("user_id", "demo_user"),
    )
    chunks = focus_chunks_on_topic(chunks, kp, name)
    context, citations = build_context(chunks)
    if source_ids and not chunks:
        script = {
            "title": f"{name}·资料不足",
            "narration": "当前选中的资料没有可检索内容，因此未生成资料范围外的讲解视频。",
            "scenes": [],
            "video_prompt": "",
        }
        rid = uuid.uuid4().hex[:12]
        resource = {
            "id": rid,
            "kind": explicit_kind,
            "kp": kp,
            "title": script["title"],
            "payload": {"script": script, "degraded": True, "reason": "selected sources have no indexed content"},
            "citations": [],
        }
        await emit({"type": "resource", "resource": resource})
        await agent_end("media", "所选资料无可用片段,已阻止无依据生成")
        return {
            "generated_resources": {rid: resource},
            "safety_flags": [{"agent": "media", "type": "source_scope_empty",
                              "detail": "所选资料没有可检索内容"}],
        }

    video_prompt_call = render_video_prompt_call(
        kp=name,
        goal=goal or f"讲清{name}",
        context=context or "（课程知识库未检索到片段）",
        general_knowledge=custom_topic and not source_ids,
    )
    script = {}
    script_error = ""
    strict_sorting_example = kp == "sorting_basic" and _strict_sorting_example_requested(goal)
    if strict_sorting_example:
        # This learner explicitly constrained the explanation to one tiny
        # example. Skip the model and broad chapter excerpts entirely so the
        # length-normalization step cannot pull adjacent sorting topics back in.
        script = _strict_sorting_example_script()
    elif not is_demo():
        try:
            raw = await asyncio.wait_for(
                llm_complete(
                    video_prompt_call.prompt,
                    system=video_prompt_call.system,
                    role="reasoner",
                    temperature=0.55,
                    max_tokens=1800,
                    allow_mock_fallback=False,
                ),
                timeout=12,
            )
            script = parse_json(raw)
        except Exception as error:  # noqa: BLE001
            script_error = str(error)[:180]
    if (not isinstance(script, dict) or not script.get("narration")
            or not _script_on_topic(script, name, kp, chunks)):
        if isinstance(script, dict) and script and not _script_on_topic(script, name, kp, chunks):
            script_error = f"模型脚本偏离当前问题「{name}」"
        if kp == "sorting_basic":
            fallback_narration = (
                "排序就是按一个明确规则重新排列同一批元素。我们只看升序和 3、1、2："
                "先把 3 看成已有序的一项；把 1 插到 3 前面，得到 1、3；"
                "再把 2 插到 1 和 3 中间，得到 1、2、3。"
                "元素没有增加也没有减少，改变的只有顺序。这个最小过程就是理解基础排序的起点。"
            )
        else:
            fallback_narration = (
                " ".join(str(chunks[0].get("text") or "").split())[:260]
                if chunks else f"本节用两分钟讲清{name}的核心思想与典型操作。"
            )
        source_scenes = [
            {"t": f"{index * 12}-{(index + 1) * 12}s",
             "visual": " ".join(str(chunk.get("text") or "").split())[:90],
             "caption": f"要点 {index + 1}"}
            for index, chunk in enumerate(chunks[:4])
        ]
        script = {"title": f"{name} 2 分钟讲透", "narration": fallback_narration,
                  "scenes": source_scenes or [
                      {"t": "0-12s", "visual": f"识别{name}中的对象", "caption": "认识对象"},
                      {"t": "12-24s", "visual": "展示对象之间的关键关系", "caption": "建立结构"},
                      {"t": "24-40s", "visual": "逐步执行核心规则", "caption": "走完过程"},
                      {"t": "40-60s", "visual": "对比正常情况与边界情况", "caption": "检查边界"},
                  ],
                  "video_prompt": f"educational 2D animation explaining {kp}, clean diagram style"}
    script = _normalize_script(script, [] if strict_sorting_example else chunks, name)
    await emit({"type": "progress", "agent": "media", "stage": "script", "percent": 25,
                "detail": f"分镜脚本就绪,共 {len(script.get('scenes', []))} 个镜头"
                + (f"；已启用同主题安全版本：{script_error}" if script_error else "")})

    payload: dict = {
        "script": script,
        "prompt_skill": video_prompt_call.metadata(),
        "animation_mode": explicit_kind,
        "animation_preview": _animation_preview(name, script),
    }
    trace_id = str(state.get("session_id", ""))
    # TTS and cloud video creation are independent. Starting narration here
    # removes the artificial serial wait and lets the configured provider use
    # its real timeout instead of being cut off after 2.5 seconds.
    audio_task = asyncio.create_task(
        multimodal_gateway.tts(script["narration"][:820], trace_id=trace_id)
    )

    mode = explicit_kind if explicit_kind != "video" else "manim"
    if explicit_kind == "video":
        try:
            created = await multimodal_gateway.video_create(
                _video_prompt(script, source_bound=bool(source_ids)), trace_id=trace_id,
            )
            if created["ok"]:
                provider = str(created["data"].get("provider") or "video")
                payload["video"] = dict(created["data"])
                mode = provider
                await emit({
                    "type": "progress",
                    "agent": "media",
                    "stage": "video",
                    "percent": 45,
                    "detail": "云端动画任务已提交；无需在这里等待，可先学习分镜与旁白",
                    "task_id": created["data"].get("task_id"),
                })
            elif created["data"]:
                payload["video"] = created["data"]
        except Exception:  # noqa: BLE001
            payload["video"] = {"status": "degraded", "reason": "视频服务异常,已切换为脚本讲解"}
            await emit({"type": "progress", "agent": "media", "stage": "video", "percent": 40,
                        "detail": "视频服务异常,已安全切换为脚本与动画代码"})

    if explicit_kind == "python_animation":
        payload["python_code"] = _python_animation_code(name, script)
        await emit({"type": "progress", "agent": "media", "stage": "python_animation", "percent": 70,
                    "detail": "Python 数学动画脚本与浏览器动态预览已生成"})

    if mode == "manim":                                            # 显式 Manim 或视频降级链路
        cls = _scene_class_name(kp)
        if explicit_kind == "video" or source_ids or custom_topic or is_demo():
            # A failed cloud clip must not trigger a second LLM round-trip.
            # The browser preview and deterministic code are already useful.
            payload["manim_code"] = _fallback_manim_code(
                cls, name, source_bound=bool(source_ids) or custom_topic
            )
        else:
            manim_prompt_call = render_manim_prompt_call(
                kp=name,
                class_name=cls,
                context=context or "（课程知识库未检索到片段）",
                general_knowledge=custom_topic and not source_ids,
            )
            code = await llm_complete(
                manim_prompt_call.prompt,
                system=manim_prompt_call.system,
                role="reasoner",
                temperature=0.3,
                max_tokens=1400,
            )
            payload["manim_code"] = _normalize_manim_code(
                code, cls, name, source_bound=custom_topic
            )
            payload["manim_prompt_skill"] = manim_prompt_call.metadata()
        local_video = _local_manim_video(kp)
        if local_video:
            payload["video"] = local_video
            mode = "local_manim"
        await emit({"type": "progress", "agent": "media", "stage": "manim", "percent": 70,
                    "detail": "云端视频未配置/失败,已使用预渲染 Manim 教学动画"
                    if local_video else "云端视频未配置/失败,已降级为 Manim 动画代码(可本地渲染)"})

    try:
        audio = await audio_task
    except Exception as error:  # noqa: BLE001
        audio = {"ok": False, "data": {}, "error": f"云端旁白异常：{str(error)[:140]}"}
    if isinstance(audio, dict) and audio.get("ok"):
        payload["audio_url"] = audio["data"]["audio_url"]
        payload["audio"] = {
            "status": "ready",
            "provider": audio["data"].get("provider", "spark_tts"),
            "degraded": bool(audio.get("degraded")),
            "error": str(audio.get("error") or "")[:240],
        }
    else:
        payload["audio"] = {
            "status": "fallback",
            "provider": "browser_speech",
            "error": str(audio.get("error") or "云端旁白暂不可用")[:180] if isinstance(audio, dict) else str(audio)[:180],
        }
    await emit({"type": "progress", "agent": "media", "stage": "post", "percent": 100,
                "detail": "两分钟旁白处理完成"
                if isinstance(audio, dict) and audio.get("ok")
                else "云端旁白不可用,已保留可朗读脚本"})

    rid = uuid.uuid4().hex[:12]
    title_suffix = {
        "manim": "Manim 数学动画",
        "python_animation": "Python 数学动画",
        "video": "讲解视频",
    }[explicit_kind]
    resource = {"id": rid, "kind": explicit_kind, "kp": kp,
                "title": f"{name}·{title_suffix}",
                "payload": {**payload, "topic_label": name, "custom_topic": custom_topic,
                            "source_ids": source_ids},
                "citations": [item["citation"] for item in citations]}
    await emit({"type": "resource", "resource": resource})
    summaries = {
        "xiaoyunque": "小云雀视频任务已提交",
        "video": "云端视频任务已提交",
        "local_manim": "已产出预渲染 Manim 教学动画 + 旁白脚本",
        "manim": "已产出 Manim 动画代码 + 旁白脚本(降级模式)",
        "python_animation": "已产出 Python 数学动画代码 + 浏览器动态预览",
    }
    await agent_end("media", summaries.get(mode, "媒体学习资源已生成"), {"id": rid, "mode": mode})
    return {"generated_resources": {rid: resource},
            "progress_events": [{"agent": "media", "mode": mode}]}
