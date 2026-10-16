"""Official Sign in with ChatGPT plan usage for this user's local installation."""
from __future__ import annotations
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import uuid
import webbrowser

import httpx
import jwt

ISSUER = 'https://auth.openai.com'
RESOURCE = 'https://api.openai.com/v1'
SCOPE = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
REFRESH_LOCK = threading.Lock()
DEFAULT_STATE = Path(__file__).resolve().parents[1] / 'runtime' / 'auth' / 'chatgpt.json'


class AuthError(RuntimeError):
    pass


class InferenceError(AuthError):
    def __init__(self, message, code='limit_or_provider_error'):
        super().__init__(message)
        self.code = code


def private_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    tmp = path.with_suffix('.new')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    tmp.chmod(0o600)
    tmp.replace(path)


def read_state(path):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    state = {'ext_agent_host_id': 'urn:uuid:'+str(uuid.uuid4())}
    private_write(path, state)
    return state


def checked(response):
    if response.status_code != 200:
        raise AuthError('官方授权接口未完成请求（HTTP %s），请重新登录。' % response.status_code)
    return response.json()


def validate_callback(path, expected_state, old_client=''):
    parts = urlsplit(path)
    if parts.path != '/auth/callback' or len(path) > 8192:
        raise AuthError('授权回调无效。')
    values = parse_qs(parts.query, keep_blank_values=True)
    if any(len(v) != 1 for v in values.values()):
        raise AuthError('授权回调重复。')
    if not secrets.compare_digest(values.get('state', [''])[0], expected_state):
        raise AuthError('授权回调身份不匹配。')
    if values.get('error'):
        raise AuthError('授权已取消。')
    client = values.get('client_id', [old_client])[0]
    if not client or client == 'dynamic_agent_client' or (old_client and old_client != client):
        raise AuthError('授权客户端不匹配。')
    code = values.get('code', [''])[0]
    if not code:
        raise AuthError('授权未返回 code。')
    return code, client


def validate_identity(id_token, jwks, client_id, nonce, old_subject=''):
    try:
        header = jwt.get_unverified_header(id_token)
        if header.get('alg') != 'RS256':
            raise ValueError()
        key = next(k for k in jwt.PyJWKSet.from_dict(jwks).keys if k.key_id == header.get('kid'))
        payload = jwt.decode(id_token, key.key, algorithms=['RS256'], audience=client_id,
                             issuer=ISSUER, leeway=5,
                             options={'require': ['sub', 'exp', 'iat', 'nonce', 'iss', 'aud']})
        if not isinstance(payload['sub'], str) or not payload['sub'] or not secrets.compare_digest(str(payload['nonce']), nonce):
            raise ValueError()
        if old_subject and not secrets.compare_digest(old_subject, payload['sub']):
            raise ValueError()
        return payload
    except Exception:
        raise AuthError('官方身份校验失败；未保存凭据或调用模型。') from None


def login(path=DEFAULT_STATE):
    saved = read_state(path)
    state, nonce, verifier = (secrets.token_urlsafe(48) for _ in range(3))
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            if self.headers.get('Host') != '127.0.0.1:%s' % self.server.server_port:
                self.send_error(400)
                return
            try:
                result['code'], result['client_id'] = validate_callback(self.path, state, saved.get('client_id', ''))
                status, message = 200, 'Authorization received. Return to LearnLoop setup.'
            except AuthError:
                if parse_qs(urlsplit(self.path).query).get('state') == [state]:
                    result['denied'] = True
                status, message = 400, 'Authorization was not accepted.'
            self.send_response(status)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(message.encode())

    class Server(HTTPServer):
        def get_request(self):
            conn, addr = super().get_request()
            conn.settimeout(2)
            return conn, addr

    with Server(('127.0.0.1', 0), Callback) as server:
        redirect = 'http://127.0.0.1:%s/auth/callback' % server.server_port
        params = {'client_id': saved.get('client_id', 'dynamic_agent_client'),
                  'ext_agent_host_id': saved['ext_agent_host_id'], 'redirect_uri': redirect,
                  'response_type': 'code', 'scope': SCOPE, 'resource': RESOURCE,
                  'state': state, 'nonce': nonce, 'code_challenge_method': 'S256',
                  'code_challenge': base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')}
        if not saved.get('client_id'):
            params['agent_name_hint'] = 'LearnLoop Personal'
        if saved.get('email'):
            params['login_hint'] = saved['email']
        # Do not print authorization URLs or login tokens to logs.
        print('Continue with ChatGPT：请在打开的官方网页中选择你当前的订阅账号并授权。', flush=True)
        webbrowser.open(ISSUER+'/api/accounts/authorize?'+urlencode(params))
        deadline = time.monotonic()+600
        server.timeout = 1
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if not result or result.get('denied'):
        raise AuthError('没有完成授权。可以稍后再次运行 03-登录ChatGPT.command。')
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        tokens = checked(client.post(ISSUER+'/api/accounts/oauth/token', data={
            'grant_type': 'authorization_code', 'client_id': result['client_id'], 'code': result['code'],
            'code_verifier': verifier, 'redirect_uri': redirect, 'resource': RESOURCE}))
        identity = validate_identity(tokens.get('id_token', ''), checked(client.get(ISSUER+'/.well-known/jwks.json')),
                                     result['client_id'], nonce, saved.get('subject', ''))
        if ('chatgpt.tokens.use.direct' not in tokens.get('scope', '').split()
                or tokens.get('token_type', '').lower() != 'bearer' or not tokens.get('access_token')):
            raise AuthError('没有取得订阅用量权限；未启用调用。')
        saved.update(client_id=result['client_id'], subject=identity['sub'], email=identity.get('email', ''),
                     tokens=tokens, expires_at=time.time()+int(tokens.get('expires_in', 300)))
        private_write(path, saved)
    models = available_models(path)
    print('已登录 ChatGPT：%s；可用订阅模型 %s 个。' % (saved.get('email') or '已验证账号', len(models)), flush=True)
    print('该连接使用 ChatGPT Work/Codex 订阅用量；未配置 OpenAI API Key。', flush=True)
    return models


def access_token(path=DEFAULT_STATE):
    with REFRESH_LOCK:
        state = read_state(path)
        tokens = state.get('tokens', {})
        if 'chatgpt.tokens.use.direct' not in tokens.get('scope', '').split() or not tokens.get('access_token'):
            raise AuthError('ChatGPT 订阅尚未登录。')
        if state.get('expires_at', 0) > time.time()+90:
            return tokens['access_token']
        if not tokens.get('refresh_token'):
            raise AuthError('ChatGPT 需要重新登录。')
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            fresh = checked(client.post(ISSUER+'/api/accounts/oauth/token', data={
                'grant_type': 'refresh_token', 'client_id': state['client_id'],
                'refresh_token': tokens['refresh_token'], 'resource': RESOURCE}))
        merged = {**tokens, **fresh}
        if (not fresh.get('access_token') or merged.get('token_type', '').lower() != 'bearer'
                or 'chatgpt.tokens.use.direct' not in merged.get('scope', '').split()):
            raise AuthError('订阅权限已变化，请重新登录。')
        state.update(tokens=merged, expires_at=time.time()+int(fresh.get('expires_in', 300)))
        private_write(path, state)
        return fresh['access_token']


def available_models(path=DEFAULT_STATE):
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        body = checked(client.get(RESOURCE+'/models', headers={'Authorization': 'Bearer '+access_token(path)}))
    models = [x['slug'] for x in body.get('models', []) if x.get('visibility') == 'list' and x.get('slug')]
    if not models:
        raise AuthError('当前账号没有可用订阅模型。')
    return models


def read_completed_events(lines):
    parts, complete = [], False
    for line in lines:
        if not line.startswith('data: '):
            continue
        if line[6:] == '[DONE]':
            break
        event = json.loads(line[6:])
        kind = event.get('type')
        if kind == 'response.output_text.delta':
            parts.append(event.get('delta', ''))
        elif kind == 'response.completed':
            complete = event.get('response', {}).get('status') == 'completed'
        elif kind in {'error', 'response.failed', 'response.incomplete'}:
            raise InferenceError('订阅请求未完成；未切换到 API。')
    text = ''.join(parts)
    if not complete or not text.strip():
        raise InferenceError('订阅响应不完整；未切换到 API。', 'invalid_response')
    return text


def infer(request, model, path=DEFAULT_STATE):
    if model not in available_models(path):
        raise InferenceError('所选模型不在当前账号的订阅模型列表中。', 'unsupported_model')
    system = request.get('system', '')
    prompt = request['prompt']
    if request.get('json'):
        prompt += '\n只输出有效 JSON，不要 Markdown 围栏或额外解释。'
    body = {'model': model, 'store': False, 'stream': True,
            'input': ([{'role': 'developer', 'content': system}] if system else [])+
                     [{'role': 'user', 'content': prompt}]}
    with httpx.Client(timeout=httpx.Timeout(300, connect=20), follow_redirects=False) as client:
        with client.stream('POST', RESOURCE+'/responses', json=body,
                           headers={'Authorization': 'Bearer '+access_token(path)}) as response:
            if response.status_code != 200:
                if response.status_code == 401:
                    raise AuthError('订阅登录已失效，请重新登录。')
                raise InferenceError('订阅请求失败（HTTP %s）；未切换到 API。' % response.status_code)
            return read_completed_events(response.iter_lines())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['login', 'status', 'probe'])
    parser.add_argument('--state', type=Path, default=DEFAULT_STATE)
    parser.add_argument('--model', default='gpt-6.1-sol')
    args = parser.parse_args()
    try:
        if args.action == 'login':
            login(args.state)
        elif args.action == 'status':
            state = read_state(args.state)
            print(json.dumps({'account': state.get('email', ''), 'models': available_models(args.state)}, ensure_ascii=False))
        else:
            text = infer({'prompt': '只回复：连接成功', 'system': ''}, args.model, args.state)
            print(json.dumps({'provider': 'ChatGPT Work/Codex', 'model': args.model, 'reply': text[:80]}, ensure_ascii=False))
    except AuthError as error:
        raise SystemExit(str(error)) from None
    except Exception:
        raise SystemExit('连接未完成，请检查网络或重新登录；未打印凭据。') from None


if __name__ == '__main__':
    main()
