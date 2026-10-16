"""Local subscription worker. Polls only the paired localhost relay."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx
import chatgpt_auth
import kimi_subscription


@contextmanager
def single_instance(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


class Worker:
    def __init__(self, config):
        self.config = config
        address = urlsplit(config['relay_url'])
        if address.scheme != 'http' or address.hostname not in {'127.0.0.1', 'localhost'} or address.username or address.password or address.path:
            raise ValueError('Relay must be a loopback origin')
        if len(config['relay_token']) < 40:
            raise ValueError('Invalid local token')
        self.base = config['relay_url']
        self.headers = {'Authorization': 'Bearer '+config['relay_token']}
        self.root = Path(config['state_dir'])
        self.root.mkdir(parents=True, exist_ok=True)
        self.stop = self.root/'subscriptions.stop'

    def post(self, path, body):
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            response = client.post(self.base+path, headers=self.headers, json=body)
            response.raise_for_status()
            return response.json()

    def execute(self, job):
        request = job['request']
        provider = request['provider']
        model = self.config['kimi_model' if provider == 'kimi' else 'chatgpt_model']
        started = time.monotonic()
        try:
            if provider == 'kimi':
                text = kimi_subscription.infer(request, model, self.config.get('kimi_executable'), timeout=min(job['timeout']-10, 290), home=self.config.get('kimi_home'))
            elif provider == 'chatgpt':
                text = chatgpt_auth.infer(request, model, Path(self.config['chatgpt_auth_path']))
            else:
                raise ValueError('unsupported')
            if request.get('json'):
                # Structured teaching data must be valid, without silent repairs.
                json.loads(text)
            result = {'ok': True, 'provider': provider, 'model': model, 'text': text}
        except kimi_subscription.KimiError as error:
            result = {'ok': False, 'error': str(error)}
        except chatgpt_auth.InferenceError as error:
            result = {'ok': False, 'error': error.code}
        except chatgpt_auth.AuthError:
            result = {'ok': False, 'error': 'not_logged_in'}
        except json.JSONDecodeError:
            result = {'ok': False, 'error': 'invalid_response'}
        except Exception:
            result = {'ok': False, 'error': 'limit_or_provider_error'}
        # Retry only delivery of the same result. Never rerun an inference.
        delivered = False
        for attempt in range(4):
            try:
                self.post('/result', {'id': job['id'], 'lease': job['lease'], 'result': result})
                delivered = True
                break
            except httpx.HTTPStatusError as error:
                if error.response.status_code in {401, 403, 409, 422}:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(min(4, attempt+1))
        receipt = {'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'provider': provider,
                   'model': model, 'ok': result['ok'], 'delivered': delivered,
                   'elapsed_s': round(time.monotonic()-started, 2),
                   'request_id': job['id'], 'error': result.get('error', ''),
                   'response_sha256': hashlib.sha256(result.get('text', '').encode()).hexdigest() if result.get('ok') else ''}
        with (self.root/'subscription-receipts.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(receipt)+'\n')
        print('%s %s: %s' % (provider, model, '完成' if result['ok'] and delivered else '未完成，请检查登录或额度'), flush=True)

    def run(self):
        self.stop.unlink(missing_ok=True)
        print('订阅接入运行中；只使用本人订阅，不回退到 API。关闭本窗口会停止文本接入。', flush=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = set()
            failures = 0
            while not self.stop.exists():
                pending = {task for task in pending if not task.done()}
                try:
                    # Heartbeat uses the claim endpoint even while busy, but only
                    # claims up to the fixed number of workers.
                    if len(pending) < 2:
                        job = self.post('/claim', {}).get('job')
                        if job:
                            pending.add(pool.submit(self.execute, job))
                    else:
                        # A non-claim heartbeat prevents stealing a third job.
                        self.post('/heartbeat', {})
                    failures = 0
                except httpx.HTTPStatusError as error:
                    if error.response.status_code in {401, 403}:
                        raise SystemExit('本机配对认证失败，请重新运行安装入口。') from None
                    failures += 1
                except httpx.HTTPError:
                    failures += 1
                if failures == 1:
                    print('等待本机网站连接…', flush=True)
                time.sleep(min(5, 1+failures))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    worker = Worker(config)
    if args.stop:
        worker.stop.touch()
        return
    with single_instance(worker.root/'subscriptions.lock'):
        try:
            worker.run()
        except KeyboardInterrupt:
            worker.stop.touch()


if __name__ == '__main__':
    main()
