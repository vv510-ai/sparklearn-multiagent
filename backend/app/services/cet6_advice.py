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

VERSION = "cet6-advice-v2-20261004"
TIMEOUT = 120
CLAIM_TTL = 180
LABELS = learning.LABELS
REFERENCES = [
    {"id": "scores", "title": "中国教育考试网 · 分数解释", "url": "https://www.neea.edu.cn/html1/folder/19081/5124-1.htm",
     "checked_on": "2026-10-04", "supports": "报道分采用常模转换，不设及格线；听力与阅读各 249，写作翻译合计 212。分项常模位置只作历史参照，不代表当前考生排名。"},
    {"id": "structure", "title": "中国教育考试网 · 六级笔试结构", "url": "https://cet.neea.edu.cn/html1/report/16123/201-1.htm",
     "checked_on": "2026-10-04", "supports": "听力和阅读各占 35%，写作与翻译各占 15%；阅读参考用时 40 分钟，听力、写作、翻译各 30 分钟。"},
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
    # Vocabulary quota has a separate save flow; changing it must not invalidate advice.
    return {k: v for k, v in prefs.items() if k != "daily_new_words"}


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
            "priority_kind": priority, "rationale": "优先参考你勾选的内容；有多个分项时结合历史常模参照选择起点。信息不足时先尝试一项短练。",
            "uncertainty": "目前还不能确定主要困难来自词句理解、时间分配还是答题判断。保留首次作答和卡点，再逐步调整安排。",
            "sections": [{"kind": k, "title": v[0], "analysis": v[1], "steps": list(v[2]), "check": v[3]} for k, v in METHODS.items()],
            **schedule_text(prefs),
            "followup_keys": facts(prefs)["unknown_fields"]}


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
    return {**facts(prefs), "available_actions": available,
            "schedule": schedule_text(prefs),
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
    prose = json.dumps(checked, ensure_ascii=False)
    model_prose = json.dumps({k: v for k, v in checked.items() if k not in {"week_note", "stages"}}, ensure_ascii=False)
    if re.search(r"\d", model_prose):
        raise ValueError("Numeric advice belongs to the verified interface")
    familiar_words = re.search(r"认识.{0,8}(?:词|单词)|词.{0,8}(?:认识|眼熟|都懂)|单词.{0,5}(?:懂|会)", prefs.get("goal", ""))
    if not familiar_words and re.search(r"你(?:自述|提到|表示|说).{0,8}(?:认识单词|词都认识)", model_prose):
        raise ValueError("Invented learner statement about vocabulary")
    if any(re.search(r"每天|每日|每周", json.dumps(s, ensure_ascii=False)) for s in checked["sections"]):
        raise ValueError("Methods must not add a competing schedule")
    listening = next(s for s in checked["sections"] if s["kind"] == "listening")
    listening_prose = json.dumps(listening, ensure_ascii=False)
    # A correct exclusion (e.g. 不混入四级短篇新闻) is not a recommendation.
    listening_claims = re.sub(r"(?:不要|不应|不能|不)(?:混入|包括|包含|涉及|考|练|选择|使用)(?:四级的?)?(?:短篇新闻|短对话|新闻)", "", listening_prose)
    if re.search(r"短对话|短篇新闻|新闻", listening_claims):
        raise ValueError("Unsupported CET6 listening type")
    translation = next(s for s in checked["sections"] if s["kind"] == "translation")
    if re.search(r"中文自然|汉语自然|译成(?:中文|汉语)|英译汉", json.dumps(translation, ensure_ascii=False)):
        raise ValueError("CET6 translation must be Chinese to English")
    reading = next(s for s in checked["sections"] if s["kind"] == "reading")
    if not re.search(r"未做过|新(?:的)?(?:题|材料|文章)|陌生(?:材料|文章)", reading["check"]):
        raise ValueError("Reading progress needs unfamiliar material")
    if re.search(r"https?://|www\.|<[^>]+>|\]\(", prose):
        raise ValueError("Unverified URL or markup")
    for minutes in re.findall(r"每天(?:学习|安排|用|投入)?\s*(\d+)\s*分钟", prose):
        if int(minutes) != prefs["daily_minutes"]:
            raise ValueError("Daily time differs from saved input")
    if re.search(r"(?:保证|一定|必定|确保)(?:能|可以|会)?(?:通过|过级|提分|达到\d)|及格线(?:为|是)?\s*425", prose):
        raise ValueError("Unsupported score promise")
    for target in re.findall(r"(?:目标(?:分数)?(?:设为|定为|放在|为|是)?|争取|冲刺)\s*(\d{3})\s*分?", prose):
        if prefs.get("target_score") is None or int(target) != prefs["target_score"]:
            raise ValueError("Invented score target")
    return checked


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
                call = invoke_learning_prompt("english.cet6_advice", learner_input=json.dumps(prefs, ensure_ascii=False),
                    facts=json.dumps(generation_facts(prefs, actions(user, notebook, initial_priority(prefs))), ensure_ascii=False),
                    references=json.dumps(REFERENCES, ensure_ascii=False))
                from .model_preferences import resolve
                route = resolve(call.prompt)
                settings = get_settings()
                provider = active_provider()
                model = route["model"] if route else getattr(settings, provider + "_model", provider)
                raw = await asyncio.wait_for(llm_complete(call.prompt, system=call.system, max_tokens=10000,
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
