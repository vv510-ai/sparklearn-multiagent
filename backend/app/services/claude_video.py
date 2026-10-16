"""Claude teaching videos: the backend half of the local Claude Code handoff.

The owner's own Mac runs the official ``claude`` CLI, signed in with their Claude
subscription (or a Console API key they saved here). LearnLoop never sees
subscription credentials: a paired worker claims a job, runs Claude Code in a
private workspace and uploads the finished MP4. A video takes minutes, so the
generation job does not wait: the resource carries ``video.task_id`` and the page
polls ``/api/resources/video/task/{task_id}``.

Two stages: Claude first writes a storyboard (the worker then records the
narration and times every scene), and only then builds and renders the video.
The owner may ask to approve each storyboard before production starts.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time

from fastapi import HTTPException

from ..config import GEN_DIR, is_demo
from ..models.db import init_db, session
from ..models.entities import AuthAccount, ClaudeVideoConfig, ClaudeVideoJob, Resource, UserAsset
from ..prompt_templates import render_plain_prompt
from ..tenant import current_user_id
from .generation_jobs import transaction

PREFIX = "claude_"
TASK_ID = re.compile(r"claude_[a-f0-9]{40}")
MAX_VIDEO_BYTES = 400 * 1024 * 1024
MAX_POSTER_BYTES = 8 * 1024 * 1024
LEASE_SECONDS = 240
QUEUE_TTL = 6 * 3600          # never picked up: the local worker is not running
PING_TTL = 180
MAX_AGE = 12 * 3600
MAX_ATTEMPTS = 2
WORKER_ONLINE_SECONDS = 90

MODELS = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "note": "推荐：画面设计、动效与自查最稳"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "note": "更快，订阅额度消耗更少"},
    {"id": "claude-fable-5-1", "label": "Claude Fable 5.1", "note": "需要账号已开通 Fable"},
]
EFFORTS = [
    {"id": "low", "label": "低", "note": "最快，适合试做"},
    {"id": "medium", "label": "中", "note": "速度与质量均衡"},
    {"id": "high", "label": "高", "note": "推荐：分镜和自查更细致"},
    {"id": "xhigh", "label": "很高", "note": "更慢，更耗额度"},
    {"id": "max", "label": "最高", "note": "最慢、最耗额度"},
]
ENGINES = [{"id": "hyperframes", "label": "HyperFrames", "note": "HTML + GSAP 动效，本机渲染 1080P"}]
VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "label": "晓晓", "note": "温暖女声"},
    {"id": "zh-CN-YunxiNeural", "label": "云希", "note": "清朗男声"},
    {"id": "zh-CN-XiaoyiNeural", "label": "晓伊", "note": "活泼女声"},
    {"id": "zh-CN-YunjianNeural", "label": "云健", "note": "沉稳男声"},
    {"id": "zh-CN-YunyangNeural", "label": "云扬", "note": "播音男声"},
]
QUALITIES = [{"id": "looks", "label": "标准", "note": "渲染更快"}, {"id": "delivery", "label": "高", "note": "画质更高，渲染更慢"}]
DURATIONS = [60, 90, 120, 180]
DEFAULTS = {"model": "claude-opus-5-5", "effort": "high", "engine": "hyperframes", "max_seconds": 120,
            "voice": "zh-CN-XiaoxiaoNeural", "quality": "looks", "approve_storyboard": False,
            "access": "subscription", "budget_usd": 8.0}
SETTING_KEYS = tuple(DEFAULTS)
_CHOICES = {"model": MODELS, "effort": EFFORTS, "engine": ENGINES, "voice": VOICES, "quality": QUALITIES}

PHASES = {
    "queued": ("排队中", 2),
    "prepare": ("正在准备制作环境", 4),
    "storyboard": ("Claude 正在设计分镜", 10),
    "voice": ("正在录制中文配音并对齐字幕", 24),
    "awaiting_approval": ("分镜已完成，等你确认后开始制作", 26),
    "compose": ("Claude 正在制作画面与动效", 40),
    "review": ("Claude 正在逐镜截图自查", 68),
    "render": ("正在渲染 1080P 成片", 82),
    "check": ("正在校验成片", 92),
    "upload": ("正在保存视频", 96),
}
FAILURES = {
    "not_started": "本机的 Claude 视频接入程序一直没有运行，任务已暂停。启动接入程序后点“重新制作”。",
    "login_required": "本机 Claude Code 未登录或登录已失效。请在启动菜单选择“登录 Claude”，然后点“重新制作”。",
    "usage_limit": "Claude 订阅额度暂时用完了，请等额度恢复后点“重新制作”。",
    "model_unavailable": "当前账号用不了所选的 Claude 模型，请在设置里换一个模型后点“重新制作”。",
    "budget": "已达到设置的单条视频费用上限，制作已停止。",
    "timeout": "制作时间超过上限，已停止。可以缩短时长或降低思考强度后重新制作。",
    "storyboard_invalid": "Claude 没有写出可用的分镜方案，已停止。可以点“重新制作”再试一次。",
    "tts_failed": "中文配音生成失败（网络或语音服务暂不可用），已停止。",
    "render_failed": "视频渲染没有成功，已停止。可以点“重新制作”再试一次。",
    "invalid_output": "生成的视频没有通过校验（分辨率、时长或音轨不符合要求），已停止。",
    "tools_missing": "本机缺少视频制作工具，请在启动菜单重新运行“首次安装”。",
    "worker_lost": "本机接入程序在制作中途退出，已停止。可以点“重新制作”。",
    "worker_error": "本机接入程序没有完成任务，已停止。可以点“重新制作”。",
    "cancelled": "已取消制作。",
}


def _text(value, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def owner_id() -> str:
    from .owner import resolve_owner
    return resolve_owner("CLAUDE_VIDEO_OWNER_ID")


def feature_enabled() -> bool:
    # is_demo() loads settings first, which also loads backend/.env into the environment.
    return not is_demo() and os.getenv("CLAUDE_VIDEO_ENABLED", "false").lower() == "true"


def enabled_for_user(user: str | None = None) -> bool:
    if not feature_enabled():  # also loads settings, so the owner lookup sees backend/.env
        return False
    owner = owner_id()
    return bool(owner) and (user or current_user_id()) == owner


def is_task(task_id: str) -> bool:
    return bool(TASK_ID.fullmatch(str(task_id or "")))


# ----------------------------------------------------------------------------- settings
def _clean_config(data: dict) -> dict:
    out = dict(DEFAULTS)
    for key in SETTING_KEYS:
        if key not in (data or {}):
            continue
        value = data[key]
        if key in _CHOICES:
            if value in {item["id"] for item in _CHOICES[key]}:
                out[key] = value
        elif key == "max_seconds":
            out[key] = int(value) if value in DURATIONS else out[key]
        elif key == "approve_storyboard":
            out[key] = bool(value)
        elif key == "access":
            out[key] = value if value in {"subscription", "api_key"} else out[key]
        elif key == "budget_usd":
            try:
                out[key] = round(min(50.0, max(1.0, float(value))), 2)
            except (TypeError, ValueError):
                pass
    return out


def _config_row(db, user: str) -> ClaudeVideoConfig | None:
    return db.get(ClaudeVideoConfig, user)


def config(user: str) -> dict:
    init_db()
    with session() as db:
        row = _config_row(db, user)
        cfg = _clean_config(row.data if row else {})
        has_key = bool(row and row.credential)
    if cfg["access"] == "api_key" and not has_key:
        cfg["access"] = "subscription"
    return cfg


def _worker_view(worker: dict) -> dict:
    worker = dict(worker or {})
    seen = float(worker.get("last_seen") or 0)
    auth = worker.get("auth") if isinstance(worker.get("auth"), dict) else {}
    return {"online": bool(seen and time.time() - seen < WORKER_ONLINE_SECONDS), "last_seen": seen or None,
            "cli_version": _text(worker.get("cli_version"), 40), "busy": bool(worker.get("busy")),
            "auth": {"logged_in": bool(auth.get("logged_in")), "method": _text(auth.get("method"), 24),
                     "plan": _text(auth.get("plan"), 24)},
            "tools": {key: _text(value, 40) for key, value in (worker.get("tools") or {}).items()
                      if key in {"hyperframes", "ffmpeg", "ffprobe", "chrome", "tts", "node"}}}


def view(user: str) -> dict:
    available = enabled_for_user(user)
    init_db()
    with session() as db:
        row = _config_row(db, user)
        cfg = _clean_config(row.data if row else {})
        has_key, revision = bool(row and row.credential), row.revision if row else 0
        worker = _worker_view(row.worker if row else {})
        ping = (db.query(ClaudeVideoJob).filter_by(user_id=user, kind="ping")
                .order_by(ClaudeVideoJob.created.desc()).first())
        test = None
        if ping:
            _expire(ping, time.time())
            test = {"status": ping.status, "reply": _text((ping.data or {}).get("reply"), 80),
                    "detail": _text((ping.data or {}).get("detail"), 160), "model": (ping.settings or {}).get("model", ""),
                    "at": ping.updated or ping.created}
        active = db.query(ClaudeVideoJob).filter(ClaudeVideoJob.user_id == user, ClaudeVideoJob.kind == "video",
                                                 ClaudeVideoJob.status.in_(["queued", "claimed", "awaiting_approval"])).count()
    reason = ""
    if not feature_enabled():
        reason = "这台服务器没有开启 Claude 讲解视频（需要在本机用启动菜单运行）。"
    elif not available:
        reason = "Claude 讲解视频只对本机拥有者账号开放。"
    return {"available": available, "reason": reason,
            "config": {**cfg, "has_api_key": has_key, "revision": revision},
            "options": {"models": MODELS, "efforts": EFFORTS, "engines": ENGINES, "voices": VOICES,
                        "qualities": QUALITIES, "durations": DURATIONS},
            "worker": worker, "test": test, "active_jobs": active,
            "note": "视频由你本机已登录的官方 Claude Code 制作；LearnLoop 不读取、不保存你的 Claude 订阅登录信息。"
                    "API Key 模式按 Anthropic 控制台用量计费，密钥加密保存，只在制作时交给本机接入程序。"}


def save(user: str, updates: dict, api_key: str | None, revision: int) -> dict:
    if not enabled_for_user(user):
        raise HTTPException(403, "Claude 讲解视频只对本机拥有者账号开放")
    unknown = set(updates or {}) - set(SETTING_KEYS)
    if unknown:
        raise HTTPException(422, "不支持的设置项")
    if api_key is not None and api_key.strip() and (not api_key.strip().startswith("sk-ant-")
                                                  or len(api_key.strip()) > 300 or re.search(r"\s", api_key.strip())):
        raise HTTPException(422, "API Key 格式不正确，请粘贴 Anthropic 控制台生成的完整密钥（sk-ant- 开头）")
    from .model_preferences import _seal
    with transaction() as db:
        row = _config_row(db, user)
        current = row.revision if row else 0
        if revision != current:
            raise HTTPException(409, "设置已在其他页面更新，请刷新后再保存")
        if not row:
            row = ClaudeVideoConfig(user_id=user, data={}, credential="", worker={}, revision=0)
            db.add(row)
        merged = _clean_config({**(row.data or {}), **(updates or {})})
        if api_key is not None:
            row.credential = _seal(user, "anthropic", api_key.strip()) if api_key.strip() else ""
        if merged["access"] == "api_key" and not row.credential:
            raise HTTPException(422, "请先填写 Anthropic API Key，或改用订阅登录")
        row.data, row.revision = merged, current + 1
    return view(user)


def hello(user: str, info: dict) -> None:
    """Record what the local worker reported about itself (never credentials)."""
    info = info if isinstance(info, dict) else {}
    auth = info.get("auth") if isinstance(info.get("auth"), dict) else {}
    worker = {"last_seen": time.time(), "cli_version": _text(info.get("cli_version"), 40), "busy": bool(info.get("busy")),
              "auth": {"logged_in": bool(auth.get("logged_in")), "method": _text(auth.get("method"), 24),
                       "plan": _text(auth.get("plan"), 24)},
              "tools": {key: _text(value, 40) for key, value in (info.get("tools") or {}).items()
                        if key in {"hyperframes", "ffmpeg", "ffprobe", "chrome", "tts", "node"}}}
    with transaction() as db:
        row = _config_row(db, user)
        if not row:
            row = ClaudeVideoConfig(user_id=user, data={}, credential="", worker={}, revision=0)
            db.add(row)
        row.worker = worker


# ----------------------------------------------------------------------------- jobs
def _now() -> float:
    return time.time()


def _settings_snapshot(cfg: dict) -> dict:
    return {key: cfg[key] for key in SETTING_KEYS}


def public_state(row: ClaudeVideoJob) -> dict:
    data, settings = dict(row.data or {}), dict(row.settings or {})
    status = {"claimed": "running"}.get(row.status, row.status)
    phase = "awaiting_approval" if row.status == "awaiting_approval" else data.get("phase") or "queued"
    label, percent = PHASES.get(phase, PHASES["queued"])
    message = _text(data.get("message"), 160) or label
    if row.status == "queued" and data.get("stage") == "production":
        message = "分镜已确认，等待本机接入程序开始制作"
    state = {"status": status, "task_id": row.id, "provider": "claude_code", "phase": phase,
             "message": message, "progress": percent, "model": settings.get("model", ""),
             "effort": settings.get("effort", ""), "engine": settings.get("engine", "hyperframes"),
             "approve_storyboard": bool(settings.get("approve_storyboard")),
             "storyboard": data.get("storyboard") or None, "error": "", "retryable": False,
             "url": "", "poster_url": "", "created": row.created, "updated": row.updated or row.created}
    if row.status == "succeeded":
        result = dict(data.get("result") or {})
        state.update({"progress": 100, "message": "讲解视频已完成", "url": result.get("url", ""),
                      "poster_url": result.get("poster_url", ""), "duration": result.get("duration"),
                      "width": result.get("width"), "height": result.get("height"),
                      "chapters": result.get("chapters") or [], "notes": _text(result.get("notes"), 200),
                      "title": _text(result.get("title"), 40)})
    elif row.status in {"failed", "cancelled"}:
        code = row.detail_code or ("cancelled" if row.status == "cancelled" else "worker_error")
        detail = _text(data.get("detail"), 200)
        state.update({"error": FAILURES.get(code, FAILURES["worker_error"]) + (f"（{detail}）" if detail else ""),
                      "code": code, "retryable": True})
    return state


def _expire(row: ClaudeVideoJob, now: float) -> None:
    data = dict(row.data or {})
    queued_at = float(data.get("queued_at") or row.created)
    if row.status in {"succeeded", "failed", "cancelled"}:
        return
    if row.kind == "ping":
        if now - row.created > PING_TTL:
            row.status, row.detail_code, row.updated = "failed", "not_started", now
        return
    if row.status == "queued" and now - queued_at > QUEUE_TTL:
        row.status, row.detail_code, row.updated = "failed", "not_started", now
    elif row.status == "claimed" and row.lease_until < now:
        if int(data.get("attempts") or 0) >= MAX_ATTEMPTS:
            row.status, row.detail_code = "failed", "worker_lost"
        else:
            row.status, row.lease = "queued", ""
            data["phase"] = "queued"
            row.data = data
        row.updated = now
    elif row.status != "awaiting_approval" and now - queued_at > MAX_AGE:
        row.status, row.detail_code, row.updated = "failed", "timeout", now


def _job_id(user: str, job_key: str, topic: str) -> str:
    return PREFIX + hashlib.sha256(f"{user}\0{job_key}\0{topic}".encode()).hexdigest()[:40]


def request(*, topic: str, goal: str, persona: str, content: str, material: str,
            resource_id: str, job_key: str) -> dict:
    """Queue (or reuse) the Claude video for one generated resource; returns ``payload.video``."""
    user = current_user_id()
    if not enabled_for_user(user):
        return {}
    cfg = config(user)
    identifier = _job_id(user, job_key, topic)
    brief = {"topic": _text(topic, 80), "goal": str(goal or "")[:600], "persona": _text(persona, 120),
             "content": str(content or "")[:6000], "material": str(material or "")[:9000]}
    now = _now()
    with transaction() as db:
        row = db.get(ClaudeVideoJob, identifier)
        if row is None:
            row = ClaudeVideoJob(id=identifier, user_id=user, resource_id=resource_id, kind="video", status="queued",
                                 created=now, updated=now, brief=brief, settings=_settings_snapshot(cfg),
                                 data={"stage": "storyboard", "phase": "queued", "queued_at": now, "attempts": 0})
            db.add(row)
            db.flush()
        elif row.user_id != user:
            raise HTTPException(404, "视频任务不存在")
        elif resource_id and row.status != "succeeded":
            # The media stage re-ran after a crash; follow the resource it now emits.
            row.resource_id = resource_id
        _expire(row, now)
        return public_state(row)


def poll(user: str, task_id: str) -> dict:
    with transaction() as db:
        row = db.get(ClaudeVideoJob, task_id)
        if not row or row.user_id != user or row.kind != "video":
            raise HTTPException(404, "视频任务不存在")
        _expire(row, _now())
        state = public_state(row)
        cfg_row = _config_row(db, user)
        worker = _worker_view(cfg_row.worker if cfg_row else {})
    state["worker_online"] = worker["online"]
    if state["status"] == "queued" and not worker["online"]:
        state["message"] = "等待本机 Claude 视频接入程序：请在启动菜单选择“启动讲解视频接入”。"
    return state


def _user_row(db, user: str, task_id: str) -> ClaudeVideoJob:
    row = db.get(ClaudeVideoJob, task_id)
    if not row or row.user_id != user or row.kind != "video":
        raise HTTPException(404, "视频任务不存在")
    _expire(row, _now())
    return row


def approve(user: str, task_id: str, notes: str = "") -> dict:
    with transaction() as db:
        row = _user_row(db, user, task_id)
        if row.status != "awaiting_approval":
            raise HTTPException(409, "这条视频现在不需要确认分镜")
        row.status, row.updated = "queued", _now()
        row.data = {**(row.data or {}), "stage": "production", "phase": "queued", "queued_at": _now(),
                    "approval_notes": _text(notes, 400), "attempts": 0}
        state = public_state(row)
    _sync_resource(row.id)
    return state


def cancel(user: str, task_id: str) -> dict:
    with transaction() as db:
        row = _user_row(db, user, task_id)
        if row.status in {"succeeded", "failed", "cancelled"}:
            return public_state(row)
        # Keep the lease: the worker's next heartbeat learns about the cancellation and stops Claude.
        row.status, row.detail_code, row.updated = "cancelled", "cancelled", _now()
        state = public_state(row)
    _sync_resource(row.id)
    return state


def retry(user: str, task_id: str) -> dict:
    if not enabled_for_user(user):
        raise HTTPException(403, "Claude 讲解视频只对本机拥有者账号开放")
    cfg = config(user)
    with transaction() as db:
        row = _user_row(db, user, task_id)
        if row.status not in {"failed", "cancelled"}:
            raise HTTPException(409, "只有失败或已取消的视频可以重新制作")
        now = _now()
        row.status, row.detail_code, row.lease, row.lease_until, row.updated = "queued", "", "", 0, now
        row.settings = _settings_snapshot(cfg)
        row.data = {"stage": "storyboard", "phase": "queued", "queued_at": now, "attempts": 0}
        state = public_state(row)
    _sync_resource(row.id)
    return state


def queue_test(user: str) -> dict:
    if not enabled_for_user(user):
        raise HTTPException(403, "Claude 讲解视频只对本机拥有者账号开放")
    cfg = config(user)
    now = _now()
    with transaction() as db:
        pending = db.query(ClaudeVideoJob).filter(ClaudeVideoJob.user_id == user, ClaudeVideoJob.kind == "ping",
                                                  ClaudeVideoJob.status.in_(["queued", "claimed"])).first()
        if not pending:
            db.add(ClaudeVideoJob(id=PREFIX + "ping_" + secrets.token_hex(16), user_id=user, kind="ping",
                                  status="queued", created=now, updated=now, brief={},
                                  settings=_settings_snapshot(cfg), data={"phase": "queued"}))
    return view(user)["test"] or {"status": "queued"}


# ----------------------------------------------------------------------------- worker
def authenticate_worker(header: str) -> str:
    scheme, _, token = str(header or "").partition(" ")
    expected = os.getenv("CLAUDE_VIDEO_WORKER_TOKEN_SHA256", "")
    if (not feature_enabled() or not owner_id() or not re.fullmatch(r"[a-f0-9]{64}", expected)
            or scheme.lower() != "bearer" or not 32 <= len(token) <= 256
            or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), expected)):
        raise HTTPException(401, "视频接入程序未授权")
    with session() as db:
        if not db.query(AuthAccount).filter_by(user_id=owner_id()).first():
            raise HTTPException(403, "拥有者账号还没有注册")
    return owner_id()


def _prompts(row: ClaudeVideoJob) -> dict:
    brief, settings, data = dict(row.brief or {}), dict(row.settings or {}), dict(row.data or {})
    seconds = int(settings.get("max_seconds") or DEFAULTS["max_seconds"])
    notes = _text(data.get("approval_notes"), 400)
    material = brief.get("material") or "（没有选择资料：只使用公认、可靠的通用知识，只讲你有把握的内容。）"
    storyboard = render_plain_prompt(
        "video.claude_storyboard", topic=brief.get("topic", ""), goal=brief.get("goal") or f"看懂{brief.get('topic', '')}",
        persona=brief.get("persona") or "零基础也能跟上的学习者", content=brief.get("content") or "（无，按学习目标设计）",
        material=material, min_seconds=max(45, seconds // 2), max_seconds=seconds, max_chars=int(seconds * 4.2)).prompt
    production = render_plain_prompt(
        "video.claude_production", topic=brief.get("topic", ""),
        approval_notes=f"确认时的补充意见（请落实到画面上）：{notes}" if notes else "",
        engine_rule=("制作引擎是 HyperFrames（HTML + CSS + GSAP）。动手前先阅读 `.claude/skills/` 里的 hyperframes-core、"
                     "hyperframes-animation、hyperframes-creative 技能，按它们的写法使用 data-* 属性、注册时间轴和拆分子合成。"
                     "不要进入任何需要用户确认的工作流，也不要使用需要登录或联网的功能（HeyGen 配音、素材库、云渲染等），"
                     "分镜和配音都已经准备好。"),
        quality=settings.get("quality") or "looks").prompt
    rules = render_plain_prompt("video.claude_rules").prompt
    style = render_plain_prompt("video.claude_style").prompt
    # The worker fills in the concrete check failures; the wording still lives in app/prompts.
    repair = render_plain_prompt("video.claude_repair", problems="{{problems}}").prompt
    return {"storyboard": storyboard, "production": production, "rules": rules, "style": style, "repair": repair}


def claim(user: str, info: dict) -> dict | None:
    hello(user, info)
    now = _now()
    with transaction() as db:
        rows = (db.query(ClaudeVideoJob).filter(ClaudeVideoJob.user_id == user,
                ClaudeVideoJob.status.in_(["queued", "claimed"])).order_by(ClaudeVideoJob.created).all())
        for row in rows:
            _expire(row, now)
        if any(row.status == "claimed" for row in rows):
            return None
        queued = [row for row in rows if row.status == "queued"]
        row = next((r for r in queued if r.kind == "ping"), None) or next(iter(queued), None)
        if not row:
            return None
        data = dict(row.data or {})
        data.update({"phase": "prepare", "attempts": int(data.get("attempts") or 0) + 1, "message": ""})
        row.status, row.lease, row.lease_until, row.updated = "claimed", secrets.token_hex(24), now + LEASE_SECONDS, now
        row.data = data
        job = {"id": row.id, "lease": row.lease, "kind": row.kind, "settings": dict(row.settings or {})}
        if row.kind == "video":
            job.update({"stage": data.get("stage", "storyboard"), "topic": (row.brief or {}).get("topic", ""),
                        "prompts": _prompts(row), "storyboard": data.get("storyboard") or None})
        settings = job["settings"]
        if settings.get("access") == "api_key":
            cfg_row = _config_row(db, user)
            try:
                from .model_preferences import _open
                job["api_key"] = _open(user, "anthropic", cfg_row.credential if cfg_row else "")
            except HTTPException:
                row.status, row.detail_code, row.lease = "failed", "login_required", ""
                row.data = {**data, "detail": "保存的 API Key 无法使用，请在设置里重新填写"}
                return None
        return job


def _owned(db, identifier: str, lease: str, *, allow=("claimed",)) -> ClaudeVideoJob:
    row = db.get(ClaudeVideoJob, identifier)
    if not row or row.user_id != owner_id() or row.user_id != current_user_id():
        raise HTTPException(404, "视频任务不存在")
    _expire(row, _now())
    if row.status not in allow or not lease or not hmac.compare_digest(row.lease or "", lease):
        raise HTTPException(409, "视频任务已停止或接入租约失效")
    return row


def heartbeat(identifier: str, lease: str, phase: str = "", message: str = "") -> dict:
    with transaction() as db:
        row = db.get(ClaudeVideoJob, identifier)
        if row and row.user_id == owner_id() and row.status == "cancelled" and hmac.compare_digest(row.lease or "", lease or "-"):
            return {"status": "cancelled", "cancelled": True}
        row = _owned(db, identifier, lease)
        data = dict(row.data or {})
        if phase in PHASES and phase not in {"queued", "awaiting_approval"}:
            data["phase"] = phase
        data["message"] = _text(message, 160)
        row.data, row.lease_until, row.updated = data, _now() + LEASE_SECONDS, _now()
    return {"status": "running", "cancelled": False}


def normalize_storyboard(value: dict) -> dict:
    value = value if isinstance(value, dict) else {}
    scenes = []
    for item in (value.get("scenes") or [])[:16]:
        if not isinstance(item, dict) or not _text(item.get("narration"), 600):
            continue
        scene = {"title": _text(item.get("title"), 24) or f"第 {len(scenes) + 1} 镜", "goal": _text(item.get("goal"), 80),
                 "narration": _text(item.get("narration"), 600), "visual": _text(item.get("visual"), 300),
                 "on_screen": [text for text in (_text(x, 40) for x in (item.get("on_screen") or [])[:6]) if text],
                 "transition": _text(item.get("transition"), 40)}
        try:
            start, end = round(float(item["start"]), 2), round(float(item["end"]), 2)
            if 0 <= start < end:
                scene.update({"start": start, "end": end})
        except (KeyError, TypeError, ValueError):
            pass
        scenes.append(scene)
    if len(scenes) < 2:
        raise HTTPException(422, "分镜至少需要两镜，且每镜都要有旁白")
    timed = all("start" in scene for scene in scenes)
    try:
        duration = round(float(value.get("duration") or (scenes[-1]["end"] if timed else 0)), 2)
    except (TypeError, ValueError):
        duration = 0.0
    return {"title": _text(value.get("title"), 40) or "讲解视频", "hook": _text(value.get("hook"), 120),
            "summary": _text(value.get("summary"), 120), "visual_style": _text(value.get("visual_style"), 300),
            "quiz": _text(value.get("quiz"), 160), "self_check": _text(value.get("self_check"), 300),
            "scenes": scenes, "duration": duration, "timed": timed}


def store_storyboard(identifier: str, lease: str, storyboard: dict) -> dict:
    clean = normalize_storyboard(storyboard)
    if not clean["timed"]:
        raise HTTPException(422, "分镜缺少配音时间轴")
    with transaction() as db:
        row = _owned(db, identifier, lease)
        if row.kind != "video":
            raise HTTPException(409, "测试任务没有分镜")
        data = {**(row.data or {}), "storyboard": clean, "message": ""}
        approve_first = bool((row.settings or {}).get("approve_storyboard")) and data.get("stage") == "storyboard"
        if approve_first:
            row.status, row.lease, row.lease_until = "awaiting_approval", "", 0
            data["phase"] = "awaiting_approval"
        else:
            data.update({"stage": "production", "phase": "compose"})
            row.lease_until = _now() + LEASE_SECONDS
        row.data, row.updated = data, _now()
    _sync_resource(identifier)
    return {"next": "wait" if approve_first else "production"}


def _write(name: str, content: bytes) -> str:
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    target, partial = GEN_DIR / name, GEN_DIR / f".{name}.{secrets.token_hex(4)}.part"
    try:
        partial.write_bytes(content)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return f"/static/gen/{name}"


def store_video(identifier: str, lease: str, content: bytes) -> dict:
    if not 1024 <= len(content) <= MAX_VIDEO_BYTES:
        raise HTTPException(413, "视频为空或超过 400 MB")
    if content[4:8] != b"ftyp":
        raise HTTPException(422, "只接受 MP4 视频")
    digest = hashlib.sha256(content).hexdigest()
    with transaction() as db:
        row = _owned(db, identifier, lease)
        url = _write(f"{identifier}.mp4", content)
        row.data = {**(row.data or {}), "video": {"url": url, "sha256": digest, "bytes": len(content)}, "phase": "upload"}
        row.lease_until, row.updated = _now() + LEASE_SECONDS, _now()
    return {"ok": True, "url": url, "sha256": digest}


def store_poster(identifier: str, lease: str, content: bytes, content_type: str) -> dict:
    if len(content) > MAX_POSTER_BYTES:
        raise HTTPException(413, "封面超过 8 MB")
    from .personal_image import _validated_image
    _, _, suffix = _validated_image(content, content_type)
    with transaction() as db:
        row = _owned(db, identifier, lease)
        url = _write(f"{identifier}{suffix}", content)
        row.data = {**(row.data or {}), "poster_url": url}
        row.lease_until, row.updated = _now() + LEASE_SECONDS, _now()
    return {"ok": True, "url": url}


def _chapters(value, storyboard: dict) -> list[dict]:
    chapters = []
    for item in value if isinstance(value, list) else []:
        try:
            chapters.append({"start": round(max(0.0, float(item["start"])), 2), "title": _text(item.get("title"), 24)})
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    if not chapters:
        chapters = [{"start": scene["start"], "title": scene["title"]} for scene in storyboard.get("scenes", []) if "start" in scene]
    return sorted((c for c in chapters if c["title"]), key=lambda c: c["start"])[:16]


def finish(identifier: str, lease: str, meta: dict) -> dict:
    meta = meta if isinstance(meta, dict) else {}
    with transaction() as db:
        row = _owned(db, identifier, lease)
        data = dict(row.data or {})
        video = data.get("video") or {}
        if row.kind != "video" or not video.get("url"):
            raise HTTPException(409, "成片还没有上传")
        storyboard = data.get("storyboard") or {}
        try:
            duration = round(float(meta.get("duration")), 2)
            width, height = int(meta.get("width")), int(meta.get("height"))
        except (TypeError, ValueError):
            raise HTTPException(422, "缺少视频时长或分辨率") from None
        result = {"url": video["url"], "poster_url": data.get("poster_url", ""), "duration": duration,
                  "width": width, "height": height, "chapters": _chapters(meta.get("chapters"), storyboard),
                  "title": _text(meta.get("title") or storyboard.get("title"), 40), "notes": _text(meta.get("notes"), 200),
                  "sha256": video.get("sha256", ""), "finished_at": _now()}
        row.status, row.lease, row.updated = "succeeded", "", _now()
        row.data = {**data, "result": result, "phase": "upload", "message": ""}
        for path in filter(None, (result["url"], result["poster_url"])):
            db.merge(UserAsset(id="asset_" + hashlib.sha256(f"{row.user_id}\0{path}".encode()).hexdigest()[:40],
                               user_id=row.user_id, path=path, resource_id=row.resource_id or "", kind="generated"))
        state = public_state(row)
    _sync_resource(identifier)
    return state


def fail(identifier: str, lease: str, code: str, detail: str = "") -> dict:
    with transaction() as db:
        row = db.get(ClaudeVideoJob, identifier)
        if row and row.status == "cancelled":
            return {"ok": True}
        row = _owned(db, identifier, lease)
        row.status, row.detail_code, row.lease, row.updated = "failed", code if code in FAILURES else "worker_error", "", _now()
        row.data = {**(row.data or {}), "detail": _text(detail, 200)}
    _sync_resource(identifier)
    return {"ok": True}


def finish_ping(identifier: str, lease: str, ok: bool, reply: str = "", code: str = "", detail: str = "") -> dict:
    with transaction() as db:
        row = _owned(db, identifier, lease)
        if row.kind != "ping":
            raise HTTPException(409, "不是连接测试任务")
        row.status = "succeeded" if ok else "failed"
        row.detail_code = "" if ok else (code if code in FAILURES else "worker_error")
        row.lease, row.updated = "", _now()
        row.data = {**(row.data or {}), "reply": _text(reply, 80),
                    "detail": _text(detail, 160) or ("" if ok else FAILURES.get(row.detail_code, ""))}
    return {"ok": True}


def _sync_resource(identifier: str) -> None:
    """Mirror the job state into the resource so a reload shows it without polling first."""
    from .ownership_service import sync_resource_ownership
    with session() as db:
        row = db.get(ClaudeVideoJob, identifier)
        if not row or not row.resource_id:
            return
        resource = db.get(Resource, row.resource_id)
        if not resource or resource.user_id != row.user_id:
            return
        payload = dict(resource.payload or {})
        payload["video"] = {**dict(payload.get("video") or {}), **public_state(row)}
        resource.payload = payload
        db.commit()
        user, rid = row.user_id, row.resource_id
    sync_resource_ownership(user, rid, payload)
