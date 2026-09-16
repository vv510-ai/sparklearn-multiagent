"""Explainable teaching adaptations for multi-select learner context."""
from __future__ import annotations

BARRIERS = {
    "concepts": ("概念和符号看不懂", "先解释符号与适用条件，再用一个反例检查边界。"),
    "application": ("看懂答案，自己不会做", "先读分步例题，再补全关键步骤，最后独立完成新题。"),
    "coding": ("思路懂，代码写不出", "把思路写成伪代码，逐行追踪变量，再检查空输入与边界。"),
    "forgetting": ("学过很快就忘", "合上资料回忆关键步骤，隔天换题检查；不要只重读。"),
    "starting": ("任务太大，难以开始", "每次只安排一个可完成的小步骤，结束后再决定是否继续。"),
}
SUPPORTS = {
    "visual": ("图示和状态变化", "用文字表格展示每一步的状态变化，并配必要解释。"),
    "steps": ("符号与步骤讲细些", "解释每个新符号，每次只推进一个推理步骤。"),
    "examples": ("先看完整例题", "给一个完整例题，再逐渐减少帮助。"),
    "hints": ("先给提示，让我自己想", "先等待独立回答；卡住时只给一级提示，记录是否使用帮助。"),
    "small_steps": ("任务短一些", "把任务拆小，并保留休息和调整空间。"),
}


def context_reasons(survey: dict) -> list[str]:
    goals = survey.get("goals") or [survey.get("goal", "掌握课程基础")]
    reasons = [f"当前优先：{survey.get('goal', goals[0])}。"]
    secondary = [g for g in goals if g != survey.get("goal")]
    if secondary:
        reasons.append(f"同时兼顾：{'、'.join(secondary)}。")
    reasons.extend(BARRIERS[k][1] for k in survey.get("barriers", []) if k in BARRIERS)
    reasons.extend(SUPPORTS[k][1] for k in survey.get("supports", []) if k in SUPPORTS)
    if survey.get("study_cue"):
        reasons.append(f"开始时机：{survey['study_cue']}。")
    if survey.get("materials_status") in ("已有资料", "稍后上传"):
        reasons.append("围绕已绑定资料的解析内容安排，并在讲解中核对来源。" if survey.get("source_ids") else "可在资料栏补充课件或考试范围；当前尚未绑定上传资料。")
    return reasons


def screening_targets(survey: dict) -> list[str]:
    goal = survey.get("goal")
    if goal == "竞赛与算法练习":
        return ["complexity", "array", "sorting_basic", "recursion"]
    if goal == "编程项目应用":
        return ["complexity", "array", "linked_list", "hash"]
    return ["complexity", "array", "linked_list", "sorting_basic"]


def small_steps(survey: dict) -> bool:
    return survey.get("pressure") == "high" or "small_steps" in survey.get("supports", []) or "starting" in survey.get("barriers", [])


def task_approach(survey: dict) -> tuple[str, str]:
    goal = survey.get("goal", "")
    if goal in ("准备课程考试", "考研 408 复习"):
        return "考点辨析与限时前练习", "先说明常见考查方式与适用条件，再做一道无提示典型题；首次理解阶段不倒计时。"
    if goal == "编程项目应用":
        return "代码追踪与应用", "从一个小型应用场景出发，写伪代码、追踪变量并检查边界情况。"
    if goal == "完成项目或实践":
        return "实践任务与检验", "从一个可完成的小任务出发，说明交付结果与检查标准，再让学习者独立尝试。"
    if goal == "看懂学习资料":
        return "资料精读与复述", "解释资料中的关键概念与论证，再合上原文用自己的话复述，核对原文纠错。"
    if goal == "独立解题与纠错":
        return "独立尝试与错因纠正", "先尝试，再提供必要的一步提示；之后用一道未见过的新题复核。"
    if goal == "竞赛与算法练习":
        return "推理与迁移", "比较两种解法及复杂度，再尝试换条件的迁移题。"
    return "例题与独立练习", "解释必要概念，先看一个分步例题，再独立完成不同情境的练习。"


def lesson_guidance(survey: dict, skill: dict) -> str:
    _, approach = task_approach(survey)
    lines = ["## 这份资料怎样帮助你", approach, *context_reasons(survey)]
    if skill.get("high_confidence_errors", 0):
        lines += ["本次有很确定但答错的题。请先写下原来的判断依据，再对照适用条件；这只是需要复核的线索。"]
    if skill.get("status") == "strength":
        lines += ["本次基础题表现较好：重点检查边界和迁移，仍需之后的独立新题确认保持情况。"]
    return "\n\n".join(lines)
