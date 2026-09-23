"""Check generated terminal choice questions before exposing answer controls.

A model review is a fallible quality filter, not a calibrated exam guarantee.
"""
from __future__ import annotations

import asyncio
import re

from ..llm.spark_client import llm_complete, parse_json
from ..prompt_templates import invoke_learning_prompt

_OPTION = re.compile(r"(?m)^\s*(?:[-*]\s*)?(?:\*\*)?([A-D])[.、．:：)）]\s*(?:\*\*)?(.+?)\s*$")
_REPLACEMENT = "这道选择题的条件或答案未能核对，先改用简答检查：请用自己的话解释刚才的关键步骤，并举一个例子，我再帮你核对。"


def terminal_question(answer: str):
    # Never treat quoted code or a source excerpt as answer buttons.
    masked = re.sub(r"```[\s\S]*?```", lambda m: " " * len(m[0]), answer)
    options = list(_OPTION.finditer(masked))
    starts = [i for i, m in enumerate(options) if m[1] == "A"]
    if not starts:
        return None
    group = options[starts[-1]:]
    if not 2 <= len(group) <= 4 or [m[1] for m in group] != list("ABCD"[:len(group)]):
        return None
    if any(masked[a.end():b.start()].strip() for a, b in zip(group, group[1:])):
        return None
    if len(masked[group[-1].end():].strip()) > 180:
        return None
    before = answer[:group[0].start()].rstrip()
    start = before.rfind("\n\n") + 2 if "\n\n" in before else 0
    # A question heading owns all following premise paragraphs, not just the
    # last line immediately before A. Losing the premises causes false rejects.
    headings = list(re.finditer(r"(?m)^(?:#{1,6}[ \t]*|\*\*)[^\n]*(?:单选|多选|检查|练习|小测)[^\n]*$", before))
    if headings and len(before) - headings[-1].start() <= 4000:
        start = headings[-1].start()
    stem = before[start:]
    if not re.search(r"[?？]|单选|多选|检查|练习|哪", stem):
        return None
    return start, answer[start:], [m[1] for m in group], "multiple" if "多选" in stem else "single"


async def check_question(answer: str, context: str) -> tuple[str, dict | None]:
    found = terminal_question(answer)
    if found is None:
        return answer, None
    start, question, labels, kind = found
    call = invoke_learning_prompt("tutor.check_question", question=question, context=context)
    reason = "review_unavailable"
    try:
        raw = await asyncio.wait_for(llm_complete(call.prompt, system=call.system,
            role="reasoner", temperature=0, max_tokens=1400, reasoning_mode="disabled",
            json_mode=True, json_object=True, allow_mock_fallback=False), timeout=35)
        result = parse_json(raw)
        rows = result.get("options", [])
        complete = (isinstance(rows, list) and len(rows) == len(labels)
            and all(isinstance(row, dict) for row in rows)
            and [row.get("label") for row in rows] == labels
            and all(type(row.get("correct")) is bool and str(row.get("reason") or "").strip() for row in rows))
        correct = sum(row["correct"] for row in rows) if complete else 0
        unique = correct == 1 if kind == "single" else 2 <= correct < len(labels)
        if complete and result.get("conditions_sufficient") is True and unique:
            return answer, {"accepted": True, "verification": "model_review", "question_type": kind}
        reason = "ambiguous_question"
    except Exception:
        pass  # Preserve the explanation; never expose a guessed answer key.
    return answer[:start].rstrip() + "\n\n" + _REPLACEMENT, {
        "accepted": False, "verification": "model_review", "reason": reason}
