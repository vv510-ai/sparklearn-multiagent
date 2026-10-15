"""Durable jobs: owner-scoped content, shared metadata-only scheduling index."""
from __future__ import annotations
import asyncio
import contextvars
import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from fastapi import HTTPException
from sqlalchemy import text
from ..models.db import session
from ..models.entities import GenerationJob, GenerationTicket, GenerationEvent, GenerationEffect, ConversationMessage
from ..tenant import current_user_context

TERMINAL = {"completed", "failed", "needs_review", "cancelled"}
_context = contextvars.ContextVar("generation_job", default=None)
_stage = contextvars.ContextVar("generation_stage", default="")

class SubmissionUncertain(BaseException):
    """Escape ordinary fallbacks: never silently resubmit an ambiguous paid call."""

class ProviderPending(BaseException):
    pass

class LeaseLost(BaseException):
    pass

def enabled():
    return os.getenv("GENERATION_JOBS_ENABLED", "false").lower() == "true"

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=lambda x: {"bytes_sha256": hashlib.sha256(x).hexdigest()} if isinstance(x, bytes) else str(x)).encode()).hexdigest()

@contextmanager
def transaction():
    with session() as db:
        # Short DB-wide scheduling/checkpoint lock, released before any network call.
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(74192026)"))
        else:
            db.execute(text("BEGIN IMMEDIATE"))
        yield db
        db.commit()

def public(job):
    return {"id": job.id, "status": job.status, "detail": job.detail,
            "notebook_id": job.notebook_id, "kind": job.kind,
            "created_at": job.created_at.isoformat() if job.created_at else None}

def lookup(user, key, fingerprint):
    if not key:
        return None
    with session() as db:
        row = db.query(GenerationJob).filter_by(user_id=user, request_key=key).first()
        if row and row.fingerprint != fingerprint:
            raise HTTPException(409, "请求编号已用于其他内容，请重新发起。")
        return public(row) if row else None

def submit(state, kind, key, fingerprint):
    import copy
    from .learning_scope import current_space
    scope = current_space()
    state = {**state, "course_snapshot": copy.deepcopy(scope["course"]) if scope else None}
    user, key = state["user_id"], key or uuid.uuid4().hex
    with transaction() as db:
        old = db.query(GenerationJob).filter_by(user_id=user, request_key=key).first()
        if old:
            if old.fingerprint != fingerprint:
                raise HTTPException(409, "请求编号已用于其他内容。")
            return public(old)
        active = db.query(GenerationTicket).filter(GenerationTicket.status.in_(["queued", "running"])).all()
        if len(active) >= int(os.getenv("GENERATION_MAX_PENDING", "100")):
            raise HTTPException(429, "当前等待的任务较多，请稍后再试。")
        if sum(t.user_id == user for t in active) >= int(os.getenv("GENERATION_USER_PENDING", "3")):
            raise HTTPException(429, "你已有任务正在处理，请等完成后再提交。")
        job = GenerationJob(id="job_" + uuid.uuid4().hex, user_id=user, request_key=key,
            fingerprint=fingerprint, kind=kind, notebook_id=state.get("notebook_id", ""),
            state=state, checkpoints={}, status="queued")
        db.add(job)
        db.flush()
        db.add(GenerationTicket(id=job.id, user_id=user, created=time.time(), status="queued"))
        if kind == "chat" and state.get("visible_message"):
            db.add(ConversationMessage(user_id=user, session_id=state["session_id"], role="user",
                content=state["visible_message"][:20000], source_evidence=[],
                course_release_id=state.get("course_release_id", "")))
        db.flush()
        return public(job)

def owned(user, job_id):
    with session() as db:
        row = db.get(GenerationJob, job_id)
        if not row or row.user_id != user:
            raise HTTPException(404, "任务不存在")
        return public(row)

def list_jobs(user, notebook):
    with session() as db:
        rows = db.query(GenerationJob).filter_by(user_id=user, notebook_id=notebook).order_by(
            GenerationJob.created_at.desc()).limit(20).all()
        return [public(row) for row in rows]

async def events(user, job_id, after=0):
    view = owned(user, job_id)
    yield {"type": "job", "job_id": job_id, "status": view["status"], "text": view["detail"]}
    idle = 0
    while True:
        with session() as db:
            row = db.get(GenerationJob, job_id)
            if not row or row.user_id != user:
                return
            from .course_library import is_withdrawn, WITHDRAWN
            release = row.state.get("course_release_id", "")
            if release and is_withdrawn(release):
                yield {"type": "error", "detail": WITHDRAWN, "job_id": job_id}
                yield {"type": "done", "job_id": job_id}
                return
            status, detail = row.status, row.detail
            batch = db.query(GenerationEvent).filter(GenerationEvent.job_id == job_id,
                GenerationEvent.user_id == user, GenerationEvent.id > after).order_by(GenerationEvent.id).limit(200).all()
            batch = [(r.id, r.data) for r in batch]
        for cursor, event in batch:
            after = cursor
            yield {**event, "job_id": job_id, "event_id": cursor}
        if status in TERMINAL and len(batch) < 200:
            if status != "completed":
                yield {"type": "error", "detail": detail, "job_id": job_id}
            yield {"type": "done", "job_id": job_id}
            return
        idle += 1
        if idle % 12 == 0:
            yield {"type": "job", "job_id": job_id, "status": status, "text": detail}
        await asyncio.sleep(0.25)

def claim(owner):
    with transaction() as db:
        now = time.time()
        active = db.query(GenerationTicket).filter(GenerationTicket.status.in_(["queued", "running"])).order_by(GenerationTicket.created).all()
        for ticket in active:
            if ticket.status == "running" and ticket.lease_until < now:
                ticket.status, ticket.owner, ticket.lease_until = "queued", "", 0
        running = [t for t in active if t.status == "running"]
        if len(running) >= int(os.getenv("GENERATION_MAX_RUNNING", "4")):
            return None
        occupied = {t.user_id for t in running}
        for ticket in active:
            if ticket.status == "queued" and ticket.lease_until <= now and ticket.user_id not in occupied:
                ticket.status, ticket.owner, ticket.lease_until = "running", uuid.uuid4().hex, now + 30
                return ticket.id, ticket.user_id, ticket.owner
    return None

def _leased(db):
    job_id, user, owner = _context.get()
    ticket = db.get(GenerationTicket, job_id)
    if not ticket or ticket.owner != owner or ticket.status != "running" or ticket.lease_until < time.time():
        raise LeaseLost()
    job = db.get(GenerationJob, job_id)
    if not job or job.user_id != user:
        raise LeaseLost()
    return job

def effect_start(key):
    ctx = _context.get()
    if not ctx:
        return None, None
    identifier = digest([ctx[0], _stage.get(), key])
    with transaction() as db:
        _leased(db)
        old = db.get(GenerationEffect, identifier)
        if old:
            return identifier, {"status": old.status, **old.data}
        db.add(GenerationEffect(id=identifier, job_id=ctx[0], user_id=ctx[1], status="started", data={}))
    return identifier, None

def effect_save(identifier, status, data):
    if not identifier:
        return
    with transaction() as db:
        _leased(db)
        row = db.get(GenerationEffect, identifier)
        row.status, row.data = status, data

def durable_stream(fn):
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        key, prior = effect_start(digest(["llm_stream", args, kwargs]))
        if prior:
            if prior["status"] != "done":
                raise SubmissionUncertain("上次回答在保存完成前中断，已暂停，避免重复请求模型。")
            for part in prior["result"]:
                yield part
            return
        parts = []
        async for part in fn(*args, **kwargs):
            parts.append(part)
            yield part
        effect_save(key, "done", {"result": parts})
    return wrapped


def durable_call(kind):
    def decorate(fn):
        @wraps(fn)
        async def wrapped(*args, **kwargs):
            key, prior = effect_start(digest([kind, args, {k: v for k, v in kwargs.items() if k != "trace_id"}]))
            if prior:
                if prior["status"] == "done":
                    return prior["result"]
                raise SubmissionUncertain("上次模型请求结果不确定，已暂停，避免重复提交。")
            result = await fn(*args, **kwargs)
            effect_save(key, "done", {"result": result})
            return result
        return wrapped
    return decorate

async def checkpoint(name, fn, state):
    if not _context.get():
        return await fn(state)
    import copy
    from ..agents.emitter import _EMITTER
    token = _stage.set(name)
    captured = []
    downstream = _EMITTER.get()
    async def capture(event):
        captured.append(copy.deepcopy(event))
        if downstream:
            await downstream(event)
    emitter_token = _EMITTER.set(capture)
    try:
        with session() as db:
            job = _leased(db)
            if name in job.checkpoints:
                return job.checkpoints[name]["result"]
        result = await fn(state)
        with transaction() as db:
            job = _leased(db)
            # Outbox: result and its events are committed together. Recovery can
            # reconstruct delivery even if the event consumer had not flushed.
            job.checkpoints = {**job.checkpoints, name: {"result": result, "events": captured}}
        return result
    finally:
        _EMITTER.reset(emitter_token)
        _stage.reset(token)

async def execute(job_id, user, owner, runner=None):
    tenant = current_user_context.set(user)
    token = _context.set((job_id, user, owner))
    async def heartbeat():
        while True:
            await asyncio.sleep(5)
            with transaction() as db:
                _leased(db)
                db.get(GenerationTicket, job_id).lease_until = time.time() + 30
    pulse = asyncio.create_task(heartbeat())
    buffer = []
    def flush():
        if not buffer:
            return
        with transaction() as db:
            _leased(db)
            db.add_all([GenerationEvent(job_id=job_id, user_id=user, data=e) for e in buffer])
        buffer.clear()
    status, detail, finish = "completed", "已完成，可以查看结果。", True
    try:
        with transaction() as db:
            job = _leased(db)
            recovering = job.status == "running"
            from .personal_image import pending_message
            waiting_for_image = pending_message(db, job_id) if recovering else ""
            recovered_errors = any(e.get("type") == "error" for value in job.checkpoints.values() if isinstance(value, dict) for e in value.get("events", []))
            if recovering and not waiting_for_image:
                # Drop partial-stage deliveries and rebuild from atomic outboxes.
                # A reset event tells connected viewers to replace partial output.
                db.query(GenerationEvent).filter_by(job_id=job_id, user_id=user).delete(synchronize_session=False)
                replay = [{"type": "job", "reset": True, "status": "running", "text": "任务已恢复，正在接着处理。"}]
                for value in job.checkpoints.values():
                    if isinstance(value, dict):
                        replay.extend(value.get("events", []))
                db.add_all([GenerationEvent(job_id=job_id, user_id=user, data=e) for e in replay])
            job.status = "running"
            if not waiting_for_image:
                job.detail = "正在处理，离开页面后任务会继续。"
            state, kind = dict(job.state), job.kind
            age = time.time() - db.get(GenerationTicket, job_id).created
        if age > int(os.getenv("GENERATION_MAX_AGE_SECONDS", "1800")):
            raise SubmissionUncertain("等待时间过长，已暂停并保留记录，请先核对已有结果。")
        if waiting_for_image:
            # Keep existing events stable while the browser is drawing. Resume
            # checkpoints once the image is available or the handoff has failed.
            raise ProviderPending(waiting_for_image)
        if runner is None and os.getenv("GENERATION_WORKER_MODE") == "external":
            from ..rag.ingest import ingest_corpus
            await asyncio.to_thread(ingest_corpus)
        from .course_library import is_withdrawn, WITHDRAWN
        if state.get("course_release_id") and is_withdrawn(state["course_release_id"]):
            raise SubmissionUncertain(WITHDRAWN)
        from ..agents.graph import run_with_events
        iterator = (runner or run_with_events)({**state, "job_id": job_id})
        last = time.monotonic()
        has_errors = recovered_errors
        async with asyncio.timeout(900):
            async for event in iterator:
                if event.get("type") == "done":
                    continue
                has_errors = has_errors or event.get("type") == "error"
                buffer.append(event)
                if len(buffer) >= 24 or time.monotonic() - last >= 0.15 or event.get("type") not in {"token", "agent_token"}:
                    flush()
                    last = time.monotonic()
        flush()
        if has_errors:
            status, detail = "failed", "部分步骤未完成，请查看已有结果和错误提示。"
        with transaction() as db:
            job = _leased(db)
            if kind == "chat" and not job.checkpoints.get("_chat_saved"):
                items = db.query(GenerationEvent).filter_by(job_id=job_id, user_id=user).order_by(GenerationEvent.id).all()
                tokens = [e.data.get("delta", "") for e in items if e.data.get("type") == "token"]
                summaries = [e.data.get("text", "") for e in items if e.data.get("type") == "summary"]
                evidence = [e.data.get("evidence", []) for e in items if e.data.get("type") == "citations" and e.data.get("agent") == "tutor"]
                answer = "".join(tokens).strip() or (summaries[-1] if summaries else "学习任务已完成，请查看学习资源。")
                db.add(ConversationMessage(user_id=user, session_id=state["session_id"], role="assistant",
                    content=answer[:20000], source_evidence=evidence[-1] if evidence else [],
                    course_release_id=state.get("course_release_id", "")))
                job.checkpoints = {**job.checkpoints, "_chat_saved": True}
    except ProviderPending as exc:
        finish = False
        flush()
        with transaction() as db:
            job = _leased(db)
            # Keep running as the recovery marker; only scheduling is requeued.
            job.detail = str(exc)[:300] or "图片仍在生成，稍后会继续查询，无需重新提交。"
            ticket = db.get(GenerationTicket, job_id)
            ticket.status, ticket.owner, ticket.lease_until = "queued", "", time.time() + 5
    except SubmissionUncertain as exc:
        status, detail = "needs_review", str(exc)
    except (LeaseLost, asyncio.CancelledError):
        finish = False
    except Exception:
        status, detail = "failed", "任务未能完成，已保留过程记录和已有结果，请稍后查看。"
    except BaseException:
        finish = False
        raise
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)
        try:
            if finish:
                flush()
                with transaction() as db:
                    job = _leased(db)
                    job.status, job.detail = status, detail
                    db.get(GenerationTicket, job_id).status = status
        except LeaseLost:
            pass
        _context.reset(token)
        current_user_context.reset(tenant)

async def worker_loop():
    owner, tasks = uuid.uuid4().hex, set()
    import tempfile
    from pathlib import Path
    health = Path(tempfile.gettempdir()) / "learnloop-worker-heartbeat"
    try:
        while True:
            health.write_text(str(time.time()), encoding="ascii")
            item = claim(owner)
            if item:
                task = asyncio.create_task(execute(*item))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
            await asyncio.sleep(0.25)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def cancel_in_session(db, user, conversation):
    rows = db.query(GenerationJob).filter(GenerationJob.user_id == user,
        GenerationJob.status.in_(["queued", "running"])).all()
    for row in rows:
        if row.state.get("session_id") == conversation:
            row.status, row.detail = "cancelled", "已停止处理旧对话。"
            ticket = db.get(GenerationTicket, row.id)
            if ticket:
                ticket.status, ticket.owner = "cancelled", ""
