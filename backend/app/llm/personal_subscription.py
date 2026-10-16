"""Personal local subscription route; always fails closed, never falls back to API."""
from __future__ import annotations
import os

from fastapi import HTTPException
import httpx
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from ..models.db import session
from ..models.entities import ModelPreference
from ..tenant import current_user_id

MODELS = {
    'kimi-subscription': {'provider': 'kimi', 'label': 'Kimi Code · 本人订阅', 'tier': '订阅',
                          'cost': '使用本机登录账号的 Kimi Code 订阅用量', 'use': '讲解、笔记、练习和教学设计'},
    'chatgpt-subscription': {'provider': 'chatgpt', 'label': 'ChatGPT / Codex · 本人订阅', 'tier': '订阅',
                             'cost': '使用本机官方授权账号的 ChatGPT Work/Codex 订阅用量', 'use': '讲解、笔记、练习和教学设计'},
}
MESSAGES = {
    'not_logged_in': '订阅账号尚未登录或需要重新授权，请在本机启动菜单中运行对应登录入口。',
    'limit_or_provider_error': '订阅服务未完成请求，请检查账号额度和网络；没有切换到收费 API。',
    'invalid_response': '订阅回复不完整或格式不正确，请重试；没有切换到收费 API。',
    'timeout': '等待订阅回复超时；没有自动重复调用或切换到收费 API。',
    'worker_unavailable': '请先从本机启动菜单启动网站和订阅接入。',
    'queue_full': '本机订阅任务较多，请稍后重试。',
    'unsupported_model': '当前订阅账号不支持所选模型，请检查本机接入配置。',
}


# Prompts may only travel to the paired relay: the Compose service or this Mac.
RELAYS = {'http://subscription-relay:18431', 'http://127.0.0.1:18431', 'http://localhost:18431'}
# Provider-specific failures where the other subscription can still answer.
FAILOVER_ERRORS = {'limit_or_provider_error', 'not_logged_in', 'unsupported_model', 'timeout', 'invalid_response'}


def enabled():
    return os.environ.get('PORTABLE_TEXT_MODE') == 'subscription'


def relay_url():
    value = os.environ.get('PERSONAL_RELAY_URL', '').strip().rstrip('/')
    return value if value in RELAYS else 'http://subscription-relay:18431'


def failover_enabled():
    return os.environ.get('PORTABLE_SUBSCRIPTION_FAILOVER', 'true').strip().lower() not in {'0', 'false', 'no', 'off'}


def other_model(model):
    return 'chatgpt-subscription' if model == 'kimi-subscription' else 'kimi-subscription'


def require_owner(user=None):
    from ..services.owner import resolve_owner
    owner = resolve_owner('PORTABLE_OWNER_ID')
    user = current_user_id() if user is None else user
    if not owner or not user or owner != user:
        raise HTTPException(403, '此迁移副本的订阅接入仅限项目拥有者本人账号。')
    return user


def model_for(prompt='', *, task_context=None):
    from ..services import model_preferences as prefs
    user = require_owner()
    override = prefs._OVERRIDE.get()
    if override:
        model = override.get('model', '')
        if override.get('provider') != 'personal_subscription' or model not in MODELS:
            raise HTTPException(422, '当前仅允许本人订阅模型。')
        return model
    routes, _, _ = prefs._load(user)
    module = prefs.module_for(prompt)
    model = routes.get(module) or routes.get('default')
    # Previous API routes are preserved in the snapshot and never executed here.
    if model not in MODELS:
        model = os.environ.get('PORTABLE_DEFAULT_MODEL', 'kimi-subscription')
    if model not in MODELS:
        raise HTTPException(503, '本机订阅默认模型配置有误。')
    return model


def resolve(prompt, *, task_context=None):
    # Metadata is also read by other migrated accounts. Preserve access to
    # existing materials; complete(), view() and test_route() still require owner.
    from ..services.owner import resolve_owner
    if current_user_id() != resolve_owner('PORTABLE_OWNER_ID'):
        return None
    model = model_for(prompt, task_context=task_context)
    return {'provider': 'personal_subscription', 'model': model, 'automatic': False,
            'reason': '本人本机订阅；没有 API 回退', 'key': '', 'base_url': ''}


async def _ask(model, prompt, system, json_mode, token):
    """One relay round trip. Returns (ok, text_or_error_code)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(345, connect=5), trust_env=False, follow_redirects=False) as client:
            response = await client.post(relay_url() + '/complete',
                headers={'Authorization': 'Bearer '+token},
                json={'provider': MODELS[model]['provider'], 'prompt': prompt, 'system': system, 'json': bool(json_mode)})
            body = response.json()
    except httpx.HTTPError:
        return False, 'worker_unavailable'
    except (ValueError, TypeError):
        return False, 'invalid_response'
    if response.status_code != 200 or body.get('ok') is not True:
        code = body.get('error', '') if isinstance(body, dict) else ''
        return False, code if code in MESSAGES else 'limit_or_provider_error'
    if body.get('provider') != MODELS[model]['provider'] or not isinstance(body.get('text'), str) or not body['text'].strip():
        return False, 'invalid_response'
    return True, body['text']


async def complete(prompt, *, system='', json_mode=False, task_context=None):
    """Kimi Code and ChatGPT/Codex subscriptions back each other up; never a paid API."""
    model = model_for(prompt, task_context=task_context)
    token = os.environ.get('PORTABLE_RELAY_TOKEN', '')
    if len(token) < 40:
        raise RuntimeError('本机订阅配对配置缺失。')
    order = [model, other_model(model)] if failover_enabled() else [model]
    error = 'limit_or_provider_error'
    for candidate in order:
        ok, value = await _ask(candidate, prompt, system, json_mode, token)
        if ok:
            return value
        error = value
        # The local worker or queue is shared, so the other subscription cannot help.
        if value not in FAILOVER_ERRORS:
            break
    raise RuntimeError(MESSAGES.get(error, MESSAGES['limit_or_provider_error']))


def view(user):
    from ..services import model_preferences as prefs
    require_owner(user)
    original, _, revision = prefs._load(user)
    routes = {key: value for key, value in original.items() if value in MODELS}
    default = os.environ.get('PORTABLE_DEFAULT_MODEL', 'kimi-subscription')
    presets = [{'id': provider, 'name': info['label'], 'description': info['cost']+'；连接失败时直接报错。',
                'routes': {'default': model}, 'available': True, 'unavailable_reason': ''}
               for model, info in MODELS.items() for provider in [info['provider']]]
    return {'routes': routes, 'revision': revision, 'modules': prefs.MODULES, 'models': MODELS,
            'providers': {}, 'presets': presets, 'server_routes': {'default': default},
            'verified_at': '2026-10-16', 'subscription_only': True,
            'note': '文字与代码任务优先使用你本人登录的 Kimi Code 或 ChatGPT/Codex 订阅；一个额度不足或未登录时会自动改用另一个，不会切换到收费 API。请保持本机接入程序运行。一图看懂由同一 ChatGPT 账号的网页生成，讲解视频由本机 Claude Code 生成，记忆歌曲由 Suno 生成。'}


def save(user, routes, keys, revision=None):
    from ..services import model_preferences as prefs
    require_owner(user)
    if keys:
        raise HTTPException(422, '订阅模式不接收 API Key，请使用本机启动菜单中的登录入口。')
    if set(routes)-set(prefs.MODULES)-{'default'} or any(value and value not in MODELS for value in routes.values()):
        raise HTTPException(422, '请选择列表中的订阅模型。')
    _, _, current_revision = prefs._load(user)
    if revision is not None and revision != current_revision:
        raise HTTPException(409, '设置已更新，请刷新后再保存。')
    with session() as db:
        row = db.get(ModelPreference, user)
        values = {'routes': {key: value for key, value in routes.items() if value}, 'revision': current_revision+1}
        try:
            if row is None:
                db.add(ModelPreference(user_id=user, credentials={}, **values))
            else:
                result = db.execute(update(ModelPreference).where(ModelPreference.user_id == user,
                    ModelPreference.revision == current_revision).values(**values))
                if result.rowcount != 1:
                    raise HTTPException(409, '设置已更新，请刷新后再保存。')
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, '设置已更新，请刷新后再保存。') from None
    return view(user)


def test_route(user, model):
    require_owner(user)
    if model not in MODELS:
        raise HTTPException(422, '请选择订阅模型。')
    return {'provider': 'personal_subscription', 'model': model, 'key': '', 'base_url': ''}
