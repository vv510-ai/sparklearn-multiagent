"""Private in-memory request relay between Docker and the owner's Mac process.

No provider keys or inference code. Bind the published Docker port to loopback.
Requests are never re-leased or retried after claiming, to avoid duplicate usage.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

MAX_BODY = 1024 * 1024
MAX_JOBS = 8
TTL = 330
ERRORS = {'not_logged_in', 'limit_or_provider_error', 'invalid_response', 'timeout', 'worker_unavailable', 'unsupported_model'}


@dataclass
class Job:
    payload: dict
    deadline: float
    lease: str = ''
    result: dict | None = None
    done: threading.Event = field(default_factory=threading.Event)


class Queue:
    def __init__(self):
        self.jobs = {}
        self.receipts = {}
        self.lock = threading.Lock()
        self.worker_seen = 0.0

    def enqueue(self, payload):
        if (payload.get('provider') not in {'kimi', 'chatgpt'}
                or not isinstance(payload.get('prompt'), str)
                or not 0 < len(payload['prompt']) <= 240000
                or not isinstance(payload.get('system', ''), str)
                or len(payload.get('system', '')) > 64000):
            raise ValueError('invalid_request')
        with self.lock:
            if len(self.jobs) >= MAX_JOBS:
                raise RuntimeError('queue_full')
            if time.monotonic() - self.worker_seen > 20:
                raise RuntimeError('worker_unavailable')
            key = secrets.token_hex(24)
            job = Job(payload, time.monotonic() + TTL)
            self.jobs[key] = job
        return key, job

    def claim(self):
        with self.lock:
            now = time.monotonic()
            self.worker_seen = now
            self.receipts = {k: v for k, v in self.receipts.items() if v[0] > now}
            for key, job in self.jobs.items():
                if not job.lease and job.deadline > now and not job.done.is_set():
                    job.lease = secrets.token_hex(24)
                    return {'id': key, 'lease': job.lease, 'request': job.payload, 'timeout': max(1, int(job.deadline-now))}
        return None

    def finish(self, data):
        key, lease, result = data.get('id', ''), data.get('lease', ''), data.get('result')
        if not isinstance(result, dict):
            raise ValueError('invalid_result')
        if result.get('ok') is True:
            if not isinstance(result.get('text'), str) or not result['text'].strip() or len(result['text']) > 800000:
                raise ValueError('invalid_result')
            if result.get('provider') not in {'kimi', 'chatgpt'} or not isinstance(result.get('model'), str):
                raise ValueError('invalid_result')
        elif result.get('error') not in ERRORS:
            raise ValueError('invalid_result')
        digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        with self.lock:
            job = self.jobs.get(key)
            if job is None:
                receipt = self.receipts.get(key)
                if receipt and hmac.compare_digest(receipt[1], lease) and receipt[2] == digest:
                    return
                raise LookupError('expired')
            if not lease or not hmac.compare_digest(job.lease, lease) or time.monotonic() >= job.deadline:
                raise LookupError('expired')
            if result.get('ok') and result['provider'] != job.payload['provider']:
                raise ValueError('provider_mismatch')
            if job.result is not None and job.result != result:
                raise LookupError('result_conflict')
            job.result = result
            self.receipts[key] = (time.monotonic()+600, lease, digest)
            job.done.set()

    def wait(self, key, job):
        job.done.wait(max(0, job.deadline - time.monotonic()))
        with self.lock:
            self.jobs.pop(key, None)
            result = job.result or {'ok': False, 'error': 'timeout'}
            job.payload = {}
            return result


def handler(queue, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, data):
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if self.path != '/health':
                return self.reply(404, {'error': 'not_found'})
            self.reply(200, {'status': 'ok', 'worker_connected': time.monotonic()-queue.worker_seen < 20})

        def do_POST(self):
            try:
                size = int(self.headers.get('Content-Length', '-1'))
                if not 0 <= size <= MAX_BODY:
                    return self.reply(413, {'error': 'body_size'})
                self.connection.settimeout(15)
                raw = self.rfile.read(size)
                # Drain bounded request bytes before an early rejection. Closing
                # with unread bytes may reset TCP and hide the HTTP error.
                expected = 'Bearer '+token
                if not hmac.compare_digest(self.headers.get('Authorization', ''), expected):
                    return self.reply(401, {'error': 'unauthorized'})
                if self.headers.get('Origin'):
                    return self.reply(403, {'error': 'browser_not_allowed'})
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError('invalid_request')
                if self.path == '/complete':
                    key, job = queue.enqueue(data)
                    result = queue.wait(key, job)
                    return self.reply(200 if result.get('ok') else 503, result)
                if self.path == '/claim':
                    return self.reply(200, {'job': queue.claim()})
                if self.path == '/heartbeat':
                    with queue.lock:
                        queue.worker_seen = time.monotonic()
                    return self.reply(200, {'ok': True})
                if self.path == '/result':
                    queue.finish(data)
                    return self.reply(200, {'ok': True})
                self.reply(404, {'error': 'not_found'})
            except (ValueError, TypeError, KeyError):
                self.reply(422, {'error': 'invalid_request'})
            except LookupError:
                self.reply(409, {'error': 'expired_or_conflict'})
            except RuntimeError as error:
                self.reply(503, {'error': str(error) if str(error) in {'queue_full', 'worker_unavailable'} else 'unavailable'})
    return Handler


def main():
    token = os.environ['PORTABLE_RELAY_TOKEN']
    if len(token) < 40:
        raise SystemExit('Invalid local relay token')
    # Docker publishes the port on loopback; a native Mac run binds loopback directly.
    host = os.environ.get('RELAY_HOST', '0.0.0.0')
    if host not in {'0.0.0.0', '127.0.0.1'}:
        raise SystemExit('RELAY_HOST must be 0.0.0.0 (container) or 127.0.0.1 (native)')
    server = ThreadingHTTPServer((host, 18431), handler(Queue(), token))
    server.daemon_threads = True
    print('LearnLoop personal subscription relay ready', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
