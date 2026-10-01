"""Notebook-owned progress for publisher-authored study material."""
import copy
import datetime as dt
from urllib.parse import urlsplit
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from ..data.study_paths import PATHS, VERSION
from ..models.db import session
from ..models.entities import NotebookStudy
from .learning_scope import ensure_space
from .study_materials import catalogue, ALLOWED_HOSTS


def course_key(course: dict) -> str:
    kind = course.get("kind", "")
    if course.get("source_ids"):
        return ""
    return {"english_scenes": "english", "python_foundations": "python"}.get(kind, kind) if kind in {*PATHS, "english_scenes", "python_foundations"} else ""


def overview(course: dict) -> dict | None:
    key = course_key(course)
    if not key:
        return None
    route = PATHS[key]
    return dict(course=key, title=route["title"], subtitle=route["subtitle"], version=VERSION,
                units=[{k: u[k] for k in ("id", "group", "title")} for u in route["units"]])


def _path(key: str) -> dict:
    path = copy.deepcopy(PATHS[key])
    sources = {m["id"]: m for m in catalogue()["items"]}
    from .textbook_service import python_book
    book = python_book()
    sections = {s["id"]: s for s in book["sections"]}
    for item in path["units"]:
        source = copy.deepcopy(sources[item["material_id"]])
        link = item["url"] or source["url"]
        parsed = urlsplit(link)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password:
            raise ValueError("Unreviewed study path URL")
        source["url"] = link
        item["source"] = source
        item["excerpts"] = [{**sections[s], "version": book["version"], "license": book["license"],
                              "license_url": book["license_url"]} for s in item["sections"]]
    return {**path, "course": key, "version": VERSION}


def _read(row, key: str) -> dict:
    return {"revision": row.revision if row else 0,
            "last_unit": row.data.get("last_unit", "") if row and row.course_key == key else "",
            "units": copy.deepcopy(row.data.get("units", {})) if row and row.course_key == key else {}}


def get(user: str, notebook: str) -> dict:
    space = ensure_space(user, notebook)
    key = course_key(space.course)
    if not key:
        raise HTTPException(404, "这门课使用你自己的资料，请从已上传的教材开始学习。")
    with session() as db:
        row = db.scalar(select(NotebookStudy).where(NotebookStudy.notebook_id == notebook, NotebookStudy.user_id == user))
        return {"path": _path(key), "progress": _read(row, key), "notebook_id": notebook}


def save(user: str, notebook: str, unit_id: str, revision: int, version: str, data: dict) -> dict:
    space = ensure_space(user, notebook)
    key = course_key(space.course)
    if not key or unit_id not in {u["id"] for u in PATHS[key]["units"]}:
        raise HTTPException(404, "本课程没有这节内容，请重新打开课程。")
    if version != VERSION:
        raise HTTPException(409, "课程内容已更新，请保留草稿后重新加载。")
    if data["completed"] and (not all(data[k] for k in ("read", "practiced", "checked")) or len(data["notes"].strip()) < 3):
        raise HTTPException(422, "完成前请确认阅读、练习与核对，并记下一条学习结果。")
    with session() as db:
        row = db.scalar(select(NotebookStudy).where(NotebookStudy.notebook_id == notebook, NotebookStudy.user_id == user))
        if row is None:
            if revision != 0:
                raise HTTPException(409, "学习记录已变化，请保留草稿后重新加载。")
            row = NotebookStudy(notebook_id=notebook, user_id=user, course_key=key, data={}, revision=0)
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                row = db.scalar(select(NotebookStudy).where(NotebookStudy.notebook_id == notebook, NotebookStudy.user_id == user))
                if row is None:
                    raise
        current = _read(row, key)
        previous = current["units"].get(unit_id, {})
        if row.revision != revision:
            if row.revision == revision + 1 and all(previous.get(k) == v for k, v in data.items()):
                return current
            raise HTTPException(409, "另一页面已更新进度。当前草稿保留，请复制后重新加载。")
        payload = {"last_unit": unit_id, "units": {**current["units"], unit_id: {**data, "saved_at": dt.datetime.now(dt.timezone.utc).isoformat()}}}
        changed = db.execute(update(NotebookStudy).where(NotebookStudy.notebook_id == notebook,
            NotebookStudy.user_id == user, NotebookStudy.revision == revision).values(data=payload, course_key=key, revision=revision + 1))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "进度刚刚更新，请保留草稿后重新加载。")
        db.commit()
        db.refresh(row)
        return _read(row, key)
