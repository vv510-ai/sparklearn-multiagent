"""媒体智能体(Media Agent):
1) 星火生成分镜视频脚本(video_script JSON);
2) 首选小云雀文生视频（异步任务 + progress 事件轮询）;
3) 云端视频不可用时优雅降级:生成 Manim 动画场景代码(可本地渲染)+ 讯飞 TTS 旁白音频;
4) 讯飞文生图生成课程封面(可选)。"""
from __future__ import annotations

import asyncio
import ast
import re
import uuid

from ..config import GEN_DIR, is_demo
from ..llm import multimodal_gateway
from ..llm.spark_client import llm_complete, parse_json
from ..prompt_templates import render_manim_prompt_call, render_video_prompt_call
from ..rag.citation import build_context
from ..rag.retriever import retrieve
from ..services.knowledge_graph import resolve_topic
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
    text = re.sub(r"[\x00-\x1f\ufffd\ue000-\uf8ff]", " ", str(value or ""))
    text = re.split(r"(?:答案|参考答案|解析)\s*[:：]", text, maxsplit=1)[0]
    text = " ".join(text.split()).strip()
    return text[:limit].rstrip("，；、 ")


def _normalize_script(script: dict, chunks: list[dict], name: str) -> dict:
    normalized = dict(script)
    narration = _clean_script_text(normalized.get("narration"), 360)
    additions = list(dict.fromkeys(
        item
        for item in (_clean_script_text(chunk.get("text"), 150) for chunk in chunks)
        if len(item) >= 24 and item not in narration
    ))
    scaffolds = [
        f"先明确{name}要解决的具体问题，以及输入和输出分别是什么",
        "再把关键对象按顺序摆出来，不跳步骤，也不把多个概念一次塞给初学者",
        "接着用一个最小例子观察状态怎样变化，并在每一步说清为什么这样做",
        "完成例子后回到正式定义，把生活化理解和资料中的术语一一对应",
        "随后检查时间与空间代价，说明这种方法在数据规模变大时会发生什么",
        "还要特别指出一个常见错误，并用成立条件和不成立条件做清楚对照",
        "最后用一句记忆钩子收束：先看目标，再走步骤，用例子验证，按边界检查",
    ]
    if len(narration) < 280:
        parts = [narration.rstrip("。")] if narration else []
        for item in [*additions, *scaffolds]:
            if item and item not in parts and item not in narration:
                parts.append(item.rstrip("。"))
            if len("。".join(parts)) >= 300:
                break
        narration = "。".join(parts).strip("。") + "。"
    normalized["narration"] = narration[:360] or f"本节用一分钟讲清{name}的核心概念、最小例子和易错边界。"

    scenes = [scene for scene in normalized.get("scenes") or [] if isinstance(scene, dict)]
    if len(scenes) < 4:
        scenes = [
            {"t": "0-15s", "visual": f"用一句话呈现{name}的学习目标", "caption": "先抓核心结论"},
            {"t": "15-30s", "visual": "按顺序演示关键对象和步骤", "caption": "跟着步骤走一遍"},
            {"t": "30-45s", "visual": "展示一个最小案例的状态变化", "caption": "用最小例子验证"},
            {"t": "45-60s", "visual": "对照正确做法与常见错误", "caption": "最后检查适用边界"},
        ]
    normalized["scenes"] = scenes[:6]
    normalized["target_seconds"] = 60
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
    goal = str(state.get("learning_goal") or "")
    await agent_start("media", "媒体智能体", f"「{name}」分镜脚本 → 文生视频/动画 + TTS")

    chunks = [] if custom_topic and not source_ids else retrieve(
        f"{name} 核心概念 关键步骤 {goal}",
        final_k=5,
        source_ids=source_ids,
        kp=None if source_ids else kp,
        user_id=state.get("user_id", "demo_user"),
    )
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
    if not is_demo():
        raw = await llm_complete(video_prompt_call.prompt,
                                 system=video_prompt_call.system,
                                 role="reasoner",
                                 temperature=0.7, max_tokens=1200)
        script = parse_json(raw)
    if not isinstance(script, dict) or not script.get("narration"):
        fallback_narration = (
            " ".join(str(chunks[0].get("text") or "").split())[:180]
            if chunks else f"本节用一分钟讲清{name}的核心思想与典型操作。"
        )
        source_scenes = [
            {"t": f"{index * 12}-{(index + 1) * 12}s",
             "visual": " ".join(str(chunk.get("text") or "").split())[:90],
             "caption": f"要点 {index + 1}"}
            for index, chunk in enumerate(chunks[:4])
        ]
        script = {"title": f"{name} 60 秒讲透", "narration": fallback_narration,
                  "scenes": source_scenes or [
                      {"t": "0-12s", "visual": f"识别{name}中的对象", "caption": "认识对象"},
                      {"t": "12-24s", "visual": "展示对象之间的关键关系", "caption": "建立结构"},
                      {"t": "24-40s", "visual": "逐步执行核心规则", "caption": "走完过程"},
                      {"t": "40-60s", "visual": "对比正常情况与边界情况", "caption": "检查边界"},
                  ],
                  "video_prompt": f"educational 2D animation explaining {kp}, clean diagram style"}
    script = _normalize_script(script, chunks, name)
    await emit({"type": "progress", "agent": "media", "stage": "script", "percent": 25,
                "detail": f"分镜脚本就绪,共 {len(script.get('scenes', []))} 个镜头"})

    payload: dict = {
        "script": script,
        "prompt_skill": video_prompt_call.metadata(),
        "animation_mode": explicit_kind,
        "animation_preview": _animation_preview(name, script),
    }
    trace_id = str(state.get("session_id", ""))

    async def on_progress(p: dict):
        await emit({"type": "progress", "agent": "media", "stage": "video",
                    "percent": 25 + int(p.get("percent", 0) * 0.6),
                    "detail": p.get("detail", "视频生成中…"), "task_id": p.get("task_id")})

    mode = explicit_kind if explicit_kind != "video" else "manim"
    if explicit_kind == "video":
        try:
            created = await multimodal_gateway.video_create(
                _video_prompt(script, source_bound=bool(source_ids)), trace_id=trace_id,
            )
            if created["ok"]:
                task_id = str(created["data"]["task_id"])
                provider = str(created["data"].get("provider") or "video")
                waited = await multimodal_gateway.video_wait(
                    task_id,
                    on_progress=on_progress,
                    trace_id=trace_id,
                )
                payload["video"] = waited["data"]
                if waited["ok"]:
                    mode = provider
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
        if source_ids or custom_topic or is_demo():
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

    audio, cover = await asyncio.gather(
        multimodal_gateway.tts(script["narration"][:360], trace_id=trace_id),
        multimodal_gateway.text_to_image(
            f"学习资料主题封面插画:{name},蓝橙科技风,简洁抽象示意图,不添加事实性标签",
            trace_id=trace_id,
        ),
        return_exceptions=True,
    )
    if isinstance(audio, dict) and audio.get("ok"):
        payload["audio_url"] = audio["data"]["audio_url"]
    if isinstance(cover, dict) and cover.get("ok"):
        payload["cover_url"] = cover["data"]["image_url"]
    await emit({"type": "progress", "agent": "media", "stage": "post", "percent": 100,
                "detail": "旁白与封面处理完成"
                if (isinstance(audio, dict) and audio.get("ok"))
                or (isinstance(cover, dict) and cover.get("ok"))
                else "旁白与封面不可用,已保留讲解脚本"})

    rid = uuid.uuid4().hex[:12]
    title_suffix = {
        "manim": "Manim 数学动画",
        "python_animation": "Python 数学动画",
        "video": "讲解视频",
    }[explicit_kind]
    resource = {"id": rid, "kind": explicit_kind, "kp": kp,
                "title": f"{name}·{title_suffix}",
                "payload": {**payload, "topic_label": name, "custom_topic": custom_topic},
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
