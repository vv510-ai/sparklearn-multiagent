"""Personal Chat UI handoff. No OpenAI credentials, private endpoints or API fallback."""
from __future__ import annotations
import hashlib
import hmac
import io
import os
import re
import secrets
import time
import warnings
from fastapi import HTTPException
from PIL import Image
from ..config import GEN_DIR
from ..models.db import session
from ..models.entities import AuthAccount, GenerationJob, PersonalImageJob, UserAsset
from ..tenant import current_user_id
from .generation_jobs import _context, _leased, transaction, ProviderPending

MAX_IMAGE_BYTES = 20 * 1024 * 1024
LEASE_SECONDS = 180
MAX_AGE_SECONDS = 1200
MAX_IMAGES = 6  # One answer may split a topic into several 一图看懂 pictures.
CONVERSATION_URL = re.compile(r"https://chatgpt\.com/c/[A-Za-z0-9-]{8,80}")
FAILURES = {
    "login_required": "ChatGPT 需要重新登录，请在本机 Chrome 完成登录后重新发起。",
    "interaction_required": "ChatGPT 出现验证码、授权或额度提示，接入已暂停，请在本机查看。",
    "ui_changed": "ChatGPT 页面结构发生变化，接入已暂停，文字版已保留。",
    "uncertain": "浏览器发送后的结果尚未确认，已暂停避免重复生成。请先查看 ChatGPT 中的结果。",
    "timeout": "等待本机 ChatGPT 超时，已暂停，文字版已保留。",
    "worker_error": "本机图片接入程序未完成任务，文字版已保留。",
    "cancelled": "原学习任务已停止，未继续请求图片。",
}
PHASE_MESSAGES = {
    "connect": "正在连接本机 ChatGPT。",
    "prepare_prompt": "正在把已核对的内容交给 ChatGPT。",
    "submit": "正在确认图片任务。",
    "wait_image": "ChatGPT 正在绘图；完成后会自动保存，可先继续学习，无需重新点击。",
    "continue_more": "ChatGPT 把内容拆成了多张图，正在继续生成后面的图。",
    "read_image": "图片已生成，正在取回原图。",
    "upload_image": "原图已取回，正在保存到资料归档。",
}


def owner_id() -> str:
    return os.getenv("PERSONAL_CHAT_IMAGE_OWNER_ID", "").strip()


def enabled_for_user() -> bool:
    return (os.getenv("PERSONAL_CHAT_IMAGE_ENABLED", "false").lower() == "true"
            and bool(owner_id()) and current_user_id() == owner_id())


def authenticate_worker(header: str) -> str:
    scheme, _, token = header.partition(" ")
    expected = os.getenv("PERSONAL_CHAT_IMAGE_WORKER_TOKEN_SHA256", "")
    if (os.getenv("PERSONAL_CHAT_IMAGE_ENABLED", "false").lower() != "true"
            or not owner_id() or not re.fullmatch(r"[a-f0-9]{64}", expected)
            or scheme.lower() != "bearer" or not 32 <= len(token) <= 256
            or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), expected)):
        raise HTTPException(401, "图片接入程序未授权")
    with session() as db:
        if not db.query(AuthAccount).filter_by(user_id=owner_id()).first():
            raise HTTPException(403, "个人图片账号未配置")
    return owner_id()


def _parent_active(db, row) -> bool:
    parent = db.get(GenerationJob, row.generation_job_id)
    return bool(parent and parent.user_id == row.user_id and parent.status in {"queued", "running"})


def _expire(db, row):
    now = time.time()
    if row.status in {"completed", "failed"}:
        return
    if not _parent_active(db, row):
        row.status, row.detail_code = "failed", "cancelled"
    elif now - row.created > MAX_AGE_SECONDS:
        row.status, row.detail_code = "failed", "timeout"
    elif row.status in {"claimed", "submitted"} and row.lease_until < now:
        if row.status == "submitted":
            row.status, row.detail_code = "failed", "uncertain"
        else:
            row.status, row.lease = "queued", ""


def _pending_message(row):
    if row.status == "queued":
        return "等待本机 ChatGPT 接入程序；请保持程序与已登录的 Chrome 运行。"
    return PHASE_MESSAGES.get(row.data.get("phase"), "本机 ChatGPT 正在生成图片，完成后会自动回传。")


def pending_message(db, job_id):
    """Poll a pending handoff without replaying the entire generation graph."""
    if not enabled_for_user():
        return ""
    rows = db.query(PersonalImageJob).filter(PersonalImageJob.user_id == current_user_id(),
        PersonalImageJob.generation_job_id == job_id,
        PersonalImageJob.status.in_(["queued", "claimed", "submitted"])).all()
    for row in rows:
        _expire(db, row)
        if row.status in {"queued", "claimed", "submitted"}:
            return _pending_message(row)
    return ""


def request_image(prompt: str, *, multi: bool = False) -> dict:
    if not enabled_for_user() or not _context.get():
        return {"ok": False, "detail": "个人 Chat 图片需通过已登录账号的持久生成任务使用。"}
    if not prompt.strip() or len(prompt) > 14000:
        return {"ok": False, "detail": "图片内容为空或过长，请分章节生成。"}
    job_id, user, _ = _context.get()
    if user != owner_id():
        raise HTTPException(403, "此图片接入仅限本人")
    identifier = hashlib.sha256(f"{user}\0{job_id}\0{prompt}".encode()).hexdigest()
    with transaction() as db:
        _leased(db)
        row = db.get(PersonalImageJob, identifier)
        if not row:
            row = PersonalImageJob(id=identifier, user_id=user, generation_job_id=job_id,
                                   prompt=prompt, created=time.time(), data={"mode": "multi"} if multi else {})
            db.add(row)
            db.flush()
        _expire(db, row)
        status, data, code = row.status, dict(row.data), row.detail_code
        message = _pending_message(row)
    if status == "completed":
        return {"ok": True, **data, "provider": "chatgpt_web"}
    if status == "failed":
        return {"ok": False, "detail": FAILURES.get(code, FAILURES["worker_error"])}
    raise ProviderPending(message)


def claim() -> dict | None:
    if not enabled_for_user():
        raise HTTPException(403, "此图片接入仅限本人")
    with transaction() as db:
        rows = db.query(PersonalImageJob).filter(PersonalImageJob.user_id == owner_id(),
            PersonalImageJob.status.in_(["queued", "claimed", "submitted"])).order_by(PersonalImageJob.created).all()
        for row in rows:
            _expire(db, row)
        if any(row.status in {"claimed", "submitted"} for row in rows):
            return None
        row = next((row for row in rows if row.status == "queued"), None)
        if not row:
            return None
        row.status, row.lease, row.lease_until = "claimed", secrets.token_hex(24), time.time() + LEASE_SECONDS
        multi = (row.data or {}).get("mode") == "multi"
        return {"id": row.id, "lease": row.lease, "prompt": row.prompt,
                "expires_at": row.created + MAX_AGE_SECONDS,
                "multi": multi, "max_images": MAX_IMAGES if multi else 1}


def _owned_lease(db, identifier: str, lease: str, *, completed=False):
    row = db.get(PersonalImageJob, identifier)
    if not row or row.user_id != current_user_id() or row.user_id != owner_id():
        raise HTTPException(404, "图片任务不存在")
    _expire(db, row)
    allowed = {"claimed", "submitted"} | ({"completed"} if completed else set())
    if row.status not in allowed or not lease or not hmac.compare_digest(row.lease, lease):
        raise HTTPException(409, "图片任务已暂停或接入租约失效")
    return row


def transition(identifier: str, lease: str, action: str, code="", phase=""):
    with transaction() as db:
        row = _owned_lease(db, identifier, lease)
        if action == "submitted":
            row.status = "submitted"  # Acknowledge BEFORE the only UI send.
        elif action == "fail":
            row.status, row.detail_code = "failed", code if code in FAILURES else "worker_error"
        phases = list(PHASE_MESSAGES)
        previous_phase = row.data.get("phase")
        if phase in phases and (previous_phase not in phases or phases.index(phase) >= phases.index(previous_phase)):
            row.data = {**row.data, "phase": phase}
        row.lease_until = time.time() + LEASE_SECONDS
    return {"ok": True}


def _validated_image(content: bytes, content_type: str) -> tuple[tuple[int, int], str, str]:
    """Return (size, mime, suffix) for one decoded, single-frame raster image."""
    if not 0 < len(content) <= MAX_IMAGE_BYTES:
        raise HTTPException(413, "图片为空或超过 20 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as picture:
                fmt, size = picture.format, picture.size
                if fmt not in {"PNG", "JPEG", "WEBP"} or getattr(picture, "n_frames", 1) != 1:
                    raise ValueError("unsupported image")
                if min(size) < 128 or size[0] * size[1] > 25000000:
                    raise ValueError("invalid dimensions")
                picture.verify()
            with Image.open(io.BytesIO(content)) as picture:
                picture.load()
        mime, suffix = {"PNG": ("image/png", ".png"), "JPEG": ("image/jpeg", ".jpg"),
                        "WEBP": ("image/webp", ".webp")}[fmt]
        if content_type.split(";", 1)[0] != mime:
            raise ValueError("mime mismatch")
    except Exception:
        raise HTTPException(422, "仅接受有效的 PNG、JPEG 或 WebP 原图") from None
    return size, mime, suffix


def store_image(identifier: str, lease: str, index: int, content: bytes, content_type: str) -> dict:
    """Save picture ``index`` (1-based) of a multi-image answer; same bytes are idempotent."""
    if not 1 <= int(index) <= MAX_IMAGES:
        raise HTTPException(422, "图片序号无效")
    size, _, suffix = _validated_image(content, content_type)
    digest = hashlib.sha256(content).hexdigest()
    with transaction() as db:
        row = _owned_lease(db, identifier, lease)
        if row.status != "submitted":
            raise HTTPException(409, "任务尚未确认发送")
        images = [dict(item) for item in (row.data or {}).get("images", []) if isinstance(item, dict)]
        existing = next((item for item in images if item.get("index") == index), None)
        if existing:
            if existing.get("sha256") != digest:
                raise HTTPException(409, "这个序号已保存另一张图片")
            return {"ok": True, **existing}
        GEN_DIR.mkdir(parents=True, exist_ok=True)
        target = GEN_DIR / f"chatgpt_{identifier}_{index}{suffix}"
        partial = GEN_DIR / f".chatgpt_{identifier}_{index}.part"
        try:
            partial.write_bytes(content)
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
        item = {"index": int(index), "image_url": f"/static/gen/{target.name}", "sha256": digest,
                "width": size[0], "height": size[1]}
        row.data = {**(row.data or {}), "images": sorted([*images, item], key=lambda value: value["index"])}
        row.lease_until = time.time() + LEASE_SECONDS
    return {"ok": True, **item}


def finish(identifier: str, lease: str, count: int, conversation_url: str = "") -> dict:
    """Complete a multi-image answer after pictures 1..count were stored."""
    if conversation_url and not CONVERSATION_URL.fullmatch(conversation_url):
        conversation_url = ""
    with transaction() as db:
        row = _owned_lease(db, identifier, lease, completed=True)
        if row.status == "completed":
            if int((row.data or {}).get("count") or 1) != int(count):
                raise HTTPException(409, "此任务已按另一组图片完成")
            return {"ok": True, **row.data}
        if row.status != "submitted":
            raise HTTPException(409, "任务尚未确认发送")
        images = sorted((item for item in (row.data or {}).get("images", []) if isinstance(item, dict)),
                        key=lambda value: value["index"])
        if not 1 <= int(count) <= MAX_IMAGES or [item["index"] for item in images] != list(range(1, int(count) + 1)):
            raise HTTPException(422, "图片数量与已上传的序号不一致")
        first = images[0]
        data = {"images": images, "image_url": first["image_url"], "sha256": first["sha256"],
                "width": first["width"], "height": first["height"], "count": int(count),
                "mode": (row.data or {}).get("mode", ""),
                **({"conversation_url": conversation_url} if conversation_url else {})}
        row.status, row.data, row.prompt = "completed", data, ""
        for item in images:
            db.merge(UserAsset(id="asset_" + hashlib.sha256(f"{row.user_id}\0{item['image_url']}".encode()).hexdigest()[:40],
                              user_id=row.user_id, path=item["image_url"], resource_id="", kind="generated"))
    return {"ok": True, **data}


def complete(identifier: str, lease: str, content: bytes, content_type: str):
    if not 0 < len(content) <= MAX_IMAGE_BYTES:
        raise HTTPException(413, "图片为空或超过 20 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as picture:
                fmt, size = picture.format, picture.size
                if fmt not in {"PNG", "JPEG", "WEBP"} or getattr(picture, "n_frames", 1) != 1:
                    raise ValueError("unsupported image")
                if min(size) < 128 or size[0] * size[1] > 25000000:
                    raise ValueError("invalid dimensions")
                picture.verify()
            with Image.open(io.BytesIO(content)) as picture:
                picture.load()
        mime, suffix = {"PNG": ("image/png", ".png"), "JPEG": ("image/jpeg", ".jpg"),
                        "WEBP": ("image/webp", ".webp")}[fmt]
        if content_type.split(";", 1)[0] != mime:
            raise ValueError("mime mismatch")
    except Exception:
        raise HTTPException(422, "仅接受有效的 PNG、JPEG 或 WebP 原图") from None
    digest = hashlib.sha256(content).hexdigest()
    with transaction() as db:
        row = _owned_lease(db, identifier, lease, completed=True)
        if row.status == "completed":
            if row.data.get("sha256") != digest:
                raise HTTPException(409, "此任务已保存另一张图片")
            return {"ok": True, **row.data}
        if row.status != "submitted":
            raise HTTPException(409, "任务尚未确认发送")
        GEN_DIR.mkdir(parents=True, exist_ok=True)
        target = GEN_DIR / f"chatgpt_{identifier}{suffix}"
        partial = GEN_DIR / f".chatgpt_{identifier}.part"
        try:
            partial.write_bytes(content)
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
        url = f"/static/gen/{target.name}"
        data = {"image_url": url, "sha256": digest, "width": size[0], "height": size[1]}
        row.status, row.data, row.prompt = "completed", data, ""
        db.merge(UserAsset(id="asset_" + hashlib.sha256(f"{row.user_id}\0{url}".encode()).hexdigest()[:40],
                          user_id=row.user_id, path=url, resource_id="", kind="generated"))
    return {"ok": True, **data}
