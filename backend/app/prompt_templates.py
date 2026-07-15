"""File-backed Prompt Skill loader.

All model-facing wording lives under ``app/prompts``. Python only selects a
capability, injects variables, and returns the software-wide system prompt plus
the module prompt. Templates are intentionally re-read on every call so a
maintainer can replace a Markdown file without editing Python or restarting a
long-running development process.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any


_PROMPT_ROOT = Path(__file__).resolve().parent / "prompts"
_MANIFEST_PATH = _PROMPT_ROOT / "manifest.json"
_TOKEN = re.compile(r"\{\{([a-zA-Z][a-zA-Z0-9_]*)\}\}")
_DOC_TEMPLATES = {
    "complete_notes",
    "one_page",
    "error_confusion",
    "conversation_notes",
    "question_review",
    "exam_guide",
}
DEFAULT_TEMPLATE = "complete_notes"
_GENERAL_TOPIC_RULES = """自定义主题边界：

1. 当前主题由学习者明确指定，可使用模型通用知识完成教学，不要求它属于内置课程知识图谱。
2. 所有内容必须紧扣当前主题；禁止引用旧会话中的其他主题，尤其禁止回退到二叉树或数据结构示例。
3. 不确定的事实要明确说明不确定性，不虚构资料编号、页码或引用。"""


@dataclass(frozen=True)
class PromptCall:
    """A rendered, traceable prompt capability invocation."""

    capability: str
    prompt: str
    system: str
    version: str

    def metadata(self) -> dict[str, str]:
        return {
            "name": "sparklearn.learning_prompt",
            "capability": self.capability,
            "version": self.version,
        }


def _load_manifest() -> dict[str, Any]:
    try:
        data = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"cannot load prompt manifest: {_MANIFEST_PATH}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("capabilities"), dict):
        raise RuntimeError("prompt manifest must contain a capabilities object")
    return data


def _prompt_path(relative_path: str) -> Path:
    path = (_PROMPT_ROOT / str(relative_path or "")).resolve()
    if _PROMPT_ROOT.resolve() not in path.parents:
        raise ValueError(f"prompt path escapes prompt root: {relative_path}")
    if path.suffix.lower() != ".md":
        raise ValueError(f"prompt file must be Markdown: {relative_path}")
    return path


def _read_prompt(relative_path: str) -> str:
    try:
        return _prompt_path(relative_path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"cannot read prompt file: {relative_path}") from exc


def _partials(manifest: dict[str, Any]) -> dict[str, str]:
    items = manifest.get("partials") or {}
    if not isinstance(items, dict):
        raise RuntimeError("prompt manifest partials must be an object")
    return {str(name): _read_prompt(str(path)) for name, path in items.items()}


def _render(template: str, values: dict[str, Any], *, label: str) -> str:
    string_values = {str(key): str(value) for key, value in values.items()}
    missing = sorted(set(_TOKEN.findall(template)) - string_values.keys())
    if missing:
        raise ValueError(f"prompt {label} is missing variables: {missing}")
    return _TOKEN.sub(lambda match: string_values[match.group(1)], template)


def prompt_skill_manifest() -> dict[str, Any]:
    """Return a public manifest suitable for a future MCP wrapper."""

    manifest = _load_manifest()
    capabilities = {
        str(key): str(value.get("description") or "")
        for key, value in manifest["capabilities"].items()
        if isinstance(value, dict)
    }
    return {
        "name": str(manifest.get("name") or "sparklearn.learning_prompt"),
        "version": str(manifest.get("version") or "unversioned"),
        "capabilities": capabilities,
    }


_INITIAL_MANIFEST = prompt_skill_manifest()
PROMPT_SKILL_VERSION = _INITIAL_MANIFEST["version"]
PROMPT_CAPABILITIES: dict[str, str] = dict(_INITIAL_MANIFEST["capabilities"])


def invoke_learning_prompt(capability: str, **values: Any) -> PromptCall:
    """Render one named capability from disk, like invoking an MCP prompt tool."""

    key = str(capability or "").strip().lower()
    manifest = _load_manifest()
    entry = manifest["capabilities"].get(key)
    if not isinstance(entry, dict):
        raise ValueError(f"unsupported learning prompt capability: {capability}")
    partials = _partials(manifest)
    defaults: dict[str, Any] = {}
    if key.startswith("doc."):
        defaults = {
            "topic": "当前主题",
            "goal": "系统学习当前主题",
            "persona": "循序渐进",
            "context": "（没有检索到可用资料）",
            "conversation": "（当前没有可整理的学习对话）",
        }
    all_values = {**partials, **defaults, **values}
    system = _render(
        _read_prompt(str(manifest.get("system") or "system.md")),
        all_values,
        label="system",
    )
    prompt = _render(
        _read_prompt(str(entry.get("file") or "")),
        all_values,
        label=key,
    )
    return PromptCall(
        capability=key,
        prompt=prompt,
        system=system,
        version=str(manifest.get("version") or "unversioned"),
    )


def supported_template(value: str) -> str:
    key = str(value or "").strip().lower()
    return key if key in _DOC_TEMPLATES else DEFAULT_TEMPLATE


def _dialog_text(conversation: list[dict] | None) -> str:
    return "\n".join(
        f"{('学习者' if item.get('role') == 'user' else '学伴')}: {str(item.get('content') or '').strip()}"
        for item in (conversation or [])[-10:]
        if str(item.get("content") or "").strip()
    ) or "（这是本主题的第一次交流）"


def render_learning_prompt_call(
    template_key: str,
    *,
    topic: str,
    goal: str,
    persona: str,
    context: str,
    conversation: str = "",
    general_knowledge: bool = False,
) -> PromptCall:
    key = supported_template(template_key)
    return invoke_learning_prompt(
        f"doc.{key}",
        topic=topic or "当前主题",
        goal=goal or f"系统学习{topic or '当前主题'}",
        persona=persona or "循序渐进",
        context=context or "（没有检索到可用资料）",
        conversation=conversation or "（当前没有可整理的学习对话）",
        **({"source_rules": _GENERAL_TOPIC_RULES} if general_knowledge else {}),
    )


def render_learning_prompt(
    template_key: str,
    *,
    topic: str,
    goal: str,
    persona: str,
    context: str,
    conversation: str = "",
) -> str:
    """Backward-compatible document prompt renderer."""

    return render_learning_prompt_call(
        template_key,
        topic=topic,
        goal=goal,
        persona=persona,
        context=context,
        conversation=conversation,
    ).prompt


def render_tutor_prompt(
    question: str,
    profile: dict,
    context: str,
    source_ids: list[str],
    *,
    conversation: list[dict] | None = None,
    guided: bool = False,
    general_knowledge: bool = False,
) -> PromptCall:
    source_scope = (
        "仅使用本次选中的学习资料"
        if source_ids
        else "围绕当前自定义主题使用模型通用知识，不混入旧主题"
        if general_knowledge
        else "使用课程知识库和已经沉淀的个人学习笔记"
    )
    return invoke_learning_prompt(
        "tutor.guided" if guided else "tutor.followup",
        question=question or "请从最基础开始讲解当前主题",
        cognitive_style=profile.get("cognitive_style", "视觉型"),
        difficulty_pref=profile.get("difficulty_pref", "循序渐进"),
        pace=profile.get("pace", "常规"),
        source_scope=source_scope,
        conversation=_dialog_text(conversation),
        context=context or "（没有检索到可用片段）",
        **({"source_rules": _GENERAL_TOPIC_RULES} if general_knowledge else {}),
    )


def render_quiz_prompt_call(
    *, kp: str, kpid: str, difficulty: int, context: str, guided: bool,
    general_knowledge: bool = False,
) -> PromptCall:
    return invoke_learning_prompt(
        "quiz.guided" if guided else "quiz.standard",
        kp=kp or "当前知识点",
        kpid=kpid or "unknown",
        difficulty=max(1, min(5, int(difficulty or 1))),
        context=context or "（没有可用资料）",
        **({"source_rules": _GENERAL_TOPIC_RULES} if general_knowledge else {}),
    )


def render_quiz_prompt(*, kp: str, kpid: str, difficulty: int, context: str, guided: bool) -> str:
    return render_quiz_prompt_call(
        kp=kp, kpid=kpid, difficulty=difficulty, context=context, guided=guided,
    ).prompt


def render_mindmap_prompt_call(*, kp: str, context: str, general_knowledge: bool = False) -> PromptCall:
    return invoke_learning_prompt(
        "mindmap.leaf", kp=kp or "当前概念", context=context or "（无）",
        **({"source_rules": _GENERAL_TOPIC_RULES} if general_knowledge else {}),
    )


def render_mindmap_prompt(*, kp: str, context: str) -> str:
    return render_mindmap_prompt_call(kp=kp, context=context).prompt


def render_video_prompt_call(
    *, kp: str, goal: str, context: str, general_knowledge: bool = False,
) -> PromptCall:
    return invoke_learning_prompt(
        "media.video_script",
        kp=kp or "当前知识点",
        goal=goal or "理解并记住该知识点",
        context=context or "（无）",
        **({"source_rules": _GENERAL_TOPIC_RULES} if general_knowledge else {}),
    )


def render_video_prompt(*, kp: str, goal: str, context: str) -> str:
    return render_video_prompt_call(kp=kp, goal=goal, context=context).prompt


def render_manim_prompt_call(
    *, kp: str, class_name: str, context: str, general_knowledge: bool = False,
) -> PromptCall:
    return invoke_learning_prompt(
        "media.manim",
        kp=kp or "当前知识点",
        class_name=class_name or "LearningScene",
        context=context or "（无）",
        **({"source_rules": _GENERAL_TOPIC_RULES} if general_knowledge else {}),
    )


def render_manim_prompt(*, kp: str, class_name: str, context: str) -> str:
    return render_manim_prompt_call(kp=kp, class_name=class_name, context=context).prompt
