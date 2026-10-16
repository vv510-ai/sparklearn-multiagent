"""SparkLearn 文本大模型统一封装(OpenAI 兼容接口)。

要点(与官方文档一致):
- 通用语言模型 base_url = https://spark-api-open.xf-yun.com/v1/ ,端点 /v1/chat/completions;
  model 取值:4.0 Ultra="4.0Ultra"、Max="generalv3.5"、Pro="generalv3"、Lite="lite"。
- 深度推理 X 系列走独立路径 base_url = .../x2/ ,model="spark-x",支持 thinking 字段。
- 鉴权:Authorization: Bearer {APIPassword}(单一 APIPassword,无需 HMAC)。

工程化设计:
- 全项目仅通过 llm_complete()/llm_stream() 两个函数访问大模型,便于:
  ① DeepSeek-V4-Pro 与星火按配置选择;② 无密钥时切换 MockEngine;③ 统一计量与日志。
- 同时提供 get_spark_llm() 返回 LangChain ChatOpenAI,供需要 LangChain 生态的扩展使用。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import AsyncIterator, Iterable

from ..config import get_settings, is_demo
from . import openai_client
from . import personal_subscription

log = logging.getLogger("sparklearn.llm")

# 角色 → (model, 走 X2 路径?) ;Max 套餐 2026-03 起并入 Ultra,保留映射做兼容互备
MODELS: dict[str, tuple[str, bool]] = {
    "ultra": ("4.0Ultra", False),     # 主力生成/对话
    "max": ("generalv3.5", False),    # 历史兼容,限流互备
    "pro": ("generalv3", False),
    "lite": ("lite", False),          # 永久免费:画像抽取/分类/标签等高频低算力任务
    "reasoner": ("spark-x", True),    # 深度推理 X2:算法推导、路径规划、grounding 校验
}
_FALLBACK_ORDER = ["ultra", "max", "pro", "lite"]


def active_provider() -> str:
    """Resolve the server-side provider without ever exposing credentials."""
    if personal_subscription.enabled():
        return "personal_subscription"
    settings = get_settings()
    requested = str(settings.llm_provider or "auto").strip().lower()
    if requested == "openai":
        return "openai"
    if requested == "deepseek":
        return "deepseek"
    if requested == "kimi":
        return "kimi"
    if requested == "spark":
        return "spark"
    if requested != "auto":
        raise ValueError("Unsupported LLM_PROVIDER")
    if getattr(settings, "openai_api_key", ""):
        return "openai"
    if settings.deepseek_api_key:
        return "deepseek"
    if settings.kimi_api_key:
        return "kimi"
    return "spark"


def active_llm_label() -> str:
    if personal_subscription.enabled():
        return "本人本机订阅（Kimi Code / ChatGPT Codex）"
    if is_demo():
        return "MockEngine（离线演示）"
    settings = get_settings()
    if active_provider() == "deepseek":
        return f"{settings.deepseek_model}（深度思考）"
    if active_provider() == "openai":
        return settings.openai_text_model
    if active_provider() == "kimi":
        return settings.kimi_model
    return "讯飞星火 X2（自动深度思考）"


def _reasoning_extra(x2: bool) -> dict:
    if not x2:
        return {}
    mode = (get_settings().spark_reasoning_mode or "auto").lower()
    if mode not in {"enabled", "disabled", "auto"}:
        mode = "auto"
    return {"extra_body": {"thinking": {"type": mode}}}


def _is_unrecoverable_auth_error(error: Exception) -> bool:
    """同一应用鉴权失效时无需重复请求所有同源模型。"""
    detail = str(error)
    return "AppIdNoAuthError" in detail or "'code': '11200'" in detail


def _client(x2: bool):
    """惰性创建 openai 客户端(讯飞 OpenAI 兼容)。"""
    from openai import OpenAI  # 局部导入,便于无依赖环境跑 Mock

    s = get_settings()
    base = s.spark_x2_base_url if x2 else s.spark_base_url
    return OpenAI(api_key=s.spark_api_password, base_url=base)


def _deepseek_client():
    """Create the official DeepSeek OpenAI-compatible client lazily."""
    from openai import OpenAI

    settings = get_settings()
    return OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        timeout=180.0,
        max_retries=1,
    )


def _deepseek_extra(*, thinking_override: str = "") -> dict:
    settings = get_settings()
    thinking = str(thinking_override or settings.deepseek_thinking or "enabled").strip().lower()
    if thinking not in {"enabled", "disabled"}:
        thinking = "enabled"
    effort = str(settings.deepseek_reasoning_effort or "high").strip().lower()
    if effort not in {"high", "max"}:
        effort = "high"
    return {
        "extra_body": {
            "thinking": {"type": thinking},
            "reasoning_effort": effort,
        }
    }


def _kimi_route() -> dict:
    settings = get_settings()
    if not settings.kimi_api_key:
        raise RuntimeError("KIMI_API_KEY is not configured")
    return {"provider": "kimi", "model": settings.kimi_model,
            "base_url": settings.kimi_base_url, "key": settings.kimi_api_key}


def _kimi_reasoning(role: str, max_tokens: int | None, mode: str) -> str:
    if mode:
        return mode
    # Small classifiers keep their short final-answer budget; deeper roles think.
    return "enabled" if role == "reasoner" and (not max_tokens or max_tokens >= 1600) else ""


def get_spark_llm(role: str = "ultra", streaming: bool = True, temperature: float = 0.7):
    """返回当前统一文本主脑的 LangChain ChatOpenAI 实例(扩展用)。"""
    if personal_subscription.enabled():
        raise RuntimeError("订阅模式请经 llm_complete / llm_stream 调用。")
    from langchain_openai import ChatOpenAI

    s = get_settings()
    if active_provider() == "openai":
        return ChatOpenAI(model=s.openai_text_model, api_key=s.openai_api_key,
                          base_url=s.openai_base_url, streaming=streaming,
                          use_responses_api=True, reasoning={"effort": s.openai_reasoning_effort})
    if active_provider() == "kimi":
        from .selected_model import _request
        params = _request(_kimi_route(), [], None, False, _kimi_reasoning(role, None, ""))
        params.pop("messages")
        return ChatOpenAI(api_key=s.kimi_api_key, base_url=s.kimi_base_url,
                          streaming=streaming, timeout=s.kimi_timeout_s, max_retries=0, **params)
    if active_provider() == "deepseek":
        return ChatOpenAI(
            model=s.deepseek_model,
            api_key=s.deepseek_api_key,
            base_url=s.deepseek_base_url,
            streaming=streaming,
            temperature=temperature,
            model_kwargs=_deepseek_extra()["extra_body"],
        )
    model, x2 = MODELS[role]
    base = s.spark_x2_base_url if x2 else s.spark_base_url
    return ChatOpenAI(model=model, api_key=s.spark_api_password, base_url=base,
                      streaming=streaming, temperature=temperature,
                      **_reasoning_extra(x2))


# --------------------------------------------------------------------------
# 统一出入口
# --------------------------------------------------------------------------
from ..services.generation_jobs import durable_call, durable_stream

@durable_call("llm_complete")
async def llm_complete(prompt: str, *, role: str = "ultra", system: str = "",
                       temperature: float = 0.7, json_mode: bool = False,
                       max_tokens: int | None = None,
                       reasoning_mode: str = "", json_object: bool = False,
                       allow_model_fallback: bool = True,
                       allow_mock_fallback: bool = True) -> str:
    """非流式补全。json_mode=True 时尽力让模型只回 JSON 并做容错解析前清洗。"""
    if personal_subscription.enabled():
        return await personal_subscription.complete(prompt, system=system, json_mode=json_mode or json_object)
    from ..services.model_preferences import resolve
    route = resolve(prompt)
    if route:
        from .selected_model import complete
        selected_messages = ([{"role": "system", "content": system}] if system else [])
        selected_messages.append({"role": "user", "content": prompt + ("\n只输出有效 JSON。" if json_mode or json_object else "")})
        return await complete(route, selected_messages, max_tokens=max_tokens, json_object=json_object, reasoning_mode=reasoning_mode)
    if is_demo():
        return MockEngine.complete(prompt, role=role, json_mode=json_mode)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    if json_mode or json_object:
        prompt += "\n\n只输出 JSON,不要 Markdown 围栏,不要任何解释。"
    messages.append({"role": "user", "content": prompt})
    token_extra = {"max_tokens": max_tokens} if max_tokens else {}

    last_err: Exception | None = None
    provider = active_provider()
    if provider == "kimi":
        from .selected_model import complete
        return await complete(_kimi_route(), messages, max_tokens=max_tokens, json_object=json_object,
                              reasoning_mode=_kimi_reasoning(role, max_tokens, reasoning_mode))
    if provider == "openai":
        # Never pass mock lessons off as an answer from the selected model.
        try:
            def complete_openai():
                with openai_client.client() as client:
                    params = openai_client.response_params(messages, max_tokens=max_tokens, reasoning_mode=reasoning_mode)
                    if json_object:
                        params["text"] = {"format": {"type": "json_object"}}
                    response = client.responses.create(**params)
                    if getattr(response, "status", "completed") != "completed" or not response.output_text:
                        raise RuntimeError("Incomplete or empty OpenAI response")
                    return response.output_text
            return await asyncio.to_thread(complete_openai)
        except Exception as error:
            raise RuntimeError("OpenAI 调用失败：" + openai_client.error_label(error)) from None
    if provider == "deepseek":
        settings = get_settings()
        # Thinking tokens share the completion budget. Small structured helper
        # calls would otherwise spend their entire 260/1200-token allowance on
        # reasoning and return empty final content. They still use V4-Pro, just
        # in its official non-thinking mode.
        thinking_override = (reasoning_mode if reasoning_mode in {"enabled", "disabled"}
                             else "disabled" if max_tokens and max_tokens < 1600 else "")
        try:
            resp = await asyncio.to_thread(
                lambda: _deepseek_client().chat.completions.create(
                    model=settings.deepseek_model,
                    messages=messages,
                    temperature=temperature,
                    stream=False,
                    **({"response_format": {"type": "json_object"}} if json_object else {}),
                    **token_extra,
                    **_deepseek_extra(thinking_override=thinking_override),
                )
            )
            content = resp.choices[0].message.content or ""
            if json_object and (getattr(resp.choices[0], "finish_reason", "stop") != "stop" or not content.strip()):
                raise RuntimeError("Incomplete structured model response")
            return content
        except Exception as error:  # noqa: BLE001
            last_err = error
            log.warning("DeepSeek %s 调用失败:%s", settings.deepseek_model, openai_client.error_label(error))
            if not allow_model_fallback:
                raise RuntimeError("DeepSeek 调用失败：" + openai_client.error_label(error)) from None
            if not settings.spark_api_password:
                if not allow_mock_fallback:
                    raise RuntimeError(f"DeepSeek 模型调用失败: {error}") from error
                return MockEngine.complete(prompt, role=role, json_mode=json_mode)
            log.warning("DeepSeek 不可用，按服务端降级策略尝试星火")

    order = ([role] + [r for r in _FALLBACK_ORDER if r != role] if role != "reasoner" else [role, "ultra", "lite"]) if allow_model_fallback else [role]
    for r in order:  # 限流/故障时按序互备(对应方案"降级策略")
        model, x2 = MODELS[r]
        extra = {**token_extra, **_reasoning_extra(x2)}
        try:
            resp = await asyncio.to_thread(
                lambda: _client(x2).chat.completions.create(
                    model=model, messages=messages, temperature=temperature,
                    stream=False, **extra)
            )
            return resp.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.warning("spark %s 调用失败,尝试下一档:%s", r, e)
            if r != "reasoner" and _is_unrecoverable_auth_error(e):
                break
    log.warning("星火模型不可用,切换本地演示引擎:%s", last_err)
    if not allow_mock_fallback:
        raise RuntimeError(f"星火全部档位调用失败: {last_err}")
    return MockEngine.complete(prompt, role=role, json_mode=json_mode)


@durable_stream
async def llm_stream(prompt: str, *, role: str = "ultra", system: str = "",
                     temperature: float = 0.7,
                     max_tokens: int | None = None,
                     reasoning_mode: str = "",
                     task_context: dict | None = None,
                     allow_model_fallback: bool = True,
                     allow_mock_fallback: bool = True) -> AsyncIterator[str]:
    """流式补全,逐 token 产出(SSE 直接转发)。"""
    if personal_subscription.enabled():
        text = await personal_subscription.complete(prompt, system=system, task_context=task_context)
        for offset in range(0, len(text), 64):
            yield text[offset:offset + 64]
        return
    from ..services.model_preferences import resolve
    route = resolve(prompt, task_context=task_context) if task_context is not None else resolve(prompt)
    if route and route["provider"] == "kimi":
        from .selected_model import stream
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
        async for delta in stream(route, messages, max_tokens=max_tokens, reasoning_mode=reasoning_mode):
            yield delta
        return
    if route:
        # Buffer and validate explicit selections before displaying any content.
        text = await llm_complete(prompt, role=role, system=system, temperature=temperature,
                                  max_tokens=max_tokens, reasoning_mode=reasoning_mode,
                                  allow_mock_fallback=False, allow_model_fallback=False)
        for start in range(0, len(text), 64):
            yield text[start:start + 64]
        return
    if is_demo():
        async for d in MockEngine.stream(prompt, role=role):
            yield d
        return
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
    token_extra = {"max_tokens": max_tokens} if max_tokens else {}
    order = (
        ([role] + [r for r in _FALLBACK_ORDER if r != role] if role != "reasoner" else [role, "ultra", "lite"])
        if allow_model_fallback
        else [role]
    )
    last_err: Exception | None = None
    loop = asyncio.get_running_loop()

    provider = active_provider()
    if provider == "kimi":
        from .selected_model import stream
        async for delta in stream(_kimi_route(), messages, max_tokens=max_tokens,
                                  reasoning_mode=_kimi_reasoning(role, max_tokens, reasoning_mode)):
            yield delta
        return
    if provider == "openai":
        client = openai_client.client()
        stream = None
        completed = False
        emitted = False
        try:
            stream = await asyncio.to_thread(lambda: client.responses.create(
                **openai_client.response_params(messages, max_tokens=max_tokens, reasoning_mode=reasoning_mode),
                stream=True))
            iterator = iter(stream)
            while True:
                event = await asyncio.to_thread(lambda: next(iterator, None))
                if event is None:
                    break
                if event.type == "response.output_text.delta":
                    emitted = emitted or bool(event.delta)
                    yield event.delta
                elif event.type == "response.completed":
                    completed = True
                elif event.type in {"response.failed", "response.incomplete", "error"}:
                    raise RuntimeError("Incomplete OpenAI stream")
            if not completed or not emitted:
                raise RuntimeError("OpenAI stream ended before completion")
            return
        except Exception as error:
            raise RuntimeError("OpenAI 流式调用失败：" + openai_client.error_label(error)) from None
        finally:
            if stream is not None:
                await asyncio.to_thread(stream.close)
            await asyncio.to_thread(client.close)
    if provider == "deepseek":
        settings = get_settings()
        client = _deepseek_client()
        thinking_override = (
            reasoning_mode
            if reasoning_mode in {"enabled", "disabled"}
            else "disabled" if max_tokens and max_tokens < 1600 else ""
        )

        def _create_deepseek():
            return client.chat.completions.create(
                model=settings.deepseek_model,
                messages=messages,
                temperature=temperature,
                stream=True,
                **token_extra,
                **_deepseek_extra(thinking_override=thinking_override),
            )

        try:
            stream = await asyncio.to_thread(_create_deepseek)
            iterator = iter(stream)
            emitted = False
            while True:
                chunk = await loop.run_in_executor(None, lambda: next(iterator, None))
                if chunk is None:
                    break
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta_obj = getattr(choices[0], "delta", None)
                delta = getattr(delta_obj, "content", None) or ""
                if delta:
                    emitted = True
                    yield delta
            if emitted:
                return
            last_err = RuntimeError("DeepSeek stream returned empty")
        except Exception as error:  # noqa: BLE001
            last_err = error
            log.warning("DeepSeek %s 流式调用失败:%s", settings.deepseek_model, error)
        if not settings.spark_api_password or not allow_model_fallback:
            if not allow_mock_fallback:
                raise RuntimeError(f"DeepSeek 流式模型调用失败: {last_err}") from last_err
            async for delta in MockEngine.stream(prompt, role=role):
                yield delta
            return
        log.warning("DeepSeek 流式调用不可用，按服务端降级策略尝试星火")

    for r in order:
        model, x2 = MODELS[r]
        client = _client(x2)
        if x2 and reasoning_mode in {"enabled", "disabled", "auto"}:
            reasoning_extra = {"extra_body": {"thinking": {"type": reasoning_mode}}}
        else:
            reasoning_extra = _reasoning_extra(x2)
        extra = {**token_extra, **reasoning_extra}

        def _create():
            return client.chat.completions.create(
                model=model, messages=messages, temperature=temperature,
                stream=True, **extra)

        try:
            stream = await asyncio.to_thread(_create)
            it = iter(stream)
            emitted = False
            while True:
                chunk = await loop.run_in_executor(None, lambda: next(it, None))
                if chunk is None:
                    break
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta_obj = getattr(choices[0], "delta", None)
                delta = getattr(delta_obj, "content", None) or ""
                if delta:
                    emitted = True
                    yield delta
            if emitted:
                return
            last_err = RuntimeError(f"spark stream {r} returned empty")
            log.warning("spark stream %s 返回空,尝试下一档", r)
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.warning("spark stream %s 调用失败,尝试下一档:%s", r, e)
            if r != "reasoner" and _is_unrecoverable_auth_error(e):
                break
    log.warning("星火流式模型不可用,切换本地演示引擎:%s", last_err)
    if not allow_mock_fallback:
        raise RuntimeError(f"星火流式模型调用失败: {last_err}")
    async for delta in MockEngine.stream(prompt, role=role):
        yield delta


def parse_json(text: str) -> dict | list:
    """LLM JSON 输出的健壮解析:剥围栏、按先出现的 {..}/[..] 截取、宽松修复。"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    i_obj, i_arr = text.find("{"), text.find("[")
    pairs = [("{", "}"), ("[", "]")]
    if i_arr >= 0 and (i_obj < 0 or i_arr < i_obj):
        pairs.reverse()                                   # 顶层数组优先
    for opener, closer in pairs:
        i = text.find(opener)
        if i >= 0:
            depth = 0
            for j in range(i, len(text)):
                if text[j] == opener:
                    depth += 1
                elif text[j] == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[i:j + 1])
                        except json.JSONDecodeError:
                            break
    return json.loads(text)  # 最后一搏,失败抛错由上层兜底


# --------------------------------------------------------------------------
# MockEngine:离线演示引擎(无密钥也能完整跑通五大功能,内容明确标注"演示数据")
# --------------------------------------------------------------------------
class MockEngine:
    """根据提示词中的任务标记返回结构合理的演示内容;流式按字切片模拟打字机。"""

    @staticmethod
    def complete(prompt: str, *, role: str = "ultra", json_mode: bool = False) -> str:
        p = prompt
        if "TASK=intent" in p:
            match = re.search(r"用户消息:(.*?)(?:\n学习目标|$)", p, flags=re.S)
            user_text = match.group(1).strip() if match else p
            for kw, intent in (
                ("整理", "summary"), ("总结", "summary"), ("个人笔记", "summary"),
                ("从零", "learn"), ("零基础", "learn"), ("入门", "learn"), ("我想学", "learn"),
                ("出题", "generate"), ("生成", "generate"), ("资源", "generate"),
                ("学习路径", "generate"), ("评估", "eval"), ("测", "eval"),
                ("为什么", "tutor"), ("怎么", "tutor"), ("?", "tutor"), ("？", "tutor"),
            ):
                if kw in user_text:
                    return json.dumps({"intent": intent, "reason": f"命中关键词「{kw}」(演示规则)"},
                                      ensure_ascii=False)
            return json.dumps({"intent": "chat", "reason": "默认闲聊(演示规则)"}, ensure_ascii=False)
        if "TASK=profile" in p:
            return json.dumps({
                "cognitive_style": "视觉型", "goal": "应试",
                "pace": {"daily_minutes": 45, "frequency": "每天", "focus": "中"},
                "difficulty_pref": "循序渐进",
                "error_prone": ["递归边界条件", "复杂度误判"],
                "resource_pref": {"doc": 0.3, "video": 0.35, "quiz": 0.2, "mindmap": 0.1, "code": 0.05},
                "metacognition": 0.55,
                "evidence": "演示模式:基于内置启发式抽取",
            }, ensure_ascii=False)
        if "TASK=plan" in p:
            return json.dumps({"resources": [
                {"kind": "doc", "kp": "binary_tree", "reason": "视觉型+应试:先建立系统讲解"},
                {"kind": "mindmap", "kp": "binary_tree", "reason": "知识体系结构化"},
                {"kind": "quiz", "kp": "binary_tree", "reason": "针对易错点(递归边界)出题"},
                {"kind": "code", "kp": "binary_tree", "reason": "代码实操案例为课程主角"},
                {"kind": "video", "kp": "binary_tree", "reason": "遍历过程动态演示"},
            ], "order": "doc→mindmap→quiz→code→video"}, ensure_ascii=False)
        if "TASK=grounding" in p:
            return json.dumps({"grounded": True, "unsupported": [],
                               "verdict": "演示模式:答案各要点均能在给定资料中找到出处"},
                              ensure_ascii=False)
        if "TASK=quiz" in p and "MODE=guided" in p:
            return json.dumps([
                {"type": "single", "difficulty": 1, "kp": "binary_tree",
                 "stem": "普通二叉树中的一个节点最多可以有几个孩子?",
                 "options": ["1 个", "2 个", "3 个", "没有限制"],
                 "answer": "B", "explanation": "二叉树的每个节点至多有两个孩子,并区分左、右。",
                 "error_tags": ["基本定义"]},
                {"type": "single", "difficulty": 1, "kp": "binary_tree",
                 "stem": "下面哪一项是普通二叉树必然具有的性质?",
                 "options": ["左边都更小", "右边都更大", "每个节点至多两个孩子", "每层都必须填满"],
                 "answer": "C", "explanation": "大小顺序属于二叉搜索树等特殊类型,不是普通二叉树的要求。",
                 "error_tags": ["概念边界"]},
                {"type": "judge", "difficulty": 1, "kp": "binary_tree",
                 "stem": "普通二叉树一定满足左边的值小于右边的值。", "answer": "错",
                 "explanation": "普通二叉树只限制孩子数量;有序性质需要额外条件。",
                 "error_tags": ["二叉树与BST混淆"]},
                {"type": "fill", "difficulty": 1, "kp": "binary_tree",
                 "stem": "二叉树的两个孩子通常区分为左孩子和 ____ 孩子。",
                 "answer": "右", "explanation": "二叉树不仅至多有两个孩子,还区分左右位置。",
                 "error_tags": ["基本定义"]},
                {"type": "design", "difficulty": 2, "kp": "binary_tree",
                 "stem": "用一句话说出普通二叉树和二叉搜索树的区别。",
                 "answer": "二叉树只限制每个节点至多两个孩子;二叉搜索树还增加左小右大的有序条件。",
                 "explanation": "先记通用结构,再记特殊类型额外增加的规则。",
                 "error_tags": ["概念边界"]},
            ], ensure_ascii=False)
        if "TASK=quiz" in p:
            return json.dumps([
                {"type": "single", "difficulty": 2, "kp": "binary_tree",
                 "stem": "对一棵二叉搜索树进行哪种遍历可得到升序序列?",
                 "options": ["前序遍历", "中序遍历", "后序遍历", "层序遍历"],
                 "answer": "B", "explanation": "BST 左<根<右,中序(左根右)即升序。",
                 "error_tags": ["遍历次序混淆"]},
                {"type": "fill", "difficulty": 3, "kp": "binary_tree",
                 "stem": "n 个结点的二叉树共有 ____ 个空指针域(用 n 表示)。",
                 "answer": "n+1", "explanation": "2n 个指针域,n-1 条边占用 n-1 个,余 n+1。",
                 "error_tags": ["计数边界"]},
                {"type": "judge", "difficulty": 1, "kp": "binary_tree",
                 "stem": "完全二叉树一定是满二叉树。", "answer": "错",
                 "explanation": "满二叉树是完全二叉树的特例,反之不成立。",
                 "error_tags": ["概念混淆"]},
                {"type": "design", "difficulty": 4, "kp": "binary_tree",
                 "stem": "设计算法判断二叉树是否为 BST,给出思路与复杂度。",
                 "answer": "中序遍历检查严格递增;或递归传 (low,high) 区间。O(n) 时间 O(h) 空间。",
                 "explanation": "易错:仅比较父子结点会漏判跨层违例,必须用区间约束。",
                 "error_tags": ["递归边界条件"]},
                {"type": "complexity", "difficulty": 3, "kp": "binary_tree",
                 "stem": "高度为 h 的平衡 BST 上查找的时间复杂度是?",
                 "options": ["O(1)", "O(log n)", "O(n)", "O(n log n)"],
                 "answer": "B", "explanation": "平衡时 h=O(log n),沿单条路径下行。",
                 "error_tags": ["复杂度误判"]},
            ], ensure_ascii=False)
        if "TASK=mindmap" in p:
            return ("# 二叉树\n## 基本概念\n### 结点/度/深度/高度\n### 满二叉树 vs 完全二叉树\n"
                    "## 存储结构\n### 顺序存储(完全二叉树友好)\n### 链式存储(lchild/rchild)\n"
                    "## 遍历\n### 前序(根左右)\n### 中序(左根右)⭐BST 升序\n### 后序(左右根)\n### 层序(队列)\n"
                    "## 二叉搜索树\n### 性质:左<根<右\n### 查找/插入/删除\n### 退化为链表→平衡树\n"
                    "## 易错点\n### 递归边界条件\n### 空指针域计数 n+1\n### 仅比父子≠BST")
        if "TASK=video_script" in p:
            return json.dumps({
                "title": "90 秒看懂二叉树中序遍历",
                "shots": [
                    {"t": "0-15s", "visual": "结点逐个亮起组成一棵 BST", "narration": "这是一棵二叉搜索树,左小右大。"},
                    {"t": "15-45s", "visual": "指针沿 左-根-右 路径游走,访问到的结点变橙色并落入底部序列",
                     "narration": "中序遍历:先走到最左,再回根,再向右。"},
                    {"t": "45-75s", "visual": "底部序列高亮显示为升序 1,3,4,6,7,8,10",
                     "narration": "于是 BST 的中序遍历天然有序——这是它最重要的性质。"},
                    {"t": "75-90s", "visual": "弹出易错提示卡:递归别忘了空结点返回",
                     "narration": "写递归时,空结点直接返回,这是最常错的边界。"}],
                "style": "扁平科技风,深空蓝底+星火橙高亮",
            }, ensure_ascii=False)
        if "TASK=doc" in p or json_mode is False and "讲解文档" in p:
            return MockEngine._doc()
        if "TASK=tutor" in p and "MODE=guided" in p and "二叉树" in p:
            return (
                "可以，我们先不背整页定义。把二叉树想成一张向下展开的小家谱：每个节点最多只分出左、右两个位置，"
                "而且“最多两个”也包括没有孩子或只有一个孩子 [^1]。\n\n"
                "比如 A 是最上面的根节点，B 在 A 的左边，C 在 A 的右边，这就是一棵只有 3 个节点的二叉树。"
                "删掉 C 后它仍然是二叉树，因为节点不必同时拥有两个孩子。\n\n"
                "有个很容易混淆的地方：**普通二叉树没有大小顺序**；“左小右大”是二叉搜索树额外增加的规则 [^2]。\n\n"
                "先记住这一句就够了：**每个节点最多两个孩子，而且区分左、右位置。**"
                "我问你一个小问题确认一下：一个节点只有右孩子，它还能出现在二叉树里吗？"
            )
        if "TASK=tutor" in p:
            return ("中序遍历 BST 得到升序序列,核心在于 BST 的不变量:对任意结点,左子树所有键 < 根键 < 右子树所有键 "
                    "[^1]。中序按「左→根→右」访问,递归展开后恰好把所有键按该不变量从小到大串起来 [^2]。"
                    "复杂度:每个结点恰被访问一次,时间 O(n);递归栈深为树高 h,空间 O(h) [^1]。"
                    "易错提醒:验证 BST 不能只比较父子结点,必须携带 (low, high) 区间下推 [^2]。")
        # 默认:简短聊天
        return "(演示模式)收到!我可以为你构建学习画像、生成五类资源、规划路径或答疑。试试:「帮我生成二叉树的学习资源」。"

    @staticmethod
    def _doc() -> str:
        return (
            "# 二叉树与二叉搜索树精讲\n\n"
            "> 本文档由 Doc Agent 生成,所有关键论断均标注知识库出处。\n\n"
            "## 1. 为什么需要树\n"
            "线性结构(数组/链表)在「有序数据的动态查找」上难两全:数组查找 O(log n) 但插入 O(n),"
            "链表插入 O(1) 但查找 O(n) [^1]。二叉搜索树把两者折中到 O(h) [^2]。\n\n"
            "## 2. 基本概念\n"
            "结点的度、深度、高度;满二叉树与完全二叉树的区别——完全二叉树只要求最后一层靠左连续 [^2]。\n"
            "**性质**:n 个结点的二叉链表共有 n+1 个空指针域(2n−(n−1)) [^2]。\n\n"
            "## 3. 遍历\n"
            "前序(根左右)、中序(左根右)、后序(左右根)、层序(借助队列) [^2]。\n"
            "**核心结论**:BST 的中序遍历是升序序列 [^2]。\n\n"
            "```python\n"
            "def inorder(root, out):\n"
            "    if root is None:      # 易错:空结点边界必须先判\n"
            "        return\n"
            "    inorder(root.left, out)\n"
            "    out.append(root.val)\n"
            "    inorder(root.right, out)\n"
            "```\n\n"
            "## 4. 二叉搜索树操作\n"
            "查找/插入沿一条根到叶路径,O(h);删除分 0/1/2 孩子三种情形,2 孩子用中序后继顶替 [^2]。\n"
            "**退化警告**:有序插入会让 BST 退化为链表,h=n,引出 AVL/红黑树的平衡需求 [^2]。\n\n"
            "## 5. 易错点清单\n"
            "1. 递归忘记空结点返回(边界条件)[^2];\n"
            "2. 验证 BST 只比较父子结点——必须用 (low, high) 区间 [^2];\n"
            "3. 把「完全」当「满」;\n"
            "4. 复杂度按最好情况想当然(平均 O(log n) ≠ 最坏 O(log n))[^1]。\n"
        )

    @staticmethod
    async def stream(prompt: str, *, role: str = "ultra") -> AsyncIterator[str]:
        text = MockEngine.complete(prompt, role=role)
        step = 6
        for i in range(0, len(text), step):
            yield text[i:i + step]
            await asyncio.sleep(0.012)  # 模拟网络节奏,前端打字机效果
