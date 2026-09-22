"""Per-account model selection. Secrets never enter profiles, prompts or responses."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from contextvars import ContextVar

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from ..auth import _jwt_secret
from ..config import get_settings
from ..models.db import init_db, session
from ..models.entities import ModelPreference
from ..tenant import current_user_id

PROVIDERS = {
    "deepseek": {"name": "DeepSeek · 国产", "base_url": "https://api.deepseek.com", "key_env": "deepseek_api_key", "docs": "https://api-docs.deepseek.com/quick_start/pricing/"},
    "kimi": {"name": "Kimi · 国产", "base_url": "https://api.moonshot.cn/v1", "key_env": "kimi_api_key", "docs": "https://platform.kimi.com/docs/guide/kimi-k3-quickstart"},
    "openai": {"name": "OpenAI / ChatGPT 系列", "base_url": "https://api.openai.com/v1", "key_env": "openai_api_key", "docs": "https://developers.openai.com/api/docs/models"},
}
MODELS = {
    "deepseek-flash": {"provider": "deepseek", "label": "DeepSeek V4.1 Flash", "tier": "经济", "cost": "约 $0.15–0.30 输入 / $0.60–1.20 输出，每百万 token；未命中缓存", "use": "日常解释、词汇、练习和快速提问"},
    "deepseek-v4-pro": {"provider": "deepseek", "label": "DeepSeek V4 Pro", "tier": "均衡", "cost": "约 $0.66–1.32 输入 / $1.98–3.96 输出，每百万 token；未命中缓存", "use": "中文深入讲解、知识整合和推导"},
    "kimi-k3": {"provider": "kimi", "label": "Kimi K3", "tier": "进阶", "cost": "按 Kimi 官方价格计费；需充值解锁，始终启用思考", "use": "长材料整合、研究报告、复杂动画分镜"},
    "gpt-5.6-terra": {"provider": "openai", "label": "GPT-5.6 Terra", "tier": "均衡", "cost": "以 OpenAI 官方实时价格为准", "use": "英文解释、结构化笔记和日常教学"},
    "gpt-6-astra": {"provider": "openai", "label": "GPT-6 Astra", "tier": "高能力", "cost": "$10 输入 / $50 输出，每百万 token；未命中缓存", "use": "复杂跨学科推理、研究综合与严谨分镜设计"},
}
MODULES = {"tutor": "讲解与问题引导", "notes": "笔记与资料整合", "quiz": "出题与反馈", "english": "英语场景学习", "animation": "教学动画设计", "knowledge_map": "一图看懂内容设计", "research": "深度研究"}
_OVERRIDE: ContextVar[dict | None] = ContextVar("model_test_override", default=None)


def _cipher() -> Fernet:
    configured = get_settings().model_key_encryption_secret
    if configured and len(configured) < 32:
        raise HTTPException(503, "模型密钥加密配置不完整，请联系管理员")
    secret = configured or _jwt_secret()
    material = ("learnloop-model-keys-v1:" + secret).encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest()))


def _seal(user: str, provider: str, key: str) -> str:
    return _cipher().encrypt(json.dumps([user, provider, key]).encode()).decode()


def _open(user: str, provider: str, value: str) -> str:
    try:
        owner, kind, key = json.loads(_cipher().decrypt(value.encode()))
        if (owner, kind) != (user, provider):
            raise ValueError("credential owner mismatch")
        return key
    except (ValueError, InvalidToken, TypeError):
        raise HTTPException(409, "API 密钥无法解密，请在设置中重新填写") from None


def _load(user: str) -> tuple[dict, dict, int]:
    init_db()
    with session() as db:
        row = db.get(ModelPreference, user)
        return (dict(row.routes or {}), dict(row.credentials or {}), row.revision) if row else ({}, {}, 0)


def view(user: str) -> dict:
    routes, keys, revision = _load(user)
    settings = get_settings()
    return {"routes": routes, "revision": revision, "modules": MODULES, "models": MODELS,
            "providers": {p: {k: v for k, v in info.items() if k != "key_env"} | {
                "has_personal_key": bool(keys.get(p)),
                "has_server_key": bool(getattr(settings, info["key_env"], "")),
            } for p, info in PROVIDERS.items()},
            "verified_at": "2026-09-22",
            "note": "按任务选择文本模型。动画、图片的渲染服务另行配置；价格不是质量排名。个人密钥加密保存，仅对当前账户生效。"}


def save(user: str, routes: dict[str, str], updates: dict[str, str], revision: int | None = None) -> dict:
    if set(routes) - set(MODULES) - {"default"} or any(v and v not in MODELS for v in routes.values()):
        raise HTTPException(422, "请选择列表中的功能和模型")
    if set(updates) - set(PROVIDERS):
        raise HTTPException(422, "不支持的模型供应商")
    for key in updates.values():
        if key and (len(key.strip()) < 8 or len(key) > 512 or re.search(r"\s", key.strip())):
            raise HTTPException(422, "API Key 格式不正确，请粘贴完整密钥")
    _, keys, current_revision = _load(user)
    conflict = "设置已在其他页面更新，请刷新后重新选择并保存"
    if revision is not None and revision != current_revision:
        raise HTTPException(409, conflict)
    for provider, key in updates.items():
        if key.strip():
            keys[provider] = _seal(user, provider, key.strip())
        else:
            keys.pop(provider, None)
    settings = get_settings()
    for model in routes.values():
        if not model:
            continue
        p = MODELS[model]["provider"]
        if not keys.get(p) and not getattr(settings, PROVIDERS[p]["key_env"], ""):
            raise HTTPException(422, f"请先填写 {PROVIDERS[p]['name']} 的 API Key")
    with session() as db:
        values = {"routes": {k: v for k, v in routes.items() if v}, "credentials": keys, "revision": current_revision + 1}
        try:
            if current_revision == 0:
                db.add(ModelPreference(user_id=user, **values))
            else:
                changed = db.execute(update(ModelPreference).where(ModelPreference.user_id == user, ModelPreference.revision == current_revision).values(**values))
                if changed.rowcount != 1:
                    raise HTTPException(409, conflict)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, conflict) from None
    return view(user)


def module_for(prompt: str) -> str:
    capability = prompt.partition("\n")[0].removeprefix("CAPABILITY=")
    if capability.startswith("english."):
        return "english"
    if capability.startswith("research."):
        return "research"
    if capability.startswith("media.") and "ppt" not in capability:
        return "animation"
    if capability in {"doc.one_page", "image.one_page", "mindmap.leaf", "doc.infographic"}:
        return "knowledge_map"
    if capability.startswith("quiz."):
        return "quiz"
    if capability.startswith("doc.") or "ppt" in capability:
        return "notes"
    return "tutor"


def resolve(prompt: str) -> dict | None:
    if _OVERRIDE.get() is not None:
        return _OVERRIDE.get()
    user = current_user_id()
    if not user:
        return None
    routes, keys, _ = _load(user)
    model = routes.get(module_for(prompt)) or routes.get("default")
    if not model:
        return None
    provider = MODELS[model]["provider"]
    key = (_open(user, provider, keys[provider]) if keys.get(provider)
           else getattr(get_settings(), PROVIDERS[provider]["key_env"], ""))
    if not key:
        raise HTTPException(422, "所选模型缺少 API Key，请打开模型设置")
    return {"model": model, "provider": provider, "key": key, "base_url": PROVIDERS[provider]["base_url"]}


def test_route(user: str, model: str) -> dict:
    if model not in MODELS:
        raise HTTPException(422, "不支持的模型")
    _, keys, _ = _load(user)
    p = MODELS[model]["provider"]
    key = _open(user, p, keys[p]) if keys.get(p) else getattr(get_settings(), PROVIDERS[p]["key_env"], "")
    if not key:
        raise HTTPException(422, "请先保存对应的 API Key")
    return {"model": model, "provider": p, "key": key, "base_url": PROVIDERS[p]["base_url"]}
