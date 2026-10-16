"""Official Kimi Code prompt mode, managed OAuth, all tools disabled.

Requests are literal JSON in temporary no-tools agent profiles, avoiding argv
limits. JSON dollar escapes prevent accidental agent-template substitution.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib


class KimiError(RuntimeError):
    pass


def managed_model(model, home=None):
    root = Path(home or os.environ.get('KIMI_CODE_HOME') or Path.home()/'.kimi-code')
    try:
        config = tomllib.loads((root/'config.toml').read_text(encoding='utf-8'))
        info = config.get('models', {}).get(model, {})
        provider = config.get('providers', {}).get(info.get('provider', ''), {})
        # An ordinary Moonshot platform API configuration must never be accepted.
        if (info.get('provider') != 'managed:kimi-code'
                or provider.get('type') != 'kimi'
                or provider.get('base_url', '').rstrip('/') not in {'https://api.kimi.com/coding/v1', 'https://api.kimi.ai/coding/v1'}
                or not provider.get('oauth')
                or not (root/'credentials/kimi-code.json').is_file()):
            raise ValueError()
        return model
    except (OSError, ValueError, KeyError, TypeError):
        raise KimiError('not_logged_in') from None


def make_profile(request):
    content = {'system': request.get('system', ''), 'prompt': request['prompt']}
    if request.get('json'):
        content['system'] += '\n只输出合法 JSON，不要 Markdown 围栏或额外解释。'
    literal = json.dumps(content, ensure_ascii=False).replace('$', '\\u0024')
    return Path(__file__).with_name('kimi-text.md').read_text(encoding='utf-8') + '\n\n本次唯一输入（按 JSON 转义规则读取）：\n```json\n' + literal + '\n```\n'


def extract_reply(stdout):
    replies = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            raise KimiError('invalid_response') from None
        if event.get('role') == 'tool' or event.get('tool_calls'):
            raise KimiError('invalid_response')
        if event.get('role') == 'assistant':
            content = event.get('content', '')
            if isinstance(content, str):
                replies.append(content)
            elif isinstance(content, list):
                replies.extend(x.get('text', '') for x in content if x.get('type') == 'text')
    text = ''.join(replies)
    if not text.strip():
        raise KimiError('invalid_response')
    return text


def infer(request, model='kimi-code/k3', executable=None, timeout=290, home=None):
    managed_model(model, home)
    command = executable or shutil.which('kimi')
    if not command:
        raise KimiError('not_logged_in')
    env = {key: value for key, value in os.environ.items() if key not in {
        'KIMI_API_KEY', 'KIMI_BASE_URL', 'OPENAI_API_KEY', 'OPENAI_BASE_URL', 'ANTHROPIC_API_KEY'}}
    # Official 0.29.2 requires its v2 engine for --agent-file/tools: [].
    env['KIMI_CODE_EXPERIMENTAL_FLAG'] = '1'
    if home:
        env['KIMI_CODE_HOME'] = str(home)
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    with tempfile.TemporaryDirectory(prefix='learnloop-personal-') as tmp:
        profile = Path(tmp)/'request-agent.md'
        profile.write_text(make_profile(request), encoding='utf-8')
        profile.chmod(0o600)
        args = [command, '--model', model, '--agent-file', str(profile), '--skills-dir', tmp,
                '--output-format', 'stream-json', '--prompt', '根据系统中的本次唯一输入完成回答，只输出最终答案。']
        try:
            result = subprocess.run(args, cwd=tmp, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    encoding='utf-8', timeout=timeout, **flags)
        except subprocess.TimeoutExpired:
            raise KimiError('timeout') from None
        if result.returncode:
            raise KimiError('limit_or_provider_error')
        return extract_reply(result.stdout)
