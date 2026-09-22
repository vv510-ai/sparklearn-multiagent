"""Transport for an explicitly selected model; called only by spark_client."""
from __future__ import annotations

import asyncio

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
        params.update(max_completion_tokens=max(4096, budget), reasoning_effort="low")
    else:
        params.update(max_tokens=budget, extra_body={"thinking": {"type": "disabled" if reasoning_mode == "disabled" or (max_tokens and max_tokens < 1600) else "enabled"}})
    if json_object:
        params["response_format"] = {"type": "json_object"}
    return params


async def complete(route, messages, *, max_tokens=None, json_object=False, reasoning_mode=""):
    from openai import OpenAI
    def run():
        with OpenAI(api_key=route["key"], base_url=route["base_url"], timeout=150, max_retries=0) as client:
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
