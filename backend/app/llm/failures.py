"""Safe failure codes; never serialize provider bodies, prompts or credentials."""
from __future__ import annotations

MESSAGES = {
    "timeout": "生成等待超时，请稍后重试。",
    "truncated": "模型回答达到长度限制，未生成完整正文。可以缩小本次学习范围后重试。",
    "empty_response": "模型没有返回可用正文，请重试。",
    "incomplete_response": "模型回答未完整结束，请重试。",
    "content_filter": "模型服务未返回完整内容，请调整问题后重试。",
    "authentication": "模型连接认证失败，请检查模型设置。",
    "quota": "模型服务额度不足，请检查额度。",
    "rate_limit": "模型服务请求过于频繁，请稍后重试。",
    "connection": "暂时无法连接模型服务，请稍后重试。",
    "provider_error": "模型服务暂时出错，请稍后重试。",
    "generation_failed": "本次生成失败，原因尚未分类，请重试。",
    "topic_drift": "生成内容偏离本次问题，已改为资料导读。",
    "invalid_citation": "生成内容引用了不存在的资料，已拒绝该正文。",
    "grounding_timeout": "资料核对未完成，请结合原文复核。",
    "grounding": "生成内容存在缺少资料依据的表述，请结合原文复核。",
    "one_page_source_excerpt": "扩写未通过检查，当前展示检索资料的原文摘录。",
    "source_scope_empty": "当前资料范围没有可检索内容，请选择已完成索引的资料。",
    "demo_mode": "当前展示演示内容。",
}

class ModelFailure(RuntimeError):
    def __init__(self, code: str, *, streaming: bool = False, status_code: int | None = None):
        self.code = code if code in MESSAGES else "generation_failed"
        self.status_code = status_code if isinstance(status_code, int) else None
        operation = "流式调用" if streaming else "调用"
        status = f" (HTTP {self.status_code})" if self.status_code else ""
        super().__init__(f"模型{operation}失败：{MESSAGES[self.code]}{status}")


def failure_code(error: BaseException) -> str:
    if isinstance(error, ModelFailure):
        return error.code
    name = type(error).__name__.lower()
    status = getattr(error, "status_code", None)
    code = getattr(error, "code", None)
    if isinstance(error, TimeoutError) or "timeout" in name:
        return "timeout"
    if code in {"insufficient_quota", "credit_balance_exhausted"}:
        return "quota"
    if status in (401, 403):
        return "authentication"
    if status == 429:
        return "rate_limit"
    if "connection" in name:
        return "connection"
    if isinstance(status, int) and status >= 500:
        return "provider_error"
    return "generation_failed"


def finish_failure(reason: str | None) -> ModelFailure:
    return ModelFailure("truncated" if reason in {"length", "max_output_tokens"} else
                        "content_filter" if reason == "content_filter" else "incomplete_response")


def generation_details(flags: list[dict], *, mode: str, source_empty: bool = False) -> dict:
    codes = ["source_scope_empty"] if source_empty else []
    if mode == "demo":
        codes.append("demo_mode")
    for flag in flags:
        code = flag.get("reason_code") or flag.get("type")
        if code in MESSAGES and code not in codes:
            codes.append(code)
    return {"status": "unavailable" if mode == "unavailable" else "degraded" if codes else "completed",
            "reason_codes": codes, "message": " ".join(MESSAGES[code] for code in codes)}
