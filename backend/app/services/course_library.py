"""Versioned public course publishing and tenant-owned learning progress.

Publishing is an operator/startup operation. Student endpoints never fetch
external documents, rebuild vectors, or execute submitted code.
"""
from __future__ import annotations
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import uuid

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from ..models.db import session
from ..models.entities import CoursePublication, CourseRelease, CourseStudy, LearningSpace, Notebook, Profile, EventLog, WithdrawnCourseSource
from .profile_service import default_profile, ensure_user

BUNDLE_PATH = Path(__file__).resolve().parents[1] / "data/course_library/python-foundations-v1.json"
ENGLISH_BUNDLE_PATH = BUNDLE_PATH.with_name("english-scenes-v1.json")
WITHDRAWN = "该版本的部分材料已停止提供，相关内容暂不可查看；已有作答记录保留。"


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_bundle(bundle: dict) -> None:
    if bundle.get("schema_version") != 1 or not bundle.get("rights", {}).get("public_distribution"):
        raise ValueError("Course has no public distribution basis")
    if not bundle.get("rights", {}).get("license_notice") or not bundle.get("review", {}).get("method"):
        raise ValueError("License or review record missing")
    if bundle.get("kind") == "english_scenes" and not all(bundle.get("rights", {}).get("audio", {}).get(key) for key in ("license_url", "model_license", "model_sha256")):
        raise ValueError("Audio distribution basis missing")
    book = bundle["textbook"]
    sections = {s["id"]: s for s in book["sections"]}
    if len(sections) != len(book["sections"]) or not sections:
        raise ValueError("Duplicate/empty sections")
    for section in sections.values():
        if hashlib.sha256(section["text"].encode()).hexdigest() != section["sha256"]:
            raise ValueError("Source text hash mismatch")
        if book.get("source_kind") == "platform_original":
            expected = f"/api/library/releases/{bundle['release_id']}/sections/{section['id']}"
            if bundle.get("kind") != "english_scenes" or section["url"] != expected:
                raise ValueError("Invalid original source provenance")
        elif not section["url"].startswith("https://docs.python.org/"):
            raise ValueError("Unverified official source")
    lesson_ids, question_ids = set(), set()
    for lesson in bundle["lessons"]:
        if lesson["id"] in lesson_ids:
            raise ValueError("Duplicate objective")
        lesson_ids.add(lesson["id"])
        if bundle.get("kind") == "english_scenes":
            from .english_scene_library import validate_scene
            validate_scene(lesson)
        for key in ("objective", "markdown", "example", "task", "criteria", "review_prompt", "questions", "source_sections"):
            if not lesson.get(key):
                raise ValueError("Incomplete objective: " + key)
        if not set(lesson["source_sections"]) <= sections.keys() or len(lesson["questions"]) < 2:
            raise ValueError("Missing source or alternate practice")
        for q in lesson["questions"]:
            if q["id"] in question_ids or len(q["options"]) != 4 or len(set(q["options"])) != 4:
                raise ValueError("Invalid practice options")
            if not 0 <= q["answer"] < 4 or q["options"][q["answer"]] != q["expected"] or not q["explanation"]:
                raise ValueError("Invalid answer")
            question_ids.add(q["id"])
    if not lesson_ids:
        raise ValueError("No objectives")


def publish(bundle: dict, *, activate: bool = True) -> str:
    """Build before committing; a failed build never changes the active pointer."""
    from ..rag.library_index import build_index
    validate_bundle(bundle)
    content_hash = digest(bundle)
    release_id = bundle["release_id"]
    with session() as db:
        existing = db.get(CourseRelease, release_id)
        if existing and existing.content_hash != content_hash:
            raise ValueError("Release IDs are immutable; use a new ID")
        if existing and existing.status == "withdrawn":
            raise ValueError("Withdrawn releases cannot be republished")
        if _blocked_sources(db, bundle):
            raise ValueError("Withdrawn source cannot be republished")
    index = build_index(bundle)
    with session() as db:
        if _blocked_sources(db, bundle):
            raise ValueError("Withdrawn source cannot be republished")
        row = db.get(CourseRelease, release_id)
        if row and row.content_hash != content_hash:
            raise ValueError("Concurrent release content mismatch")
        if row and row.status == "withdrawn":
            raise ValueError("Release was withdrawn while building")
        if not row:
            row = CourseRelease(id=release_id, course_id=bundle["course_id"], content_hash=content_hash,
                                data=copy.deepcopy(bundle), index=index, status="published")
            db.add(row)
        else:
            row.index = index
        if activate:
            pointer = db.get(CoursePublication, bundle["course_id"])
            if pointer:
                pointer.release_id = release_id
            else:
                db.add(CoursePublication(id=bundle["course_id"], release_id=release_id))
        db.commit()
    return release_id


def bootstrap() -> None:
    for path in (BUNDLE_PATH, ENGLISH_BUNDLE_PATH):
        _bootstrap_bundle(path)


def _bootstrap_bundle(path: Path) -> None:
    from ..rag.library_index import index_identity
    bundle = json.loads(path.read_text(encoding="utf-8"))
    with session() as db:
        row = db.get(CourseRelease, bundle["release_id"])
        pointer = db.get(CoursePublication, bundle["course_id"])
        if row:
            if row.content_hash != digest(bundle):
                raise ValueError("Bundled release changed without a new version")
            if row.status == "withdrawn":
                return
            if row.index.get("identity") == index_identity():
                return
    # Do not downgrade an operator-selected newer version during a restart.
    publish(bundle, activate=not pointer)


def load_release(release_id: str, *, allow_withdrawn: bool = False) -> tuple[dict, dict]:
    with session() as db:
        row = db.get(CourseRelease, release_id)
        if not row:
            raise HTTPException(404, "课程版本不存在")
        if (row.status != "published" or _blocked_sources(db, row.data)) and not allow_withdrawn:
            raise HTTPException(410, WITHDRAWN)
        data, index = copy.deepcopy(row.data), copy.deepcopy(row.index)
        if digest(data) != row.content_hash:
            raise HTTPException(503, "课程完整性检查未通过，请稍后重试")
        return data, index


def is_withdrawn(release_id: str) -> bool:
    if not release_id:
        return False
    with session() as db:
        row = db.get(CourseRelease, release_id)
        return not row or row.status != "published" or _blocked_sources(db, row.data)


def withdraw(release_id: str, reason: str) -> None:
    if not reason.strip():
        raise ValueError("A withdrawal reason is required")
    with session() as db:
        row = db.get(CourseRelease, release_id)
        if not row:
            raise ValueError("Unknown course release")
        row.status, row.withdrawal_reason = "withdrawn", reason[:1000]
        db.commit()


def _blocked_sources(db, bundle: dict) -> bool:
    hashes = [s["sha256"] for s in bundle.get("textbook", {}).get("sections", [])]
    return bool(hashes and db.query(WithdrawnCourseSource.sha256).filter(WithdrawnCourseSource.sha256.in_(hashes)).first())


def withdraw_source(source_sha256: str, reason: str) -> list[str]:
    import re
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha256) or not reason.strip():
        raise ValueError("A valid source SHA-256 and reason are required")
    with session() as db:
        db.merge(WithdrawnCourseSource(sha256=source_sha256, reason=reason[:1000]))
        affected = []
        for row in db.query(CourseRelease).all():
            if any(s["sha256"] == source_sha256 for s in row.data["textbook"]["sections"]):
                row.status, row.withdrawal_reason = "withdrawn", reason[:1000]
                affected.append(row.id)
        db.commit()
    return affected


def provenance(value: object) -> list[dict]:
    """Carry only immutable origin IDs, never nested bodies, across note reuse."""
    origins = set()
    def walk(item):
        if isinstance(item, dict):
            rid = item.get("course_release_id")
            if rid:
                origins.add(str(rid))
            for child in item.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
    walk(value)
    return [{"course_release_id": rid} for rid in sorted(origins)]


def catalogue(user_id: str) -> dict:
    with session() as db:
        pointers = db.query(CoursePublication).all()
        studies = db.query(CourseStudy).filter_by(user_id=user_id).all()
    items = []
    for p in pointers:
        if is_withdrawn(p.release_id):
            continue
        bundle, _ = load_release(p.release_id)
        items.append({k: bundle[k] for k in ("course_id", "release_id", "title", "description", "audience",
            "prerequisites", "scope", "not_covered", "status_label", "review")} | {
            "outline": [{"id": l["id"], "title": l["title"], "objective": l["objective"]} for l in bundle["lessons"]],
            "kind": bundle.get("kind", "python_foundations"),
            "source": {"kind": bundle["textbook"].get("source_kind", "official"), "title": bundle["textbook"]["title"], "version": bundle["textbook"]["version"],
                       "section_count": len(bundle["textbook"]["sections"]), "license": bundle["textbook"]["license"]}})
    return {"items": items, "studies": [{"id": s.id, "release_id": s.release_id, "notebook_id": s.notebook_id,
            "last_lesson": s.data.get("last_lesson"), "withdrawn": is_withdrawn(s.release_id)} for s in studies],
        "other_courses": [
            {"title": "数据结构与算法", "scope": "16 个知识点及基础讲义，完整教材尚未接入"},
            {"title": "高等数学入门", "scope": "4 个入门知识点，尚非整学期高数课程"},
            {"title": "大学英语六级", "scope": "6 个原创训练模块，含合成音频；不是历年真题库"}]}


def course_snapshot(bundle: dict) -> dict:
    book = bundle["textbook"]
    # Immutable source contents live once in CourseRelease, not once per student.
    public_book = {k: copy.deepcopy(v) for k, v in book.items() if k != "sections"}
    public_book["sha256"] = digest(book)
    public_book["sections"] = [{k: v for k, v in s.items() if k != "text"} for s in book["sections"]]
    nodes = [{"id": bundle.get("kp_prefix", "foundation_") + l["id"], "name": l["title"], "desc": l["objective"],
              "chapter": l["title"], "difficulty": 1} for l in bundle["lessons"]]
    return {"title": bundle["title"], "kind": bundle.get("kind", "python_foundations"), "revision": digest(bundle)[:16],
            "course_release_id": bundle["release_id"], "source_ids": [], "sources": [],
            "textbook": public_book, "bank": [], "lessons": {}, "evidence": {},
            "coverage_note": bundle["scope"] + "未覆盖：" + bundle["not_covered"],
            "boundary": bundle["review"]["note"], "graph": {"course_id": bundle["course_id"],
            "course": bundle["title"], "version": 1, "nodes": nodes,
            "edges": [{"from": nodes[i-1]["id"], "to": nodes[i]["id"]} for i in range(1, len(nodes))]}}


def enroll(user_id: str, release_id: str) -> dict:
    ensure_user(user_id)
    bundle, _ = load_release(release_id)
    study_id = "study_" + hashlib.sha256(f"{user_id}:{release_id}".encode()).hexdigest()[:32]
    with session() as db:
        row = db.get(CourseStudy, study_id)
        if not row:
            nb = "nb_" + uuid.uuid4().hex
            data = default_profile()
            data.update(knowledge_mastery={}, learning_topic=bundle["title"])
            db.add(Notebook(id=nb, user_id=user_id, title=bundle["title"], emoji=bundle.get("emoji", "🐍"),
                            session_id="book-" + uuid.uuid4().hex[:16]))
            db.flush()
            db.add(LearningSpace(notebook_id=nb, user_id=user_id, data=data, course=course_snapshot(bundle), path={}, version=1))
            db.add(CourseStudy(id=study_id, user_id=user_id, notebook_id=nb, release_id=release_id,
                               data={"last_lesson": bundle["lessons"][0]["id"], "lessons": {}}, revision=0))
            profile = db.get(Profile, user_id)
            if profile and not profile.data.get("onboarding_completed"):
                profile.data = {**profile.data, "onboarding_completed": True}
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                if not db.get(CourseStudy, study_id):
                    raise
    return state(user_id, study_id)


def _owned(db, user_id: str, study_id: str, *, lock=False):
    q = db.query(CourseStudy).filter_by(id=study_id, user_id=user_id)
    row = (q.with_for_update() if lock else q).first()
    if not row:
        raise HTTPException(404, "学习记录不存在")
    return row


def state(user_id: str, study_id: str) -> dict:
    with session() as db:
        row = _owned(db, user_id, study_id)
        result = {"id": row.id, "notebook_id": row.notebook_id, "release_id": row.release_id,
                  "revision": row.revision, "progress": copy.deepcopy(row.data)}
    if is_withdrawn(row.release_id):
        # Preserve counts and submitted work; suppress cached source-derived feedback.
        result.update(withdrawn=True, notice=WITHDRAWN)
        for item in result["progress"].get("lessons", {}).values():
            for attempt in item.get("attempts", []):
                attempt.pop("explanation", None)
                attempt.pop("answer_text", None)
        return result
    bundle, _ = load_release(row.release_id)
    result.update(withdrawn=False, kind=bundle.get("kind", "python_foundations"), title=bundle["title"], review=bundle["review"],
        outline=[{"id": l["id"], "title": l["title"], "objective": l["objective"]} for l in bundle["lessons"]])
    return result


def lesson(user_id: str, study_id: str, lesson_id: str) -> dict:
    current = state(user_id, study_id)
    bundle, _ = load_release(current["release_id"])
    selected = next((x for x in bundle["lessons"] if x["id"] == lesson_id), None)
    if not selected:
        raise HTTPException(404, "课程章节不存在")
    progress = current["progress"]["lessons"].get(lesson_id, {})
    attempts = progress.get("attempts", [])
    index = len(attempts)
    now = dt.datetime.now(dt.timezone.utc)
    due = progress.get("next_due_at")
    ready = not due or now >= dt.datetime.fromisoformat(due)
    question = selected["questions"][index] if index < len(selected["questions"]) and ready else None
    extra = {}
    if bundle.get("kind") == "english_scenes":
        from .english_scene_library import public_scene
        extra["scene"] = public_scene(selected["scene"], bundle["release_id"], lesson_id)
        if progress.get("work", {}).get("reference_viewed"):
            extra["work_reference"] = selected["work_reference"]
    return extra | {k: copy.deepcopy(selected[k]) for k in ("id", "title", "objective", "markdown", "example", "task", "criteria", "review_prompt", "authoring")} | {
        "release_id": bundle["release_id"], "revision": current["revision"], "progress": progress,
        "question": {k: question[k] for k in ("id", "stem", "code", "options")} if question else None,
        "practice_status": "active" if question else "scheduled" if index < len(selected["questions"]) else "exhausted",
        "sources": [{k: copy.deepcopy(s[k]) for k in ("id", "title", "url", "text", "sha256")}
                    | {"version": bundle["textbook"]["version"], "source_type": bundle["textbook"].get("source_kind", "official")}
                    for s in bundle["textbook"]["sections"] if s["id"] in selected["source_sections"]],
        "license": bundle["textbook"]["license"], "license_notice": bundle["rights"]["license_notice"]}


def update_progress(user_id: str, study_id: str, lesson_id: str, req: dict) -> dict:
    # Serialise by learner row on PostgreSQL; revision rejects delayed browser writes.
    with session() as db:
        row = _owned(db, user_id, study_id, lock=True)
        bundle, _ = load_release(row.release_id)
        selected = next((x for x in bundle["lessons"] if x["id"] == lesson_id), None)
        if not selected:
            raise HTTPException(404, "课程章节不存在")
        data = copy.deepcopy(row.data)
        progress = data.setdefault("lessons", {}).setdefault(lesson_id, {})
        attempts = progress.setdefault("attempts", [])
        if req["action"] == "answer":
            repeated = next((x for x in attempts if x["question_id"] == req.get("question_id")), None)
            if repeated:
                if repeated["choice"] != req.get("choice") or repeated["assisted"] != req.get("assisted", False):
                    raise HTTPException(409, "这道题已经提交，原作答保留")
                return state(user_id, study_id)
        if req["revision"] != row.revision:
            raise HTTPException(409, "进度已更新，请刷新后继续；已有记录保留")
        if req["action"] == "answer":
            index = len(attempts)
            if index >= len(selected["questions"]):
                raise HTTPException(409, "本节新题已用完")
            due = progress.get("next_due_at")
            if due and dt.datetime.now(dt.timezone.utc) < dt.datetime.fromisoformat(due):
                raise HTTPException(409, "下一道新题安排在隔日复习，当前作答已经保存")
            q = selected["questions"][index]
            if req.get("question_id") != q["id"] or req.get("choice") not in range(4):
                raise HTTPException(422, "题目或选项与当前练习不符")
            assisted = bool(req.get("assisted"))
            attempts.append({"question_id": q["id"], "choice": req["choice"], "assisted": assisted,
                "correct": req["choice"] == q["answer"], "independent": not assisted,
                "answer_text": q["options"][q["answer"]], "explanation": q["explanation"],
                "submitted_at": dt.datetime.now(dt.timezone.utc).isoformat()})
            progress["next_due_at"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat() if index + 1 < len(selected["questions"]) else None
        elif req["action"] == "read":
            progress["read"] = True
        elif req["action"] == "work":
            if not req.get("work", "").strip():
                raise HTTPException(422, "请先写下你的回应")
            viewed = progress.get("work", {}).get("reference_viewed", False)
            progress["work"] = {"text": req.get("work", ""), "self_checked": req.get("self_checked", []),
                "assisted": bool(req.get("assisted")) or viewed or progress.get("work", {}).get("assisted", False), "reference_viewed": viewed, "status": "self_reported",
                "notice": ("回应与自查已保存；" + ("已查看参考示例，后续修改记为参考后作答。" if viewed else "尚未查看参考示例。") + "没有口语评分，不据此判定掌握。") if selected.get("scene") else
                          "这是你提交的代码和自查记录，服务器没有运行它，也未据此判定掌握。"}
        elif req["action"] == "reveal_work":
            if not selected.get("scene") or not progress.get("work", {}).get("text", "").strip():
                raise HTTPException(422, "先保存自己的回应，再查看参考示例")
            progress["work"].update(reference_viewed=True, assisted=True,
                notice="已查看参考示例，后续修改记为参考后作答；没有口语评分，不据此判定掌握。")
        elif req["action"] == "listen":
            audio = selected.get("scene", {}).get("audio", {})
            if not audio or req.get("audio_sha256") != audio["sha256"]:
                raise HTTPException(422, "音频版本与当前课程不符")
            from .english_scene_library import media_file
            try:
                media_file(audio)
            except ValueError:
                raise HTTPException(503, "音频暂不可用，可继续文字学习")
            progress["listening"] = {"status": "client_reported", "audio_sha256": audio["sha256"],
                "reported_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "notice": "浏览器报告完整播放；不代表听懂、跟读或掌握。"}
        else:
            raise HTTPException(422, "未知学习记录类型")
        data["last_lesson"] = lesson_id
        changed = db.query(CourseStudy).filter_by(id=row.id, user_id=user_id, revision=req["revision"]).update(
            {"data": data, "revision": req["revision"] + 1}, synchronize_session=False)
        if changed != 1:
            db.rollback()
            raise HTTPException(409, "进度已更新，请刷新后继续")
        db.commit()
    return state(user_id, study_id)


def report_issue(user_id: str, study_id: str, lesson_id: str, text: str) -> None:
    with session() as db:
        row = _owned(db, user_id, study_id)
        db.add(EventLog(user_id=user_id, etype="course_content_report", payload={
            "notebook_id": row.notebook_id, "course_release_id": row.release_id,
            "lesson_id": lesson_id, "description": text}))
        db.commit()


def blocked_payload(value: object) -> bool:
    """Check durable provenance at read/export/reuse time; do not renumber cites."""
    if isinstance(value, dict):
        rid = value.get("course_release_id")
        if rid and is_withdrawn(str(rid)):
            return True
        return any(blocked_payload(v) for v in value.values() if isinstance(v, (dict, list)))
    if isinstance(value, list):
        return any(blocked_payload(v) for v in value)
    return False


def public_message(row) -> dict:
    evidence = copy.deepcopy(row.source_evidence or [])
    blocked = is_withdrawn(getattr(row, "course_release_id", "") or "") or blocked_payload(evidence)
    if blocked and row.role == "assistant":
        evidence = [{"index": x.get("index", i + 1), "preview": WITHDRAWN, "excerpt": "", "withdrawn": True}
                    for i, x in enumerate(evidence)]
    return {"role": row.role, "content": WITHDRAWN if blocked and row.role == "assistant" else row.content,
            "source_evidence": evidence}
