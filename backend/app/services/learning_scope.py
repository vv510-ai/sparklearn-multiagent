"""Request-local learning spaces. Account identity never doubles as course mastery."""
from __future__ import annotations

import copy
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import inspect

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

_scope: ContextVar[dict | None] = ContextVar("learning_space", default=None)
_scope_user: ContextVar[str] = ContextVar("learning_user", default="")


def learning_user() -> str:
    return _scope_user.get()


def current_space() -> dict | None:
    return _scope.get()


def notebook_id() -> str:
    return str((_scope.get() or {}).get("notebook_id") or "")


def graph_index(graph: dict) -> dict:
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    edges = graph.get("edges", [])
    adj, indeg = {k: [] for k in nodes}, {k: 0 for k in nodes}
    for edge in edges:
        if edge["from"] not in nodes or edge["to"] not in nodes:
            raise ValueError("课程先修关系引用了不存在的知识点")
        adj[edge["from"]].append(edge["to"])
        indeg[edge["to"]] += 1
    return {**graph, "nodes": nodes, "adj": adj, "indeg": indeg,
            "detail_edges": [], "detail_node_count": 0, "version": graph.get("version", 1)}


def ensure_space(user_id: str, space_id: str):
    from ..models.db import session
    from ..models.entities import LearningSpace
    from .notebook_service import ensure_notebook_owner
    from .profile_service import default_profile, ensure_user
    ensure_user(user_id)
    notebook = ensure_notebook_owner(user_id, space_id)
    with session() as db:
        row = db.get(LearningSpace, space_id)
        if row is None:
            profile = default_profile()
            profile["knowledge_mastery"] = {}
            profile["learning_topic"] = notebook.title
            row = LearningSpace(notebook_id=space_id, user_id=user_id, data=profile,
                course={"title": notebook.title, "kind": "unconfigured", "source_ids": [],
                        "graph": {"course": notebook.title, "course_id": space_id, "nodes": [], "edges": []}},
                path={}, version=1)
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                # The first profile and course reads can arrive concurrently.
                db.rollback()
                row = db.get(LearningSpace, space_id)
                if row is None:
                    raise
        if row.user_id != user_id:
            raise HTTPException(404, "学习空间不存在")
        return row


@contextmanager
def course_scope(user_id: str, space_id: str = "", *, snapshot: dict | None = None):
    if not space_id:
        token = _scope.set(None)
    else:
        row = ensure_space(user_id, space_id)
        course = copy.deepcopy(snapshot or row.course)
        if course.get("course_release_id"):
            from .course_library import is_withdrawn, WITHDRAWN
            if is_withdrawn(course["course_release_id"]):
                raise HTTPException(410, WITHDRAWN)
        token = _scope.set({"user_id": user_id, "notebook_id": space_id,
            "course": course, "graph": graph_index(course["graph"]), "profile": copy.deepcopy(row.data)})
    user_token = _scope_user.set(user_id)
    try:
        yield current_space()
    finally:
        _scope.reset(token)
        _scope_user.reset(user_token)


def profile_row(db, user_id: str):
    from ..models.entities import LearningSpace, Profile
    space = current_space()
    if space:
        if space["user_id"] != user_id:
            raise HTTPException(403, "学习记录不属于当前用户")
        row = db.scalar(select(LearningSpace).where(LearningSpace.notebook_id == notebook_id(), LearningSpace.user_id == user_id).with_for_update())
        if not row or row.course.get("revision") != space["course"].get("revision"):
            raise HTTPException(409, "课程范围已更新，请刷新当前课程后继续；已有作答仍保留")
        return row
    return db.scalar(select(Profile).where(Profile.user_id == user_id).with_for_update())


def event_in_scope(payload: dict) -> bool:
    # Existing operator-only final-review fixtures restore an account baseline.
    if (payload or {}).get("demo_final_review"):
        return not notebook_id()
    if str((payload or {}).get("notebook_id") or "") != notebook_id():
        return False
    revision = (payload or {}).get("course_revision")
    return not revision or revision == (current_space() or {}).get("course", {}).get("revision")


def selected_sources(source_ids: list[str]) -> list[str]:
    from ..rag.ingest import COURSE_SCOPE_ID
    space = current_space()
    if not space or space["course"].get("kind") == "ds_algo":
        return source_ids
    uploads = [s for s in source_ids if s != COURSE_SCOPE_ID]
    if space["course"].get("textbook") and not uploads:
        # Carry the selected course source through every generation/tutor
        # entrypoint. Otherwise named courses look like ungrounded custom
        # topics and the agents skip retrieval before the retriever runs.
        return [COURSE_SCOPE_ID]
    return uploads


def scoped_endpoint(fn):
    """Bind a validated notebook, stored quiz or assessment before any course lookup.

    wraps preserves FastAPI's request signature. All scope resets are in finally;
    graph tasks establish their own scope because streaming outlives the route.
    """
    signature = inspect.signature(fn, eval_str=True)

    def resolve(args, kwargs):
        from ..auth import require_current_user_id
        from ..models.db import session
        from ..models.entities import AssessmentSession, LearningSpace, Resource, ReviewItem
        bound = signature.bind(*args, **kwargs).arguments
        req = bound.get("req")
        user_id = getattr(req, "user_id", None) or bound.get("user_id") or require_current_user_id()
        space_id = getattr(req, "notebook_id", "") or bound.get("notebook_id", "") or getattr(getattr(req, "survey", None), "notebook_id", "")
        if not isinstance(space_id, str):
            space_id = ""
        snapshot = None
        assessment_id = bound.get("assessment_id")
        resource_id = getattr(req, "quiz_resource_id", "")
        with session() as db:
            if assessment_id:
                row = db.get(AssessmentSession, assessment_id)
                if not row or row.user_id != user_id:
                    raise HTTPException(404, "测评不存在")
                space_id = row.data.get("notebook_id", "")
                snapshot = row.data.get("course_snapshot")
            review_ids = [getattr(item, "review_item_id", "") for item in getattr(req, "items", [])]
            if bound.get("item_id"):
                review_ids.append(bound["item_id"])
            resources = [resource_id] if resource_id else []
            for rid in review_ids:
                review = db.get(ReviewItem, rid)
                if not review or review.user_id != user_id:
                    raise HTTPException(404, "复习题不存在")
                resources.append(review.quiz_resource_id)
            spaces = set()
            for rid in resources:
                resource = db.get(Resource, rid)
                if not resource or resource.user_id != user_id:
                    raise HTTPException(404, "学习资源不存在")
                payload = resource.payload or {}
                revision = payload.get("course_revision")
                if revision and payload.get("notebook_id"):
                    course = db.get(LearningSpace, payload["notebook_id"])
                    if not course or course.course.get("revision") != revision:
                        raise HTTPException(409, "这份练习属于之前的课程范围，请在当前计划中重新生成练习")
                spaces.add("" if payload.get("demo_final_review") else str(payload.get("notebook_id") or ""))
            if len(spaces) > 1:
                raise HTTPException(400, "请在同一课程中提交复习，其他课程的记录分别保存")
            if spaces:
                space_id = spaces.pop()
        return user_id, str(space_id or ""), snapshot

    if inspect.iscoroutinefunction(fn):
        @wraps(fn)
        async def async_wrapped(*args, **kwargs):
            user, space, snapshot = resolve(args, kwargs)
            with course_scope(user, space, snapshot=snapshot):
                return await fn(*args, **kwargs)
        async_wrapped.__signature__ = signature
        return async_wrapped

    @wraps(fn)
    def wrapped(*args, **kwargs):
        user, space, snapshot = resolve(args, kwargs)
        with course_scope(user, space, snapshot=snapshot):
            return fn(*args, **kwargs)
    wrapped.__signature__ = signature
    return wrapped
