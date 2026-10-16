"""File-backed Prompt Skill loader.

All model-facing wording lives under ``app/prompts``. Python only selects a
capability, injects variables, and returns the software-wide system prompt plus
the module prompt. Templates are intentionally re-read on every call so a
maintainer can replace a Markdown file without editing Python or restarting a
long-running development process.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any


_PROMPT_ROOT = Path(__file__).resolve().parent / "prompts"
_MANIFEST_PATH = _PROMPT_ROOT / "manifest.json"
_TOKEN = re.compile(r"\{\{([a-zA-Z][a-zA-Z0-9_]*)\}\}")
_DOC_TEMPLATES = {
    "complete_notes",
    "interactive_audio",
    "one_page",
    "error_confusion",
    "conversation_notes",
    "question_review",
    "exam_guide",
    "remediation",
}
DEFAULT_TEMPLATE = "complete_notes"


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
            "sha256": hashlib.sha256((self.system + "\0" + self.prompt).encode()).hexdigest(),
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
    from .services.course_learning_service import context_summary
    # This report already carries a frozen intake. Appending the latest profile
    # could mix two revisions when another page edits preferences mid-generation.
    learning_context = None if key == "english.cet6_advice" else context_summary()
    if learning_context and "one_page" in key:
        # The explicit request and selected evidence define infographic content.
        # Old course exam records/mastery must not leak through the generic
        # personalization attachment into a newly requested subject or image.
        learning_context = {field: learning_context[field] for field in (
            "goal", "goals", "stage", "daily_minutes", "study_days", "target_date", "adaptations", "support"
        ) if field in learning_context}
    if learning_context and not key.startswith("assessment.") and key not in {"image.one_page_observe", "image.one_page_check", "doc.one_page_scope", "doc.one_page_topic_check", "english.word_lesson", "english.word_lesson_review"}:
        prompt += "\n\n" + _render(_read_prompt("shared/learner-context.md"),
            {"learning_context": json.dumps(learning_context, ensure_ascii=False)}, label="learning_context")
    return PromptCall(
        capability=key,
        prompt=f"CAPABILITY={key}\n{prompt}",
        system=system,
        version=str(manifest.get("version") or "unversioned"),
    )


def render_plain_prompt(capability: str, **values: Any) -> PromptCall:
    """Render one capability verbatim for an external chat UI.

    Unlike :func:`invoke_learning_prompt`, nothing is added: no system prompt,
    no ``CAPABILITY=`` header and no learner context. Used where the exact text
    is a product decision (for example the 一图看懂 request sent to ChatGPT).
    """
    key = str(capability or "").strip().lower()
    manifest = _load_manifest()
    entry = manifest["capabilities"].get(key)
    if not isinstance(entry, dict):
        raise ValueError(f"unsupported learning prompt capability: {capability}")
    prompt = _render(_read_prompt(str(entry.get("file") or "")), values, label=key)
    return PromptCall(capability=key, prompt=prompt, system="",
                      version=str(manifest.get("version") or "unversioned"))


def supported_template(value: str) -> str:
    key = str(value or "").strip().lower()
    return key if key in _DOC_TEMPLATES else DEFAULT_TEMPLATE


def _dialog_text(conversation: list[dict] | None) -> str:
    """Keep the whole useful conversation up to a generous character budget.

    Older code kept only ten turns, which made pronouns, corrections and the
    learner's earlier misconceptions disappear even though the database still
    had them. DeepSeek-V4 supports a long context, but an explicit budget keeps
    prompts predictable when a notebook grows for months.
    """
    budget = 24000
    selected: list[str] = []
    used = 0
    for item in reversed(conversation or []):
        content = " ".join(str(item.get("content") or "").strip().split())
        if not content:
            continue
        line = f"{('学习者' if item.get('role') == 'user' else '小知')}: {content}"
        if selected and used + len(line) + 1 > budget:
            break
        selected.append(line[:budget] if not selected else line)
        used += len(selected[-1]) + 1
    selected.reverse()
    return "\n".join(selected) or "（这是本主题的第一次交流）"


def render_learning_prompt_call(
    template_key: str,
    *,
    topic: str,
    goal: str,
    persona: str,
    context: str,
    conversation: str = "",
    general_knowledge: bool = False,
    source_policy: str = "strict",
) -> PromptCall:
    key = supported_template(template_key)
    return invoke_learning_prompt(
        f"doc.{key}",
        topic=topic or "当前主题",
        goal=goal or f"系统学习{topic or '当前主题'}",
        persona=persona or "循序渐进",
        context=context or "（没有检索到可用资料）",
        conversation=conversation or "（当前没有可整理的学习对话）",
        **({"source_rules": _read_prompt("shared/source-supplement.md")} if source_policy == "supplement"
           else {"source_rules": _read_prompt("shared/general-topic.md")} if general_knowledge else {}),
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
    source_policy: str = "strict",
) -> PromptCall:
    source_scope = (
        "优先使用本次资料，允许明确标识的通用补充；未找到的原文不能补造"
        if source_policy == "supplement" else
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
        **({"source_rules": _read_prompt("shared/source-supplement.md")} if source_policy == "supplement"
           else {"source_rules": _read_prompt("shared/general-topic.md")} if general_knowledge
           else {"source_rules": _read_prompt("tutor/source-boundary.md")}),
    )


def render_quiz_prompt_call(
    *, kp: str, kpid: str, difficulty: int, context: str, guided: bool,
    general_knowledge: bool = False,
    remediation: bool = False,
    target_questions: int = 3,
    misconception: str = "",
    forbidden_stems: str = "",
) -> PromptCall:
    capability = "quiz.remediation" if remediation else "quiz.guided" if guided else "quiz.standard"
    return invoke_learning_prompt(
        capability,
        kp=kp or "当前知识点",
        kpid=kpid or "unknown",
        difficulty=max(1, min(5, int(difficulty or 1))),
        context=context or "（没有可用资料）",
        target_questions=max(1, min(5, int(target_questions or 3))),
        misconception=misconception or "概念边界还不稳定",
        forbidden_stems=forbidden_stems or "（无可复用题干；仍需生成新题面）",
        **({"source_rules": _read_prompt("shared/general-topic.md")} if general_knowledge else {}),
    )


def render_quiz_prompt(*, kp: str, kpid: str, difficulty: int, context: str, guided: bool) -> str:
    return render_quiz_prompt_call(
        kp=kp, kpid=kpid, difficulty=difficulty, context=context, guided=guided,
    ).prompt


def render_mindmap_prompt_call(*, kp: str, context: str, general_knowledge: bool = False) -> PromptCall:
    return invoke_learning_prompt(
        "mindmap.leaf", kp=kp or "当前概念", context=context or "（无）",
        **({"source_rules": _read_prompt("shared/general-topic.md")} if general_knowledge else {}),
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
        **({"source_rules": _read_prompt("shared/general-topic.md")} if general_knowledge else {}),
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
        **({"source_rules": _read_prompt("shared/general-topic.md")} if general_knowledge else {}),
    )


def render_manim_prompt(*, kp: str, class_name: str, context: str) -> str:
    return render_manim_prompt_call(kp=kp, class_name=class_name, context=context).prompt
