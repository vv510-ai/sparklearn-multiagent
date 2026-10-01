"""Curated source links and private notes; clicks never imply mastery."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from ..models.db import session
from ..models.entities import MaterialStudy

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "study_materials_v1.json"
ALLOWED_HOSTS = {"cet.neea.edu.cn", "cet6.koolearn.com", "cet4-6.xdf.cn", "www.sparke.cn", "detail.youzan.com", "docs.python.org", "cs50.harvard.edu", "exercism.org", "ocw.mit.edu", "www.hello-algo.com", "learnenglish.britishcouncil.org"}

@lru_cache(maxsize=1)
def catalogue() -> dict:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    seen = set()
    for item in data["items"]:
        link = urlsplit(item["url"])
        if link.scheme != "https" or link.hostname not in ALLOWED_HOSTS or link.username or link.password:
            raise ValueError("Unreviewed material URL")
        if item["id"] in seen or item["course"] not in data["courses"]:
            raise ValueError("Invalid material identity")
        seen.add(item["id"])
        if not all(item.get(k) for k in ("title", "provider", "source_role", "kind", "scope", "access", "checked_on", "verification", "task")):
            raise ValueError("Incomplete source review")
    return data

def _view(row: MaterialStudy) -> dict:
    return {"id": row.id, "material_id": row.material_id, "revision": row.revision, **row.data}

def studies(user_id: str) -> dict:
    with session() as db:
        rows = db.scalars(select(MaterialStudy).where(MaterialStudy.user_id == user_id).order_by(MaterialStudy.id)).all()
        return {"items": [_view(row) for row in rows]}

def add(user_id: str, material_id: str) -> dict:
    material = next((m for m in catalogue()["items"] if m["id"] == material_id), None)
    if not material:
        raise HTTPException(404, "资料暂未收录")
    key = hashlib.sha256(f"{user_id}:{material_id}".encode()).hexdigest()
    with session() as db:
        row = db.scalar(select(MaterialStudy).where(MaterialStudy.id == key, MaterialStudy.user_id == user_id))
        if row:
            return _view(row)
        row = MaterialStudy(id=key, user_id=user_id, material_id=material_id, revision=0,
            data={"task": material["task"], "location": "", "notes": "", "minutes": 0, "next_review": None, "status": "planned"})
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            row = db.scalar(select(MaterialStudy).where(MaterialStudy.id == key, MaterialStudy.user_id == user_id))
            if row is None:
                raise
        return _view(row)

def save(user_id: str, study_id: str, revision: int, data: dict) -> dict:
    with session() as db:
        row = db.scalar(select(MaterialStudy).where(MaterialStudy.id == study_id, MaterialStudy.user_id == user_id))
        if row is None:
            raise HTTPException(404, "学习记录不存在")
        if row.revision != revision:
            # A lost response can be retried, but stale tabs cannot clobber newer notes.
            if row.revision == revision + 1 and row.data == data:
                return _view(row)
            raise HTTPException(409, "记录已在其他页面更新。请先复制当前草稿，再重新加载记录。")
        changed = db.execute(update(MaterialStudy).where(MaterialStudy.id == study_id,
            MaterialStudy.user_id == user_id, MaterialStudy.revision == revision).values(data=data, revision=revision + 1))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "记录刚刚更新，请先复制草稿，再重新加载。")
        db.commit()
        db.refresh(row)
        return _view(row)
