"""统一教学 Prompt Skill 的能力清单与组装回归测试。"""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.prompt_templates import (  # noqa: E402
    PROMPT_CAPABILITIES,
    PROMPT_SKILL_VERSION,
    invoke_learning_prompt,
    prompt_skill_manifest,
    render_learning_prompt,
    render_mindmap_prompt,
    render_quiz_prompt,
    render_tutor_prompt,
    render_video_prompt,
)


def test_manifest_is_ready_for_an_mcp_wrapper():
    manifest = prompt_skill_manifest()
    assert manifest["name"] == "sparklearn.learning_prompt"
    assert manifest["version"] == PROMPT_SKILL_VERSION
    assert manifest["capabilities"] == PROMPT_CAPABILITIES
    assert {
        "tutor.guided",
        "tutor.followup",
        "doc.complete_notes",
        "doc.interactive_audio",
        "doc.conversation_notes",
        "doc.question_review",
        "doc.exam_guide",
        "doc.remediation",
        "quiz.guided",
        "quiz.remediation",
        "quiz.standard",
        "mindmap.leaf",
        "media.video_script",
    } <= set(PROMPT_CAPABILITIES)


@pytest.mark.parametrize("measured", [False, True])
def test_tutor_does_not_present_default_mastery_as_assessed_ability(monkeypatch, measured):
    from app.services import course_learning_service
    context = {"course": "六级", "mastery": {"listening": 0.3},
               "evidence": [{"skill": "listening", "measured": True, "correct": 1, "total": 4}] if measured else []}
    monkeypatch.setattr(course_learning_service, "context_summary", lambda: context)
    rendered = render_tutor_prompt("六级你觉得怎么备考", {}, "", [], source_policy="supplement").prompt
    assert ('"mastery"' in rendered) is measured
    if not measured:
        assert "尚无可引用的能力测评证据" in rendered
    assert context["mastery"] == {"listening": 0.3}


def test_every_capability_is_loaded_from_a_standalone_markdown_file():
    sample_values = {
        "title": "示例课程",
        "survey": "{}",
        "learner_input": "{}", "facts": "{}", "references": "[]",
        "base_request": "依据资料准备课程题目",
        "draft": "{}",
        "original_prompt": "根据当前问题作答", "reason": "无效引用", "citation_count": 1,
        "validation_issue": "多选题至少两个正确选项",
        "topic": "示例主题",
        "level": "入门", "words": "example", "scene": "日常", "subtitles": "",
        "word": "evidence", "definition": "n. 证据",
        "sentence": "Practice helps learners.", "paragraph": "Practice helps learners.",
        "plan": "{}", "evidence": "[]",
        "goal": "从零学习",
        "persona": "循序渐进",
        "context": "资料片段",
        "content": "示例主题的课程知识正文",
        "previous_topic": "旧课程", "observation": "{}", "issues": "[]",
        "conversation": "学习者：我想学",
        "question": "这是什么？",
        "cognitive_style": "视觉型",
        "difficulty_pref": "循序渐进",
        "pace": "常规",
        "source_scope": "课程知识库",
        "kp": "示例知识点",
        "kpid": "sample_kp",
        "difficulty": 2,
        "target_questions": 3,
        "misconception": "条件看漏了",
        "forbidden_stems": "- 原题题干",
        "class_name": "SampleScene",
        "message": "我想学习示例主题",
        "knowledge_points": "[]",
        "profile": "{}",
        "kinds": "['doc']",
        "dialog": "user: 我想学",
        "events": "（无）",
        "answer": "示例回答",
        "kind": "翻译", "rubric": "核对信息与表达", "dimensions": "信息、句法、术语、自然度",
        "material_hint": "", "material_section": "", "transcripts": "【图1】示例",
        "key_points": "- 要点", "mnemonic": "- 口诀", "revision_notes": "", "lyrics": "[Chorus]\n示例",
        "material": "[1] 示例资料", "min_seconds": 60, "max_seconds": 120, "max_chars": 500,
        "approval_notes": "", "engine_rule": "制作引擎是 HyperFrames。", "quality": "looks", "problems": "- 时长不符",
    }
    prompt_root = Path(__file__).resolve().parents[1] / "app" / "prompts"
    system_text = (prompt_root / "system.md").read_text(encoding="utf-8").strip()

    for capability in PROMPT_CAPABILITIES:
        call = invoke_learning_prompt(capability, **sample_values)
        assert call.prompt
        assert call.system == system_text
        assert call.metadata()["capability"] == capability


def test_all_learning_outputs_share_source_and_beginner_rules():
    note = render_learning_prompt(
        "complete_notes",
        topic="二叉树",
        goal="从零学习",
        persona="循序渐进",
        context="[^1] 资料片段",
    )
    tutor = render_tutor_prompt(
        "我想学习二叉树",
        {"difficulty_pref": "循序渐进"},
        "[^1] 资料片段",
        [],
        guided=True,
    )
    followup = render_tutor_prompt(
        "图是什么",
        {"difficulty_pref": "循序渐进"},
        "[^1] 图由顶点和边组成",
        [],
    )
    quiz = render_quiz_prompt(
        kp="二叉树",
        kpid="binary_tree",
        difficulty=1,
        context="资料片段",
        guided=True,
    )

    assert "学习者画像" in note
    assert "学生画像" not in note + tutor.prompt
    assert "零基础" in note and "最小例子" in note
    assert "不照抄附件" in note and "不同来源有冲突" in note
    assert "类比优先同领域" in tutor.prompt and "回忆链" in tutor.prompt
    assert "禁止输出 JSON" in followup.prompt
    assert "简单问题精炼回答" in followup.prompt and "不能用固定字数截断" in followup.prompt
    assert "资料不足" in tutor.system and "资料边界" in tutor.system
    assert "恰好生成 5 道" in quiz and "生活化提示" in quiz


def test_question_review_and_exam_guide_are_separate_capabilities():
    review = invoke_learning_prompt(
        "doc.question_review",
        topic="栈与队列",
        goal="复盘已有选择题",
        context="题目与选项",
    ).prompt
    exam = invoke_learning_prompt(
        "doc.exam_guide",
        topic="栈与队列",
        goal="考前复习",
        context="课堂笔记与例题",
    ).prompt

    assert "不要另外生成新题" in review
    assert "每个选项为什么对或错" in review
    assert "识别题型 → 回忆概念" in exam
    assert "🔑 考点回忆" in exam and "🚨 常见陷阱" in exam


def test_remediation_prompt_is_narrow_and_returns_to_the_blocked_problem():
    remediation = invoke_learning_prompt(
        "doc.remediation",
        topic="二叉树",
        goal="补上堆的前置缺口后返回原题",
        persona="循序渐进",
        context="[^1] 二叉树由结点和边组成。",
    ).prompt

    assert "最小、可立即学习" in remediation
    assert "回到原问题" in remediation
    assert "不得泄漏原题标准答案" in remediation
    assert "不要扩展成完整章节" in remediation


def test_interactive_audio_prompt_is_short_spoken_and_beginner_first():
    audio = invoke_learning_prompt(
        "doc.interactive_audio",
        topic="二叉树",
        goal="适合零基础收听",
        persona="循序渐进",
        context="二叉树每个节点最多有两个孩子。",
    ).prompt

    assert "60—90 秒口播" in audio
    assert "一句白话给出核心结论" in audio
    assert "最小例子" in audio
    assert "适合朗读" in audio
    assert "不得扩展成完整章节" in audio


def test_remediation_quiz_requires_fresh_source_grounded_transfer_items():
    transfer = invoke_learning_prompt(
        "quiz.remediation",
        kp="堆",
        kpid="heap",
        difficulty=2,
        target_questions=3,
        misconception="父子关系判断错误",
        forbidden_stems="- 原题：堆的父节点在哪里？",
        context="讲义：堆满足完全二叉树的结构约束。",
    ).prompt

    assert "恰好生成 3 道" in transfer
    assert "这不是原题重做" in transfer
    assert "更换题面、例子、数值或提问角度" in transfer
    assert "父子关系判断错误" in transfer
    assert "原题：堆的父节点在哪里" in transfer


def test_visual_capabilities_keep_the_same_learning_order():
    mindmap = render_mindmap_prompt(kp="递归", context="资料")
    video = render_video_prompt(kp="递归", goal="理解递归", context="资料")
    assert "由基础到应用" in mindmap
    assert "最小例子的初始状态 → 逐步推演且每步解释原因" in video
    assert "易错边界" in video and "回忆链" in video
    assert "不强行编故事" in video and "不可变步骤快照" in video


def test_unknown_capability_is_rejected():
    with pytest.raises(ValueError, match="unsupported learning prompt capability"):
        invoke_learning_prompt("unknown.tool")


def test_one_page_does_not_inherit_stale_course_facts(monkeypatch):
    from app.services import course_learning_service
    monkeypatch.setattr(course_learning_service, "context_summary", lambda: {
        "course":"大学英语六级", "exam_reference":{"parts":[{"name":"听力","weight":35}]},
        "textbook":{"title":"六级讲义"}, "goal":"准备课程考试", "adaptations":["简明解释"]})
    call=invoke_learning_prompt("doc.one_page",topic="有机化学",goal="整体框架",persona="入门",conversation="",context="")
    assert "大学英语六级" not in call.prompt and "听力" not in call.prompt
    assert "准备课程考试" in call.prompt and "简明解释" in call.prompt
