"""Transport for an explicitly selected model; called only by spark_client."""
from __future__ import annotations

import asyncio

from ..config import get_settings
from .openai_client import error_label


def _request(route, messages, max_tokens, json_object, reasoning_mode):
    budget = min(16000, max(2048, max_tokens or 6000))
    if route["provider"] == "openai":
        params = {"model": route["model"], "input": messages, "store": False,
                  "max_output_tokens": budget, "reasoning": {"effort": "low" if reasoning_mode == "disabled" else "high"}}
        if json_object:
            params["text"] = {"format": {"type": "json_object"}}
        return params
    params = {"model": route["model"], "messages": messages}
    if route["provider"] == "kimi":
        settings = get_settings()
        small_call = bool(max_tokens and max_tokens < 1600)
        if route["model"] == "kimi-k3":
            effort = "low" if reasoning_mode == "disabled" or small_call else settings.kimi_reasoning_effort
            if effort not in {"low", "high", "max"}:
                raise ValueError("Invalid KIMI_REASONING_EFFORT")
            params.update(max_completion_tokens=max(4096, budget), reasoning_effort=effort)
        elif route["model"] == "kimi-k2.6":
            thinking = reasoning_mode or ("disabled" if small_call else settings.kimi_thinking)
            if thinking not in {"enabled", "disabled"}:
                raise ValueError("Invalid KIMI_THINKING")
            # Reasoning and final content share the token allowance.
            limit = min(16000, max_tokens or 6000)
            if thinking == "enabled":
                limit = max(4096, limit)
            params.update(max_tokens=limit, extra_body={"thinking": {"type": thinking}})
        else:
            raise ValueError("Unsupported KIMI_MODEL")
    else:
        params.update(max_tokens=budget, extra_body={"thinking": {"type": "disabled" if reasoning_mode == "disabled" or (max_tokens and max_tokens < 1600) else "enabled"}})
    if json_object:
        params["response_format"] = {"type": "json_object"}
    return params


async def complete(route, messages, *, max_tokens=None, json_object=False, reasoning_mode=""):
    from openai import OpenAI
    def run():
        timeout = get_settings().kimi_timeout_s if route["provider"] == "kimi" else 150
        with OpenAI(api_key=route["key"], base_url=route["base_url"], timeout=timeout, max_retries=0) as client:
            params = _request(route, messages, max_tokens, json_object, reasoning_mode)
            if route["provider"] == "openai":
                response = client.responses.create(**params)
                if response.status != "completed":
                    raise RuntimeError("Incomplete response")
                text = response.output_text
            else:
                response = client.chat.completions.create(**params)
                if not response.choices or response.choices[0].finish_reason != "stop":
                    raise RuntimeError("Incomplete response")
                text = response.choices[0].message.content
            if not text or not text.strip():
                raise RuntimeError("Empty response")
            return text
    try:
        return await asyncio.to_thread(run)
    except Exception as exc:
        raise RuntimeError(f"所选模型 {route['model']} 调用失败：{error_label(exc)}；请检查设置或额度") from None


async def stream(route, messages, *, max_tokens=None, reasoning_mode=""):
    """Kimi SSE: display only final-answer deltas, and fail on truncation."""
    from openai import AsyncOpenAI

    if route["provider"] != "kimi":
        raise ValueError("Streaming transport requires Kimi")
    try:
        async with AsyncOpenAI(api_key=route["key"], base_url=route["base_url"],
                               timeout=get_settings().kimi_timeout_s, max_retries=0) as client:
            params = _request(route, messages, max_tokens, False, reasoning_mode)
            response = await client.chat.completions.create(**params, stream=True)
            completed = False
            emitted = False
            async with response:
                async for chunk in response:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    if choice.finish_reason and choice.finish_reason != "stop":
                        raise RuntimeError("Incomplete Kimi response")
                    if choice.delta.content:
                        emitted = True
                        yield choice.delta.content
                    if choice.finish_reason == "stop":
                        completed = True
            if not completed or not emitted:
                raise RuntimeError("Incomplete or empty Kimi stream")
    except Exception as exc:
        raise RuntimeError(f"所选模型 {route['model']} 流式调用失败：{error_label(exc)}；请检查设置或额度") from None
