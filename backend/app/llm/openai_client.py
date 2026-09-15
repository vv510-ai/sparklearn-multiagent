"""Official OpenAI SDK transport. Text calls are owned by spark_client.py."""
from __future__ import annotations

from ..config import get_settings


def client(*, timeout: float | None = None):
    from openai import OpenAI
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    # A timeout can follow a billable success; do not auto-retry generation.
    return OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url,
                  timeout=timeout or settings.openai_timeout_s, max_retries=0)


def response_params(messages: list[dict], *, max_tokens: int | None = None,
                    reasoning_mode: str = "") -> dict:
    settings = get_settings()
    effort = settings.openai_reasoning_effort
    if reasoning_mode == "disabled" or (max_tokens and max_tokens < 1600):
        effort = "low"
    if effort not in {"low", "medium", "high", "xhigh", "max"}:
        raise ValueError("Invalid OPENAI_REASONING_EFFORT")
    return {"model": settings.openai_text_model, "input": messages,
            "store": False, "reasoning": {"effort": effort},
            "max_output_tokens": max(2048, max_tokens or 8192)}


def error_label(error: Exception) -> str:
    """Never include response bodies, prompts, URLs or authorization."""
    status = getattr(error, "status_code", None)
    label = type(error).__name__ + (f" (HTTP {status})" if status else "")
    if getattr(error, "code", None) in {"credit_balance_exhausted", "insufficient_quota"}:
        label += "：API 额度不足，请由项目管理员处理"
    return label
