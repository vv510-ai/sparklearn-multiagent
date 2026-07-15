"""媒体智能体(Media Agent):
1) 星火生成分镜视频脚本(video_script JSON);
2) 首选火山方舟 Seedance 文生视频(异步任务 + progress 事件轮询);
3) 无 Seedance 密钥时优雅降级:生成 Manim 动画场景代码(可本地渲染)+ 讯飞 TTS 旁白音频;
4) 讯飞文生图生成课程封面(可选)。"""
from __future__ import annotations

import asyncio
import ast
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


def _seedance_prompt(script: dict, *, source_bound: bool) -> str:
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


def _local_manim_video(kp: str) -> dict | None:
    filename = _LOCAL_MANIM_VIDEOS.get(kp)
    if not filename or not (GEN_DIR / filename).is_file():
        return None
    return {"status": "succeeded", "url": f"/static/gen/{filename}"}


async def run(state: dict) -> dict:
    requested = state.get("kinds") or []
    if requested and not any(k in requested for k in ("video", "audio", "image")):
        return {}
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
            "kind": "video",
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
        script = {"title": f"{name} 60 秒讲透", "narration": fallback_narration,
                  "scenes": [{"t": "0-60s", "visual": f"{name} 演示动画", "caption": name}],
                  "video_prompt": f"educational 2D animation explaining {kp}, clean diagram style"}
    await emit({"type": "progress", "agent": "media", "stage": "script", "percent": 25,
                "detail": f"分镜脚本就绪,共 {len(script.get('scenes', []))} 个镜头"})

    payload: dict = {"script": script, "prompt_skill": video_prompt_call.metadata()}
    trace_id = str(state.get("session_id", ""))

    async def on_progress(p: dict):
        await emit({"type": "progress", "agent": "media", "stage": "video",
                    "percent": 25 + int(p.get("percent", 0) * 0.6),
                    "detail": p.get("detail", "视频生成中…"), "task_id": p.get("task_id")})

    mode = "manim"
    try:
        created = await multimodal_gateway.video_create(
            _seedance_prompt(script, source_bound=bool(source_ids)), trace_id=trace_id,
        )
        if created["ok"]:
            task_id = str(created["data"]["task_id"])
            waited = await multimodal_gateway.video_wait(
                task_id,
                on_progress=on_progress,
                trace_id=trace_id,
            )
            payload["video"] = waited["data"]
            if waited["ok"]:
                mode = "seedance"
        elif created["data"]:
            payload["video"] = created["data"]
    except Exception:  # noqa: BLE001
        payload["video"] = {"status": "degraded", "reason": "视频服务异常,已切换为脚本讲解"}
        await emit({"type": "progress", "agent": "media", "stage": "video", "percent": 40,
                    "detail": "视频服务异常,已安全切换为脚本与动画代码"})

    if mode == "manim":                                            # 降级链路
        cls = "Scene" + kp.title().replace("_", "")
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
                    "detail": "Seedance 未配置/失败,已使用预渲染 Manim 教学动画"
                    if local_video else "Seedance 未配置/失败,已降级为 Manim 动画代码(可本地渲染)"})

    audio, cover = await asyncio.gather(
        multimodal_gateway.tts(script["narration"][:260], trace_id=trace_id),
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
    resource = {"id": rid, "kind": "video", "kp": kp,
                "title": script.get("title", f"{name}·讲解视频"),
                "payload": {**payload, "topic_label": name, "custom_topic": custom_topic},
                "citations": [item["citation"] for item in citations]}
    await emit({"type": "resource", "resource": resource})
    summaries = {
        "seedance": "Seedance 视频任务已提交",
        "local_manim": "已产出预渲染 Manim 教学动画 + 旁白脚本",
        "manim": "已产出 Manim 动画代码 + 旁白脚本(降级模式)",
    }
    await agent_end("media", summaries[mode], {"id": rid, "mode": mode})
    return {"generated_resources": {rid: resource},
            "progress_events": [{"agent": "media", "mode": mode}]}
