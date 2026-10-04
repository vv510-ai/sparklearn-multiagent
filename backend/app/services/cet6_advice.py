"""Private, recoverable onboarding advice. Model prose never owns arithmetic/URLs."""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import hashlib
import json
import logging
import re
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..config import get_settings, is_demo
from ..llm.spark_client import active_provider, llm_complete, parse_json
from ..models.db import session
from ..models.entities import Cet6Advice
from ..prompt_templates import invoke_learning_prompt
from ..schemas.cet6_advice import AdviceText
from ..tenant import current_user_context
from . import cet6_learning as learning
from .learning_scope import course_scope

VERSION = "cet6-advice-v3-20261005"
TIMEOUT = 120
CLAIM_TTL = 180
LABELS = learning.LABELS
REFERENCES = [
    {"id": "scores", "title": "中国教育考试网 · 分数解释", "url": "https://www.neea.edu.cn/html1/folder/19081/5124-1.htm",
     "checked_on": "2026-10-04", "supports": "报道分采用常模转换，不设及格线；听力与阅读各 249，写作翻译合计 212。分项常模位置只作历史参照，不代表当前考生排名。"},
    {"id": "structure", "title": "中国教育考试网 · 六级笔试结构", "url": "https://cet.neea.edu.cn/html1/report/16123/201-1.htm",
     "checked_on": "2026-10-04", "supports": "听力和阅读各占 35%，写作与翻译各占 15%；阅读参考用时 40 分钟，听力、写作、翻译各 30 分钟。"},
    {"id": "retrieval", "title": "Karpicke 与 Roediger（2008）· 回忆练习研究", "url": "https://profiles.wustl.edu/en/publications/the-critical-importance-of-retrieval-for-learning/",
     "checked_on": "2026-10-04", "supports": "外语词汇实验中，学会后继续进行回忆测试有助于延迟记忆。支持先回忆再核对的学习建议，不能据此预测六级提分或断定某人的词汇量。"},
]
# Official CET6 historical norm table. Use enclosing ranges, never invented interpolation.
NORMS = {
    "listening": list(zip(range(100, 241, 10), [2, 5, 9, 13, 19, 26, 37, 47, 59, 69, 78, 86, 92, 97, 99])),
    "reading": list(zip(range(110, 241, 10), [1, 2, 3, 5, 9, 14, 22, 28, 40, 54, 69, 83, 93, 98])),
    "writing_translation": list(zip(range(85, 182, 8), [1, 3, 6, 14, 24, 38, 51, 66, 79, 88, 93, 97, 99])),
}
FOLLOWUPS = {"preparation": "上次考试前，你大致怎样准备？", "reading_completion": "上次考试的阅读有没有做完？"}
METHODS = {
    "reading": ("阅读：找到答案依据", "先用一篇未做过的阅读检查卡点。读不懂、定位慢和选项判断不同，需要分别处理。",
        ["先独立作答，记下用时、没做完和拿不准的位置；时间到了可以先暂停。", "不看答案补做，再核对原文。比较两次作答只用于发现线索，不能据此给能力定级。", "每道错题写清原文依据、正确选项的改写，以及自己误选的原因。"], "换一篇未做过的短文时，能独立找到依据并解释选项，而不只是记住旧题答案。"),
    "listening": ("听力：查清没听懂的位置", "用短段录音保留独立听的机会。区分词句本身不理解、看懂却听不出、听懂却选错。",
        ["原速独立听并作答，随后不看原文重听影响答题的片段。", "核对原文，查清关键词和连接关系；有原文支持时再跟读关键句。", "关掉原文重新听，隔一天再听一次；材料暂未提供原文时，先记录卡点，不猜造原句。"], "关闭文本后能跟上关键意思，并指出支持答案的信息。不要把播放时长当作学会。"),
    "writing": ("写作：先表达清楚，再修改", "合并的写译成绩不能单独说明作文问题。先留一份自己的初稿，再检查内容与语言。",
        ["按题目要求先列观点、理由和例子，用自己能控制的句子写一小段。", "依次检查是否切题、句子是否完整、时态和单复数；保留原稿再做修改。", "对 AI 建议逐处核对原文和题目，隔几天重新表达反复出错的句子。"], "能说清自己改了什么、为什么改；下一次独立写时能减少同类错误。"),
    "translation": ("翻译：保留信息，写成完整句子", "先把原文中的人物、动作和关系表达完整，再处理修饰成分。暂不依据合并分断定翻译较弱。",
        ["拆清谁做了什么，标出时间、原因和转折等必须保留的信息。", "先用意思准确的简单表达完成初稿，再检查漏译、句子结构和词语搭配。", "对照反馈修改后，隔一段时间盖住旧译文重新表达关键句。"], "核心信息不遗漏，句子能够独立成立，并能解释自己采用的表达。"),
    "vocabulary": ("词汇：放回原句，先回忆再核对", "优先整理真正阻碍阅读或听力理解的词和搭配；收藏数量不代表已经掌握。",
        ["从练习中选出影响理解的词，连同原句、当前义项和常见搭配一起记录。", "遮住释义先回忆，再翻面核对；词义与拼写分别练习，不把看着眼熟当作记住。", "先处理到期复习，再安排少量新词，并在下一次阅读或听力中检查能否认出。"], "换到新句子里仍能理解这一义项，需要输出时也能正确使用。"),
}


def snapshot(prefs: dict) -> dict:
    # Vocabulary settings have a separate flow; changing them must not invalidate advice.
    return {k: v for k, v in prefs.items() if k not in {"daily_new_words", "word_order"}}


def learner_context(prefs: dict) -> dict:
    """Translate internal choices before the model writes student-facing prose."""
    return {**prefs,
            "mode": {"balanced": "均衡备考", "foundation": "巩固基础", "exam": "考前冲刺"}[prefs["mode"]],
            "focus": [LABELS[k] for k in prefs["focus"]],
            "preparation": {"unknown": "尚未填写", "none": "上次未专门准备", "irregular": "上次零散准备", "regular": "上次有规律准备"}[prefs["preparation"]],
            "reading_completion": {"unknown": "尚未填写", "finished": "上次阅读已做完", "unfinished": "上次阅读未做完", "not_taken": "尚未参加过考试"}[prefs["reading_completion"]]}


def fingerprint(prefs: dict) -> str:
    return hashlib.sha256((VERSION + json.dumps(snapshot(prefs), sort_keys=True, ensure_ascii=False)).encode()).hexdigest()


def facts(prefs: dict) -> dict:
    today = learning.now().astimezone(dt.timezone(dt.timedelta(hours=8))).date()
    date = dt.date.fromisoformat(prefs["exam_date"]) if prefs.get("exam_date") else None
    days = (date - today).days if date else None
    refs = []
    for kind, bands in NORMS.items():
        value = prefs.get(kind + "_score")
        if value is None:
            continue
        lower = max((rank for score, rank in bands if score <= value), default=0)
        upper = min((rank for score, rank in bands if score >= value), default=100)
        refs.append({"kind": kind, "score": value, "percentile_range": [lower, upper]})
    total, target = prefs.get("total_score"), prefs.get("target_score")
    return {"today": str(today), "days_to_exam": days, "date_state": "missing" if days is None else "past" if days < 0 else "today" if days == 0 else "upcoming",
            "score_gap": target - total if total is not None and target is not None else None,
            "score_reference": refs, "unknown_fields": [k for k in FOLLOWUPS if prefs.get(k, "unknown") == "unknown"],
            "basis": "你填写的情况与历史成绩；尚未用本站练习验证", "daily_minutes": prefs["daily_minutes"]}


def initial_priority(prefs: dict) -> str:
    if prefs["focus"]:
        return prefs["focus"][0]
    refs = facts(prefs)["score_reference"]
    if len(refs) >= 2:
        lowest = min(refs, key=lambda r: sum(r["percentile_range"]))["kind"]
        return "writing" if lowest == "writing_translation" else lowest
    return "vocabulary" if prefs["mode"] == "foundation" else "reading"


def basic_text(prefs: dict) -> dict:
    priority = initial_priority(prefs)
    return {"summary": "先从你选择的重点和每天能投入的时间开始。下面提供可立即使用的基础安排；具体卡点还需要通过独立作答和核对来了解。",
            "score_analysis": basic_score_analysis(prefs),
            "priority_kind": priority, "rationale": "优先参考你勾选的内容；有多个分项时结合历史常模参照选择起点。信息不足时先尝试一项短练。",
            "uncertainty": "目前还不能确定主要困难来自词句理解、时间分配还是答题判断。保留首次作答和卡点，再逐步调整安排。",
            "sections": [{"kind": k, "title": v[0], "body": v[1] + "\n\n" + "\n".join(f"{i}. {step}" for i, step in enumerate(v[2], 1)) + "\n\n**怎样检查**：" + v[3]} for k, v in METHODS.items()],
            "target_breakdown": None,
            "plan_explanation": f"你填写的每天可用时间是 {prefs['daily_minutes']} 分钟。先在这个预算内完成练习与核对，未完成的材料可在后续分配的时段内继续；完整模拟需要另外留出完整时段。",
            "closing": "先完成一个能核对的小步骤，再观察相同问题是否还会出现。成绩单帮助你安排起点，后续独立练习留下的证据，才是继续调整重点的依据。",
            **schedule_text(prefs),
            "followup_keys": facts(prefs)["unknown_fields"]}


def basic_score_analysis(prefs: dict) -> str:
    labels = {"total_score": "总分", "listening_score": "听力", "reading_score": "阅读", "writing_translation_score": "写作与翻译合计"}
    entered = "，".join(f"{label}{prefs[key]}分" for key, label in labels.items() if prefs.get(key) is not None)
    text = f"你填写的历史成绩是：{entered}。" if entered else "你尚未填写历史成绩，可以先了解题型并从一小段独立练习开始。"
    text += "听力和阅读的报道分满分各为249，写作与翻译合计为212；这些分数经过常模转换，不能当作答题正确率。[官方分数解释](ref:scores)"
    gap = facts(prefs)["score_gap"]
    if gap is not None:
        text += f"\n\n你填写的目标是{prefs['target_score']}分，与历史总分相差{abs(gap)}分。目标用于讨论复习方向，不是对下一次成绩的预测。"
    else:
        text += "\n\n暂不替你补设目标或分项短板。先留下自己的作答和具体卡点，再判断应该把更多时间放在哪里。"
    return text


def schedule_text(prefs: dict) -> dict:
    """The same authority owns the timetable and every sentence about that timetable."""
    short = prefs["daily_minutes"] < 45
    note = ("按下方安排轮换主项。当天只做一个主项，并在同一时间预算内完成核对、修改或回忆；其他板块留到对应的学习日。"
            if short else "按下方各时段组合主项、短练、词卡和复盘。每个时段只做能完成的一小段，不把未完成的内容叠加到当天预算之外。")
    note += "原卷可暂停续做；完整模拟需要另外留出完整时段，不属于这里的日常短练。"
    days = facts(prefs)["days_to_exam"]
    if days is not None and days <= 0:
        stages = [{"title": "先核对考试日期", "text": "如果考试就在今天，以实际考试安排为先，可跳过短练；如果日期已经过去，请更新后再安排下一轮。暂不增加考前任务。"}]
    elif days is not None and days <= 14:
        stages = [{"title": "剩余时间先处理具体卡点", "text": "沿用下方短练安排，优先回看已经发现的错误与答题步骤。不要临时叠加整套刷题，也不把短期练习当成分数保证。"}]
    else:
        stages = [
            {"title": "起步：留下首次作答和卡点", "text": "按下方第一周安排开始，记录实际用时和具体困难，给核对与修改留出时间。先完成可观察的小步骤，不急于给能力定级。"},
            {"title": "复盘后再调整", "text": "结合未做过的材料检查同类问题是否仍出现，再调整下一轮主项。旧题重做用于巩固，不把记住旧答案当成进步依据。"},
        ]
        if days is not None:
            stages.append({"title": "临近考试时检查完整流程", "text": "如果能另留完整时段，再用保留的新套题检查时间分配与作答流程，并安排复盘；日常可用时间不足时不强塞整套模拟。"})
    return {"week_note": note, "stages": stages}


def generation_facts(prefs: dict, available: list[dict]) -> dict:
    # The model may change the starting priority. Explain the budget without
    # precommitting its prose to a different subject-by-day timetable.
    slots = week_plan(prefs, initial_priority(prefs))[0]["tasks"]
    roles = ["当天主项练习", "核对与修改"] if len(slots) == 2 else ["当天主项练习", "另一项短练", "词卡与原句回忆", "核对与复盘"]
    return {**facts(prefs), "available_actions": available,
            "schedule": schedule_text(prefs),
            "budget_slots": [{"role": role, "minutes": slot["minutes"]} for role, slot in zip(roles, slots)],
            "exam_structure": {"listening": {"weight_percent": 35, "max_reported_score": 249, "exam_minutes": 30},
                "reading": {"weight_percent": 35, "max_reported_score": 249, "exam_minutes": 40,
                            "parts": {"仔细阅读": 20, "长篇匹配": 10, "选词填空": 5}},
                "writing": {"weight_percent": 15, "exam_minutes": 30},
                "translation": {"weight_percent": 15, "exam_minutes": 30}, "writing_translation_max": 212},
            "schedule_style": "按天轮换一个主项与复盘" if prefs["daily_minutes"] < 45 else "按时段组合主项、短练、词卡与复盘",
            "cet6_listening_types": ["长对话", "听力篇章", "讲话/报道/讲座"],
            "translation_direction": "汉译英：把中文原文译成英文，译文应保持原意并符合英语表达。",
            "unknown_scores": [k for k in ("total_score", "listening_score", "reading_score", "writing_translation_score") if prefs.get(k) is None]}


def week_plan(prefs: dict, priority: str) -> list[dict]:
    budget = prefs["daily_minutes"]
    other = [k for k in ("reading", "listening", "writing", "translation", "vocabulary") if k != priority]
    rotation = [priority, other[0], priority, other[1], other[2], priority, other[3]]
    result = []
    days = facts(prefs)["days_to_exam"]
    horizon = min(7, max(1, days)) if days is not None and days >= 0 else 7
    for day, kind in enumerate(rotation[:horizon], 1):
        if budget < 45:
            review = max(2, budget // 4)
            tasks = [{"kind": kind, "title": f"一小段{LABELS[kind]}练习", "minutes": budget - review},
                     {"kind": kind, "title": "核对依据、修改或回忆", "minutes": review}]
        else:
            review, words = max(5, budget // 6), max(5, budget // 6)
            secondary = "listening" if kind != "listening" else "reading"
            supplement = budget // 4
            tasks = [{"kind": kind, "title": f"{LABELS[kind]}重点练习", "minutes": budget - review - words - supplement},
                     {"kind": secondary, "title": f"{LABELS[secondary]}短练", "minutes": supplement},
                     {"kind": "vocabulary", "title": "到期词卡与原句回忆", "minutes": words},
                     {"kind": kind, "title": "核对、订正与复盘", "minutes": review}]
        result.append({"day": day, "kind": kind, "minutes": sum(t["minutes"] for t in tasks), "tasks": tasks})
    return result


def actions(user: str, notebook: str, priority: str) -> list[dict]:
    from .cet6_exams import catalogue
    items = catalogue(user, notebook)["items"]
    result = []
    for kind in dict.fromkeys([priority, "reading", "listening", "writing", "translation", "vocabulary"]):
        if kind == "vocabulary":
            result.append({"kind": kind, "label": "开始词卡学习", "paper_id": "", "source": "本站六级词汇"})
        else:
            available = next((p for p in items if p.get("ready") and p.get("counts", {}).get(kind)), None)
            if available:
                result.append({"kind": kind, "label": f"进入{LABELS[kind]}真题", "paper_id": available["id"], "source": available["title"]})
    return result


def _running(data: dict) -> bool:
    if data.get("status") != "running":
        return False
    try:
        return (learning.now() - dt.datetime.fromisoformat(data["started_at"])).total_seconds() < CLAIM_TTL
    except (KeyError, ValueError, TypeError):
        return False


def _find(db, user: str, notebook: str):
    return db.scalar(select(Cet6Advice).where(Cet6Advice.notebook_id == notebook, Cet6Advice.user_id == user))


def _public(user: str, notebook: str, data: dict, current: dict) -> dict:
    value = copy.deepcopy(data)
    prefs = value.get("input", snapshot(current["preferences"]))
    text = value.get("content") or basic_text(prefs)
    if value.get("status") == "running" and not _running(value):
        value.update(status="failed", message="上次生成未完成，已填信息保留。可以重试生成建议。")
    return {**value, "status": value.get("status", "empty"), "input": prefs,
            "stale_reason": "profile" if snapshot(prefs) != snapshot(current["preferences"]) else "report_update",
            "profile_revision": current["revision"], "stale": bool(value.get("input_hash") and value["input_hash"] != fingerprint(current["preferences"])),
            "facts": facts(prefs), "content": text, "week": week_plan(prefs, text["priority_kind"]),
            "actions": actions(user, notebook, text["priority_kind"]), "sources": REFERENCES}


def get(user: str, notebook: str) -> dict:
    learning.check(user, notebook)
    current = learning.profile(user, notebook)
    with session() as db:
        row = _find(db, user, notebook)
        return _public(user, notebook, row.data if row else {}, current)


def request(user: str, notebook: str, profile_revision: int) -> tuple[dict, str | None]:
    learning.check(user, notebook)
    current = learning.profile(user, notebook)
    if not current["revision"] or current["revision"] != profile_revision:
        raise HTTPException(409, "学习情况已变化，请重新读取后再生成；已填写的信息会保留。")
    prefs, claim = snapshot(current["preferences"]), str(uuid4())
    digest = fingerprint(prefs)
    with session() as db:
        row = _find(db, user, notebook)
        if row is None:
            row = Cet6Advice(notebook_id=notebook, user_id=user, data={}, revision=0)
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                row = _find(db, user, notebook)
        if row is None:
            raise HTTPException(409, "建议记录正在建立，请重试。")
        old = row.data
        if old.get("input_hash") == digest and (old.get("status") == "ready" or _running(old)):
            return _public(user, notebook, old, current), None
        if _running(old):
            raise HTTPException(409, "上一份建议仍在生成，完成后可按新情况更新。")
        data = {"status": "unavailable" if is_demo() else "running", "claim": claim, "input_hash": digest,
                "input": prefs, "started_at": learning.now().isoformat(), "content": basic_text(prefs), "version": VERSION}
        if is_demo():
            data["message"] = "当前演示环境未连接真实 AI。以下是按已填信息整理的基础安排。"
        previous = {k: old[k] for k in ("content", "input", "generated_at", "model") if k in old} if old.get("status") == "ready" else old.get("previous")
        if previous:
            data["previous"] = previous
        changed = db.execute(update(Cet6Advice).where(Cet6Advice.notebook_id == notebook, Cet6Advice.user_id == user,
                    Cet6Advice.revision == row.revision).values(data=data, revision=row.revision + 1))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "另一页面已开始生成，请重新读取建议。")
        db.commit()
    return _public(user, notebook, data, current), claim if data["status"] == "running" else None


def validate_text(raw: str, prefs: dict) -> dict:
    payload = parse_json(raw)
    if not isinstance(payload, dict):
        raise ValueError("Advice must be an object")
    # The model cannot rewrite the budget or invent an exam timeline.
    checked = AdviceText.model_validate({**payload, **schedule_text(prefs)}).model_dump()
    if set(checked["followup_keys"]) - set(facts(prefs)["unknown_fields"]):
        raise ValueError("Repeated known intake question")
    # Resolve only the supplied citation labels, including reference-style labels
    # without a destination. The model never supplies an external URL.
    def citation_links(text: str) -> str:
        for label, key in (("官方分数解释", "scores"), ("六级笔试结构", "structure"), ("回忆练习研究", "retrieval")):
            text = text.replace(f"[ref:{key}]", f"[{label}](ref:{key})")
            text = re.sub(r"\[" + label + r"\](?!\()", f"[{label}](ref:{key})", text)
        return text
    for field in ("summary", "score_analysis", "rationale", "uncertainty", "plan_explanation", "closing"):
        checked[field] = citation_links(checked[field])
    for section in checked["sections"]:
        section["body"] = citation_links(section["body"])
    if checked["target_breakdown"]:
        checked["target_breakdown"]["reason"] = citation_links(checked["target_breakdown"]["reason"])
    reading = next(s for s in checked["sections"] if s["kind"] == "reading")
    if not re.search(r"(?:未|没)做过|未见过|新(?:的)?(?:题|材料|文章)|陌生(?:材料|文章)", reading["body"]):
        reading["body"] += "\n\n**进步检查**：旧题用于复习；请用未做过的材料检查能否独立找到依据，不把记住旧题答案当作能力提高。"
    prose = json.dumps(checked, ensure_ascii=False)
    model_prose = "\n".join([checked["summary"], checked["score_analysis"], checked["rationale"], checked["uncertainty"],
                            checked["plan_explanation"], checked["closing"],
                            *(s["title"] + "\n" + s["body"] for s in checked["sections"]),
                            (checked["target_breakdown"] or {}).get("reason", "")])
    validate_claims(model_prose, prefs)
    breakdown = checked["target_breakdown"]
    if breakdown:
        keys = ("listening", "reading", "writing_translation")
        if prefs.get("target_score") is None or any(prefs.get(k + "_score") is None for k in keys):
            raise ValueError("Target breakdown needs a selected target and all section scores")
        if sum(breakdown[k] for k in keys) != prefs["target_score"]:
            raise ValueError("Target breakdown does not add up to the selected target")
        if prefs.get("total_score") is not None and prefs["target_score"] <= prefs["total_score"]:
            raise ValueError("An already reached target does not need an increase breakdown")
    familiar_words = re.search(r"认识.{0,8}(?:词|单词)|词.{0,8}(?:认识|眼熟|都懂)|单词.{0,5}(?:懂|会)", prefs.get("goal", ""))
    if not familiar_words and re.search(r"你(?:自述|提到|表示|说).{0,8}(?:认识单词|词都认识)", model_prose):
        raise ValueError("Invented learner statement about vocabulary")
    if prefs["daily_minutes"] < 45 and re.search(r"每天.{0,50}(?:还要额外|另加)", model_prose):
        raise ValueError("Methods add work outside the short daily budget")
    for section in checked["sections"]:
        # Referring to the saved budget is different from assigning this subject
        # every day. Keep the former, reject a competing recurring task.
        method = re.sub(r"(?:每天|每日)(?:可用|只有|有|能投入|可投入|可用时间是|可用时间为)?\s*"
                        + str(prefs["daily_minutes"]) + r"\s*分钟", "", section["body"])
        if re.search(r"每天|每日|每周", method):
            raise ValueError("Methods must follow the shared schedule, not add recurring assignments")
    listening = next(s for s in checked["sections"] if s["kind"] == "listening")
    listening_prose = json.dumps(listening, ensure_ascii=False)
    # A correct exclusion (e.g. 不混入四级短篇新闻) is not a recommendation.
    listening_claims = re.sub(r"(?:不要|不应|不能|不)(?:混入|包括|包含|涉及|考|练|选择|使用)(?:四级的?)?(?:短篇新闻|短对话|新闻)", "", listening_prose)
    if re.search(r"短对话|短篇新闻|新闻", listening_claims):
        raise ValueError("Unsupported CET6 listening type")
    translation = next(s for s in checked["sections"] if s["kind"] == "translation")
    if re.search(r"中文自然|汉语自然|译成(?:中文|汉语)|英译汉", json.dumps(translation, ensure_ascii=False)):
        raise ValueError("CET6 translation must be Chinese to English")
    if re.search(r"(?:旧题|记住.{0,4}答案).{0,15}(?:就说明|就代表|足以证明).{0,10}(?:能力|进步)", reading["body"]):
        raise ValueError("Remembered answers cannot demonstrate independent progress")
    if re.search(r"https?://|www\.|<[^>]+>|!\[|javascript:|data:", prose):
        raise ValueError("Unverified URL, image or HTML")
    allowed_refs = {r["id"] for r in REFERENCES}
    if any(key not in allowed_refs for key in re.findall(r"ref:([a-zA-Z0-9_-]+)", model_prose)):
        raise ValueError("Unknown reference marker")
    if any(url not in {f"ref:{key}" for key in allowed_refs} for url in re.findall(r"\]\(([^)]+)\)", model_prose)):
        raise ValueError("Unknown reference")
    return checked


def validate_claims(text: str, prefs: dict) -> None:
    """Check concrete claims, without prohibiting ordinary numerical explanations."""
    clean = re.sub(r"[*_`]", "", text)
    labels = {"总分": "total_score", "听力": "listening_score", "阅读": "reading_score", "写作与翻译合计": "writing_translation_score",
              "写作和翻译": "writing_translation_score", "写译": "writing_translation_score"}
    for sentence in re.split(r"[。！？\n]", clean):
        # Explicit examples may discuss hypothetical values, but cannot become saved goals.
        hypothetical = bool(re.search(r"假设|例如|示例|如果|假如|若", sentence))
        for label, key in labels.items():
            for match in re.finditer(re.escape(label) + r"(?:成绩|得分)?(?:是|为|[:：])?\s*(\d{2,3})(?!\d|\s*(?:分钟|%|％|题|天|次))", sentence):
                if "满分" not in sentence and not hypothetical and int(match[1]) != prefs.get(key):
                    raise ValueError("Reported score differs from saved input")
        for match in re.finditer(r"(?:目标(?:分数)?(?:设为|定为|放在|为|是)?|争取|冲刺)\s*(\d{3})\s*分?", sentence):
            if not hypothetical and int(match[1]) != prefs.get("target_score"):
                raise ValueError("Invented score target")
        for match in re.finditer(r"每天(?:可用|学习|安排|用|投入|有|能投入)?(?:时间(?:是|为)?)?\s*(\d+)\s*分钟", sentence):
            if not hypothetical and int(match[1]) != prefs["daily_minutes"]:
                raise ValueError("Daily time differs from saved input")
        if re.search(r"(?:保证|必定|确保)(?:能|可以|会)?(?:通过|过级|提分|达到\d)", sentence) and not re.search(r"不(?:能|会|可)?(?:保证|确保)|无法保证", sentence):
            raise ValueError("Unsupported score promise")
        if re.search(r"425\s*分?(?:的)?及格线|及格线(?:为|是)\s*425", sentence) and not re.search(r"不是|并非|没有|不设", sentence):
            raise ValueError("CET has no official pass line")
        if re.search(r"(?:你的问题|问题本质|根本原因).{0,10}(?:就是|是|在于)词汇量(?:不够|不足)", sentence) and not re.search(r"不能|无法|不应|未能", sentence):
            raise ValueError("A score cannot diagnose vocabulary size")
        if re.search(r"(?:同等|相同).{0,6}(?:分差|报道分).{0,40}影响更大", sentence) and not re.search(r"不能|不应|并非|不是", sentence):
            raise ValueError("Reported-score points must not be weighted twice")
    if re.search(r"满分.{0,20}248\.5|(?:写译|写作和翻译|写作与翻译).{0,8}满分.{0,3}213", clean):
        raise ValueError("Incorrect reported-score maximum")


async def generate(user: str, notebook: str, claim: str) -> None:
    # BackgroundTasks may outlive middleware; explicitly bind the authenticated owner.
    token = current_user_context.set(user)
    try:
        with session() as db:
            row = _find(db, user, notebook)
            if row is None or row.data.get("claim") != claim:
                return
            data = copy.deepcopy(row.data)
        prefs = data["input"]
        try:
            with course_scope(user, notebook):
                call = invoke_learning_prompt("english.cet6_advice", learner_input=json.dumps(learner_context(prefs), ensure_ascii=False),
                    facts=json.dumps(generation_facts(prefs, actions(user, notebook, initial_priority(prefs))), ensure_ascii=False),
                    references=json.dumps(REFERENCES, ensure_ascii=False))
                from .model_preferences import resolve
                route = resolve(call.prompt)
                settings = get_settings()
                provider = active_provider()
                model = route["model"] if route else getattr(settings, provider + "_model", provider)
                raw = await asyncio.wait_for(llm_complete(call.prompt, system=call.system, max_tokens=12000,
                    temperature=.25, reasoning_mode="enabled", json_mode=True, json_object=True,
                    allow_model_fallback=False, allow_mock_fallback=False), timeout=TIMEOUT)
                content = validate_text(raw, prefs)
            data.update(status="ready", content=content, model=model, generated_at=learning.now().isoformat(), prompt_skill=call.metadata())
        except (Exception, asyncio.CancelledError) as exc:
            logging.getLogger(__name__).warning("CET6 onboarding advice failed (%s)", type(exc).__name__)
            data.update(status="failed", message="AI 建议暂未生成成功。你的信息已保存，可先使用下面的基础安排，或重试生成。")
        with session() as db:
            row = _find(db, user, notebook)
            if row is None or row.data.get("claim") != claim:
                return
            db.execute(update(Cet6Advice).where(Cet6Advice.notebook_id == notebook, Cet6Advice.user_id == user,
                Cet6Advice.revision == row.revision).values(data=data, revision=row.revision + 1))
            db.commit()
    finally:
        current_user_context.reset(token)
