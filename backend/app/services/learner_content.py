"""Learner-facing content guards.

Raw implementation code belongs only to an explicitly requested code resource.
Other learning artifacts should explain the idea with words, examples and visuals.
"""
from __future__ import annotations

import re


_FENCE_RE = re.compile(
    r"(?P<fence>```|~~~)(?P<info>[^\n]*)\n(?P<body>.*?)(?P=fence)",
    flags=re.DOTALL,
)
_HTML_CODE_RE = re.compile(r"<pre\b[^>]*>.*?</pre>", flags=re.IGNORECASE | re.DOTALL)
_STRONG_CODE_LINE_RE = re.compile(
    r"^\s*(?:(?:async\s+def|def|class|import|return|yield|raise)\b|"
    r"from\s+\S+\s+import\b|(?:if\s+.+|elif\s+.+|else|for\s+.+|"
    r"while\s+.+|try|except(?:\s+.+)?|with\s+.+):\s*$)",
    flags=re.IGNORECASE,
)
_CALL_LINE_RE = re.compile(
    r"^\s*[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\([^\n]*\)\s*(?:#.*)?$"
)
_SQL_LINE_RE = re.compile(
    r"^\s*(?:SELECT\b.+\bFROM|INSERT\s+INTO|UPDATE\b.+\bSET|DELETE\s+FROM|"
    r"CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE)\b",
    flags=re.IGNORECASE,
)
_INLINE_CODE_RE = re.compile(
    r"\b(?:async\s+def|def|class)\s+[A-Za-z_]\w*\s*(?:\(|:)|"
    r"\b(?:import\s+[A-Za-z_]|from\s+[A-Za-z_.]+\s+import\b)|"
    r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\([^\n)]*\)",
    flags=re.IGNORECASE,
)


def _is_code_line(line: str) -> bool:
    return bool(
        _STRONG_CODE_LINE_RE.search(line)
        or _CALL_LINE_RE.search(line)
        or _SQL_LINE_RE.search(line)
        or _INLINE_CODE_RE.search(line)
    )


def looks_like_source_code(value: object) -> bool:
    """Return True only for high-confidence source-code shaped learner text."""
    text = str(value or "").strip()
    if not text:
        return False
    lines = [line for line in text.splitlines() if line.strip()]
    if _INLINE_CODE_RE.search(text):
        return True
    if any(_STRONG_CODE_LINE_RE.search(line) or _SQL_LINE_RE.search(line) for line in lines):
        return True
    return sum(1 for line in lines if _is_code_line(line)) >= 2


def without_source_code(value: object, *, keep_mermaid: bool = False) -> str:
    """Remove fenced/HTML/raw source code while optionally retaining Mermaid diagrams."""
    text = _HTML_CODE_RE.sub("", str(value or ""))

    def replace_fence(match: re.Match[str]) -> str:
        info = match.group("info").strip().split(maxsplit=1)
        language = info[0].lower() if info else ""
        if keep_mermaid and language == "mermaid":
            return match.group(0)
        return ""

    text = _FENCE_RE.sub(replace_fence, text)
    lines = text.splitlines()
    if looks_like_source_code(text):
        filtered: list[str] = []
        skipping_indented = False
        for line in lines:
            if _is_code_line(line):
                skipping_indented = True
                continue
            if skipping_indented and (not line.strip() or line.startswith((" ", "\t"))):
                continue
            skipping_indented = False
            filtered.append(line)
        text = "\n".join(filtered)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def plain_learning_text(value: object, limit: int = 180) -> str:
    """Normalize a short artifact field without leaking source-code snippets."""
    text = without_source_code(value)
    if not text or looks_like_source_code(text):
        return ""
    text = re.sub(r"[#>*_`|\[\]]+", " ", text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."
