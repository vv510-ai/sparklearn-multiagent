"""讯飞 OCR / 图片理解:用户拍照提问的入口。

优先走星火图片理解多模态接口;未配置三元组时返回提示文本(演示模式给出固定示例)。
"""
from __future__ import annotations

import base64
import json
import logging
import re
import threading

from ..config import get_settings, is_demo
from .signing import assemble_auth_url

log = logging.getLogger("sparklearn.ocr")
IMG_UNDERSTAND_URL = "wss://spark-api.cn-huabei-1.xf-yun.com/v2.1/image"


def _safe_error_text(error: object) -> str:
    """Keep transport diagnostics without leaking the signed request URL."""
    text = str(error).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"(?:https?|wss?)://\S+", "<url>", text)
    text = re.sub(
        r"(?i)(authorization|api_key|signature)=([^&\s]+)",
        r"\1=<redacted>",
        text,
    )
    return text[:200]


def image_to_question(
    image_bytes: bytes,
    hint: str = "",
    *,
    max_tokens: int = 1024,
    timeout_s: float = 30.0,
) -> str:
    """图片 → 题目文本。演示模式返回内置样例,保证拍照答疑链路可演示。"""
    if is_demo():
        return "【演示OCR】题目:已知一棵二叉搜索树,求中序遍历序列,并说明为何有序。" + (f"(用户补充:{hint})" if hint else "")
    s = get_settings()
    if not (s.spark_appid and s.spark_api_key and s.spark_api_secret):
        return "(未配置讯飞图片理解三元组,无法解析图片;请直接文字描述题目)"
    try:
        import websocket
    except ImportError:
        return "(websocket-client 未安装,无法调用图片理解)"
    url = assemble_auth_url(IMG_UNDERSTAND_URL.replace("wss://", "https://"),
                            s.spark_api_key, s.spark_api_secret).replace("https://", "wss://")
    result: list[str] = []
    errors: list[str] = []
    req = {
        "header": {"app_id": s.spark_appid},
        "parameter": {"chat": {
            "domain": getattr(s, "spark_image_domain", "general"),
            "temperature": 0.3,
            "max_tokens": max_tokens,
        }},
        "payload": {"message": {"text": [
            {"role": "user", "content": base64.b64encode(image_bytes).decode(), "content_type": "image"},
            {
                "role": "user",
                "content": (
                    "请先完整转写图片中的文字、公式与代码，再准确描述图表、流程、连线、"
                    "标注和空间关系等仅靠 OCR 无法表达的信息。只陈述图片中可以确认的内容，"
                    "不要猜测，不要替用户作答。"
                    + (f"用户补充：{hint}" if hint else "")
                ),
                "content_type": "text",
            },
        ]}},
    }

    def on_message(ws, message):  # noqa: ANN001
        try:
            msg = json.loads(message)
        except (TypeError, json.JSONDecodeError) as exc:
            errors.append(f"spark image understanding invalid JSON: {_safe_error_text(exc)}")
            ws.close()
            return

        header = msg.get("header") or {}
        code = header.get("code", 0)
        if code != 0:
            sid = header.get("sid") or "-"
            detail = header.get("message") or header.get("msg") or "unknown error"
            errors.append(
                f"spark image understanding code={code} sid={sid} "
                f"message={_safe_error_text(detail)}"
            )
            ws.close()
            return

        choices = ((msg.get("payload") or {}).get("choices") or {})
        for t in choices.get("text") or []:
            result.append(t.get("content", ""))
        if choices.get("status") == 2:
            ws.close()

    def on_error(ws, error):  # noqa: ANN001, ARG001
        errors.append(f"spark image understanding transport error={_safe_error_text(error)}")

    def on_close(ws, status_code=None, reason=None):  # noqa: ANN001, ARG001
        if not result and not errors and status_code not in (None, 1000):
            errors.append(
                "spark image understanding connection closed "
                f"status={status_code} reason={_safe_error_text(reason or '')}"
            )

    ws = websocket.WebSocketApp(url, on_message=on_message,
                                on_error=on_error, on_close=on_close,
                                on_open=lambda w: w.send(json.dumps(req)))
    deadline = max(0.1, float(timeout_s))

    def abort_on_deadline() -> None:
        errors.append(f"spark image understanding provider timeout after {deadline:g}s")
        try:
            ws.close()
        except Exception:  # noqa: BLE001
            pass

    watchdog = threading.Timer(deadline, abort_on_deadline)
    watchdog.daemon = True
    watchdog.start()
    try:
        ws.run_forever()
    finally:
        watchdog.cancel()
    if errors:
        raise RuntimeError(errors[0])
    text = "".join(result)
    if not text:
        raise RuntimeError("spark image understanding returned no text")
    return text
