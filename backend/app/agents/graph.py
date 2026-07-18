"""多智能体编排图(LangGraph StateGraph):
START → profile → orchestrator ─┬─ generate → planner → path → [doc ∥ mindmap ∥ quiz ∥ media] → eval → END
                                ├─ tutor/chat → tutor → END
                                └─ eval → eval → END
- 条件边由 Orchestrator 的意图识别(X2)驱动;
- 生成类资源四节点并行 fan-out,State 的 Annotated reducer 负责无冲突合并,Eval fan-in;
- 环境未装 langgraph 时退化为内置 MiniGraph(asyncio.gather 等价并行语义),保证离线可跑;
- run_with_events():把图执行包装为异步事件流(供 SSE),通过 contextvar Emitter 收集
  所有 agent_start/token/resource/... 事件,图跑完发 done 哨兵。"""
from __future__ import annotations

import asyncio
import datetime as dt
import traceback
import uuid
from typing import Any, AsyncIterator

from . import (conversation_note_agent, doc_agent, eval_agent, guided_agent,
               media_agent, mindmap_agent, orchestrator, path_agent,
               planner_agent, profile_agent, quiz_agent, tutor_agent)
from .emitter import agent_end, emit, reset_emitter, set_emitter
from .state import LearningState, merge_dict
from ..trace import TraceRecorder

_GEN_NODES = {"doc": doc_agent.run, "mindmap": mindmap_agent.run,
              "quiz": quiz_agent.run, "media": media_agent.run}

try:
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
    _HAS_LANGGRAPH = True
except Exception:                                          # pragma: no cover
    _HAS_LANGGRAPH = False


# ============================ LangGraph 构图 ============================
def _guard_gen_node(name: str, fn):
    async def guarded(state: dict) -> dict:
        try:
            return await fn(state)
        except Exception as exc:  # noqa: BLE001
            detail = "".join(traceback.format_exception_only(exc)).strip()
            await emit({"type": "error", "agent": name, "detail": detail})
            await agent_end(name, f"生成失败,已跳过:{detail[:120]}", {"error": detail})
            return {"safety_flags": [{"agent": name, "type": "error", "detail": detail}]}

    return guarded


def _build_langgraph():
    g = StateGraph(LearningState)
    g.add_node("profile", profile_agent.run)
    g.add_node("orchestrator", orchestrator.run)
    g.add_node("planner", planner_agent.run)
    g.add_node("path", path_agent.run)
    for name, fn in _GEN_NODES.items():
        g.add_node(name, _guard_gen_node(name, fn))
    g.add_node("eval", eval_agent.run)
    g.add_node("tutor", tutor_agent.run)
    g.add_node("guided", guided_agent.run)
    g.add_node("conversation_note", conversation_note_agent.run)

    g.add_edge(START, "profile")
    g.add_edge("profile", "orchestrator")
    g.add_conditional_edges("orchestrator", orchestrator.route_task,
                            {"learn": "guided", "summary": "conversation_note",
                             "generate": "planner", "tutor": "tutor", "eval": "eval"})
    g.add_edge("planner", "path")
    for name in _GEN_NODES:                                # fan-out:path 后四节点并行
        g.add_edge("path", name)
        g.add_edge(name, "eval")                           # fan-in:eval 等四者全部完成
    g.add_edge("eval", END)
    g.add_edge("tutor", END)
    g.add_edge("guided", END)
    g.add_edge("conversation_note", END)
    return g.compile(checkpointer=MemorySaver())


# ============================ MiniGraph 兜底 ============================
class MiniGraph:
    """LangGraph 不可用时的等价实现:同拓扑、同 reducer 语义、asyncio.gather 真并行。"""

    async def ainvoke(self, state: dict, config: dict | None = None) -> dict:
        s = dict(state)

        def absorb(patch: dict | None):
            for k, v in (patch or {}).items():
                if k in ("generated_resources",):
                    s[k] = merge_dict(s.get(k), v)
                elif k in ("messages", "retrieval_context", "citations",
                           "safety_flags", "progress_events"):
                    s[k] = (s.get(k) or []) + (v or [])
                else:
                    s[k] = v

        absorb(await profile_agent.run(s))
        absorb(await orchestrator.run(s))
        branch = orchestrator.route_task(s)
        if branch == "learn":
            absorb(await guided_agent.run(s))
            return s
        if branch == "summary":
            absorb(await conversation_note_agent.run(s))
            return s
        if branch == "tutor":
            absorb(await tutor_agent.run(s))
            return s
        if branch == "eval":
            absorb(await eval_agent.run(s))
            return s
        absorb(await planner_agent.run(s))
        absorb(await path_agent.run(s))
        _KIND2NODE = {"doc": "doc", "code": "doc", "reading": "doc", "ppt": "doc",
                      "flashcards": "doc", "infographic": "doc", "data_table": "doc",
                      "mindmap": "mindmap", "quiz": "quiz",
                      "video": "media", "audio": "media", "image": "media",
                      "manim": "media", "python_animation": "media"}
        wanted = [_KIND2NODE[k] for k in (s.get("kinds") or []) if k in _KIND2NODE]
        run_nodes = list(dict.fromkeys(wanted)) or list(_GEN_NODES)
        results = await asyncio.gather(*(_GEN_NODES[n](s) for n in run_nodes),
                                       return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                s["safety_flags"] = (s.get("safety_flags") or []) + [
                    {"type": "error", "detail": "".join(traceback.format_exception_only(r)).strip()}]
            else:
                absorb(r)
        absorb(await eval_agent.run(s))
        return s


_graph = None


def build_graph():
    global _graph
    if _graph is None:
        _graph = _build_langgraph() if _HAS_LANGGRAPH else MiniGraph()
    return _graph


# ============================ SSE 事件桥 ============================
_DONE = {"type": "__done__"}


def _event_ts() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%S.%f")[:-3]


async def run_with_events(state: dict[str, Any]) -> AsyncIterator[dict]:
    """执行编排图并实时产出事件字典流(API 层负责包成 SSE)。"""
    queue: asyncio.Queue[dict] = asyncio.Queue()
    trace = TraceRecorder(state)
    trace_finished = False

    async def emitter(ev: dict):
        await queue.put(ev)

    token = set_emitter(emitter)
    graph = build_graph()
    # 对话由数据库持久化；每次请求使用独立图线程，避免上轮 intent/资源被 MemorySaver 合并进本轮。
    session_id = state.get("session_id", "default")
    cfg = {"configurable": {"thread_id": f"{session_id}:{uuid.uuid4().hex[:10]}"}}

    async def runner():
        try:
            final_state = await graph.ainvoke(state, cfg)
            trace.record_final_state(final_state)
        except Exception as exc:                            # pragma: no cover
            detail = str(exc)[:300]
            trace.record_error(detail)
            await queue.put({"type": "error", "detail": detail})
        finally:
            await queue.put(dict(_DONE))

    await queue.put({
        "type": "trace",
        "session_id": trace.session_id,
        "run_dir": str(trace.run_dir),
        "ts": _event_ts(),
    })
    task = asyncio.create_task(runner())
    try:
        while True:
            ev = await queue.get()
            if ev.get("type") == "__done__":
                done = {"type": "done"}
                trace.record_event(done)
                trace.finish()
                trace_finished = True
                yield done
                break
            trace.record_event(ev)
            yield ev
    finally:
        reset_emitter(token)
        if not task.done():
            task.cancel()
        if not trace_finished:
            trace.finish()
