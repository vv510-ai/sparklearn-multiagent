"""防幻觉第二层 + 内容安全:本地敏感词拦截 + 讯飞内容审核 API 挂接点。

比赛中可叠加本地敏感词表;命中则拦截或改写。教育内容仍建议保留人工抽检与
"答案均标注出处"的产品策略(grounding 非绝对)。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from ..config import is_demo

log = logging.getLogger("sparklearn.guard")

_DEFAULT_BLOCKLIST = ("代写论文", "考试作弊", "答案泄露", "枪手")
_BLOCKLIST_PATH = Path(__file__).resolve().parents[1] / "data" / "blocklist.txt"


def _load_blocklist(path: Path = _BLOCKLIST_PATH) -> tuple[str, ...]:
    """从可审计文件加载词表；文件不可用时保留最小安全兜底。"""
    try:
        words = tuple(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        return words or _DEFAULT_BLOCKLIST
    except OSError:
        log.warning("本地安全词表不可读，使用内置最小兜底：%s", path)
        return _DEFAULT_BLOCKLIST


def run_local_blocklist(text: str) -> tuple[bool, list[str]]:
    hits = [word for word in _load_blocklist() if word in text]
    return (len(hits) == 0), hits


def call_iflytek_audit(text: str) -> bool:
    """讯飞文本合规 API 预留挂接点；当前版本未发起远程审核请求。"""
    if is_demo():
        return True
    # TODO(部署时): 调用 https://audit.iflyaisol.com 文本合规接口,HMAC 鉴权同 signing.py
    return True


def safety_filter(text: str) -> dict:
    ok_local, hits = run_local_blocklist(text)
    ok_audit = call_iflytek_audit(text)
    passed = ok_local and ok_audit
    cleaned = text
    if not ok_local:
        for w in hits:
            cleaned = cleaned.replace(w, "*" * len(w))
    # ``safe`` is kept as a compatibility alias for older agents and tests.
    return {"passed": passed, "safe": passed, "hits": hits, "text": cleaned}


def strip_pii(text: str) -> str:
    """脱敏:手机号/身份证简单遮蔽(学习日志入库前调用)。"""
    text = re.sub(r"\b1[3-9]\d{9}\b", "1**********", text)
    text = re.sub(r"\b\d{17}[\dXx]\b", "***", text)
    return text
