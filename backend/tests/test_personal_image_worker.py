import importlib.util
import base64
import hashlib
import io
import json
import sys
import time
import threading
import urllib.error
from pathlib import Path
from types import SimpleNamespace
import pytest

spec = importlib.util.spec_from_file_location("personal_chat_worker", Path(__file__).resolve().parents[2] / "scripts/personal_chat_image_worker.py")
worker_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker_module)


@pytest.fixture
def worker(tmp_path):
    return worker_module.Worker({"site_url":"http://127.0.0.1:13400", "worker_token":"test-token-"*5,
        "state_dir":str(tmp_path/"state"), "downloads_dir":str(tmp_path),
        "node_path":sys.executable, "cli_path":__file__})


def job():
    return {"id":"a"*64, "lease":"b"*48, "prompt":"1、2、3 与 (rear+1)%N", "expires_at":time.time()+1000}


def test_idle_network_outage_recovers_without_sending_an_image(worker, monkeypatch):
    calls = []
    def api(path):
        calls.append(path)
        if len(calls) == 1:
            raise urllib.error.URLError('connection reset')
        return {'job': None}
    pauses = []
    def pause(_, delay):
        pauses.append(delay)
        return len(pauses) == 1
    monkeypatch.setattr(worker, 'api', api)
    monkeypatch.setattr(worker, 'run_job', lambda _: pytest.fail('no image job was claimed'))
    monkeypatch.setattr(worker_module, 'wait_for_queue', pause)
    worker_module.run(worker, SimpleNamespace(check_browser=False, once=False))
    assert calls == ['claim', 'claim']


def test_idle_outage_longer_than_six_retries_still_recovers_without_sending(worker, monkeypatch):
    calls, pauses = [], []
    def api(path):
        calls.append(path)
        if len(calls) <= 9:
            raise urllib.error.URLError('offline')
        return {'job': None}
    def pause(_, delay):
        pauses.append(delay)
        return len(pauses) < 10
    monkeypatch.setattr(worker, 'api', api)
    monkeypatch.setattr(worker, 'run_job', lambda _: pytest.fail('must never send an image'))
    monkeypatch.setattr(worker_module, 'wait_for_queue', pause)
    worker_module.run(worker, SimpleNamespace(check_browser=False, once=False))
    assert calls == ['claim'] * 10
    assert pauses[:5] == [5, 10, 20, 40, 60] and max(pauses) == 60


@pytest.mark.parametrize('status', [401, 403, 429])
def test_auth_or_rate_limit_stops_without_network_retry(worker, monkeypatch, status):
    def api(_):
        raise urllib.error.HTTPError('https://site.test', status, 'stop', {}, None)
    monkeypatch.setattr(worker, 'api', api)
    monkeypatch.setattr(worker_module, 'wait_for_queue', lambda *_: pytest.fail('must not retry authentication'))
    with pytest.raises(SystemExit):
        worker_module.run(worker, SimpleNamespace(check_browser=False, once=False))


def test_task_network_error_does_not_retry_the_claimed_image(worker, monkeypatch):
    calls = []
    def api(path):
        calls.append(path)
        return {'job': job()}
    attempts = []
    def run_job(task):
        attempts.append(task['id'])
        raise urllib.error.URLError('response lost after send')
    monkeypatch.setattr(worker, 'api', api)
    monkeypatch.setattr(worker, 'run_job', run_job)
    monkeypatch.setattr(worker_module, 'wait_for_queue', lambda *_: pytest.fail('must stop after ambiguous task'))
    with pytest.raises(SystemExit):
        worker_module.run(worker, SimpleNamespace(check_browser=False, once=False))
    assert calls == ['claim'] and len(attempts) == 1


@pytest.mark.parametrize("url", ["http://example.test", "https://user:secret@example.test", "file:///etc/passwd", "https://example.test/private", "https://example.test/?token=secret", "https://"])
def test_config_does_not_send_pairing_token_over_untrusted_transports(worker, url):
    with pytest.raises(ValueError):
        worker_module.validate_config({**worker.config, "site_url":url})


def test_send_failure_is_not_retried_and_disconnect_is_attempted(worker, monkeypatch):
    updates, clicks, commands = [], [], []
    monkeypatch.setattr(worker, "heartbeat", lambda *args:None)
    monkeypatch.setattr(worker, "connect", lambda:'uid=1_1 textbox "询问 ChatGPT" multiline')
    monkeypatch.setattr(worker, "snapshot", lambda:'uid=2_1 button "发送"')
    monkeypatch.setattr(worker, "update", lambda action, **extra:updates.append((action, extra)))
    monkeypatch.setattr(worker, "cli", lambda *args:commands.append(args) or "")
    def ambiguous_click(uid):
        clicks.append(uid)
        raise TimeoutError("connection lost after send")
    monkeypatch.setattr(worker, "click", ambiguous_click)
    with pytest.raises(TimeoutError):
        worker.run_job(job())
    assert clicks == ["2_1"]
    assert updates[0][0] == "submitted" and updates[-1] == ("fail", {"code":"uncertain"})
    assert commands[-1] == ("stop",)
    assert json.loads((worker.root/"active.json").read_text("utf-8"))["failed"] == "uncertain"


def test_chinese_chat_home_waits_for_enabled_controls_and_uses_structured_page_id(worker, monkeypatch):
    commands = []
    def cli(*args):
        commands.append(args)
        return json.dumps({"pages":[{"id":9,"url":"https://chatgpt.com/","selected":True}]}) if args[0]=="new_page" else ""
    snapshots=iter(['uid=1_1 button "聊天" disableable disabled pressed', 'uid=2_1 button "聊天" pressed'])
    monkeypatch.setattr(worker, "cli", cli)
    monkeypatch.setattr(worker, "snapshot", lambda:next(snapshots))
    monkeypatch.setattr(worker_module.time, "sleep", lambda _:None)
    assert '"聊天" pressed' in worker.connect()
    assert worker.page == 9 and not any(command[0]=="click" for command in commands)


def test_invalid_task_never_connects_or_writes_outside_state_directory(worker, monkeypatch):
    monkeypatch.setattr(worker, "connect", lambda:pytest.fail("must not connect"))
    with pytest.raises(worker_module.WorkerError):
        worker.run_job({**job(), "id":"../../unsafe"})
    assert not (worker.root/"active.json").exists()


def test_near_expiry_never_opens_chat_or_sends(worker, monkeypatch):
    updates = []
    monkeypatch.setattr(worker, "heartbeat", lambda *args:None)
    monkeypatch.setattr(worker, "connect", lambda:pytest.fail("must not connect"))
    monkeypatch.setattr(worker, "update", lambda action, **extra:updates.append((action, extra)))
    monkeypatch.setattr(worker, "cli", lambda *args:"")
    with pytest.raises(worker_module.WorkerError, match="timeout"):
        worker.run_job({**job(), "expires_at":time.time()+10})
    assert updates == [("fail", {"code":"timeout"})]


def test_connect_delay_is_checked_before_fill_or_send(worker, monkeypatch):
    updates = []
    task = job()
    def delayed_connect():
        task["expires_at"] = time.time()+10
        return 'uid=1_1 textbox "询问 ChatGPT"'
    monkeypatch.setattr(worker, "heartbeat", lambda *args:None)
    monkeypatch.setattr(worker, "connect", delayed_connect)
    monkeypatch.setattr(worker, "update", lambda action, **extra:updates.append((action, extra)))
    monkeypatch.setattr(worker, "cli", lambda *args:pytest.fail("must not fill") if args[0]!="stop" else "")
    with pytest.raises(worker_module.WorkerError, match="timeout"):
        worker.run_job(task)
    assert updates == [("fail", {"code":"timeout"})]


def test_in_flight_old_heartbeat_cannot_touch_next_job(worker, monkeypatch):
    entered, release, old_lost = threading.Event(), threading.Event(), threading.Event()
    class Stop:
        stopped = False
        def wait(self, _): return self.stopped
        def is_set(self): return self.stopped
    stop = Stop()
    observed = []
    def delayed_api(path, payload):
        observed.append((path, payload))
        entered.set()
        release.wait(2)
        raise TimeoutError()
    monkeypatch.setattr(worker, "api", delayed_api)
    task = job()
    pulse = threading.Thread(target=worker.heartbeat, args=(dict(task),stop,old_lost))
    pulse.start()
    assert entered.wait(1)
    stop.stopped = True
    worker.job, worker.lost = {**task,"id":"c"*64}, threading.Event()
    release.set()
    pulse.join(2)
    assert not pulse.is_alive() and not worker.lost.is_set() and not old_lost.is_set()
    assert observed == [(task['id']+'/heartbeat', {"lease":task['lease']})]


def test_transient_heartbeat_failure_recovers_same_lease_without_losing_task(worker, monkeypatch):
    calls, waits, clock = [], [], [0]
    class Stop:
        stopped = False
        def wait(self, seconds):
            waits.append(seconds)
            clock[0] += seconds
            return self.stopped
        def is_set(self): return self.stopped
    stop, lost, task = Stop(), threading.Event(), job()
    def api(path, payload):
        calls.append((path, payload))
        if len(calls) == 1:
            raise urllib.error.URLError('transient connection reset')
        stop.stopped = True
        return {'ok': True}
    monkeypatch.setattr(worker_module.time, 'monotonic', lambda:clock[0])
    monkeypatch.setattr(worker, 'api', api)
    worker.heartbeat(task, stop, lost)
    assert not lost.is_set() and waits[:2] == [20, 5]
    assert calls == [(task['id']+'/heartbeat', {'lease':task['lease']})] * 2


def test_heartbeat_network_retry_stops_before_server_lease_expires(worker, monkeypatch):
    calls, clock = [], [0]
    class Stop:
        def wait(self, seconds):
            clock[0] += seconds
            return False
        def is_set(self): return False
    def api(path, payload):
        calls.append(path)
        clock[0] += 35  # The transport timeout is included in the retry budget.
        raise TimeoutError('offline')
    monkeypatch.setattr(worker_module.time, 'monotonic', lambda:clock[0])
    monkeypatch.setattr(worker, 'api', api)
    lost = threading.Event()
    worker.heartbeat(job(), Stop(), lost)
    assert lost.is_set() and len(calls) == 2 and clock[0] == 95 < 180


@pytest.mark.parametrize('status', [401, 403, 409, 429])
def test_rejected_heartbeat_stops_immediately_without_retry(worker, monkeypatch, status):
    calls = []
    class Stop:
        def wait(self, _): return False
        def is_set(self): return False
    def api(path, payload):
        calls.append(path)
        raise urllib.error.HTTPError('https://site.test', status, 'stop', {}, None)
    monkeypatch.setattr(worker, 'api', api)
    lost = threading.Event()
    worker.heartbeat(job(), Stop(), lost)
    assert lost.is_set() and len(calls) == 1


def test_stale_completion_does_not_stop_a_loading_image(worker, monkeypatch, tmp_path):
    import hashlib
    data=b'tested-image-transport'
    path=tmp_path/'image.png'
    path.write_bytes(data)
    root='uid=1_0 RootWebArea "Test" url="https://chatgpt.com/c/test-123"\n'
    snapshots=iter(['uid=2_1 button "发送"', root+'uid=3_1 StaticText "回答已完成"',
                    root+'uid=3_2 button "停止"', root+'uid=4_1 button "已生成图像 1"',
                    root+'uid=5_1 button "已生成图像 1"'])
    clicks=[]
    monkeypatch.setattr(worker, "heartbeat", lambda *args:None)
    monkeypatch.setattr(worker, "connect", lambda:'uid=1_1 textbox "询问 ChatGPT"')
    monkeypatch.setattr(worker, "snapshot", lambda:next(snapshots))
    monkeypatch.setattr(worker, "cli", lambda *args:"")
    monkeypatch.setattr(worker, "click", lambda uid:clicks.append(uid))
    monkeypatch.setattr(worker, "update", lambda *args, **kwargs:None)
    monkeypatch.setattr(worker, "download", lambda _:path)
    monkeypatch.setattr(worker, "api", lambda *args, **kwargs:{"sha256":hashlib.sha256(data).hexdigest()})
    monkeypatch.setattr(worker_module.time, "sleep", lambda _:None)
    worker.run_job(job())
    assert clicks == ["2_1"]
    assert json.loads((worker.root/'active.json').read_text(encoding='utf-8'))['completed'] is True


def browser_image():
    from PIL import Image
    output = io.BytesIO()
    Image.new('RGB', (160, 128), '#236b53').save(output, format='PNG')
    content = output.getvalue()
    return content, {'conversation_url':'https://chatgpt.com/c/test-123', 'mime':'image/png',
        'bytes':len(content), 'width':160, 'height':128,
        'sha256':hashlib.sha256(content).hexdigest(),
        'data':'data:image/png;base64,' + base64.b64encode(content).decode()}


def test_image_uses_existing_browser_connection_and_preserves_original_bytes(worker, monkeypatch):
    content, exported = browser_image()
    worker.job, worker.page, worker.conversation_url = job(), 9, exported['conversation_url']
    calls = []
    def cli(*args):
        calls.append(args)
        if args[0] == 'evaluate_script':
            Path(args[-1]).write_text(json.dumps(exported), encoding='utf-8')
        return ''
    monkeypatch.setattr(worker, 'cli', cli)
    monkeypatch.setattr(worker, 'snapshot', lambda:'uid=2_1 button "知识图 的文件操作"\nuid=2_2 image "已生成图像 1"\nuid=2_3 button "下载"')
    result = worker.download('uid=1_1 button "已生成图像 1"')
    assert result.read_bytes() == content
    assert result.parent == worker.root and result.stem == worker.job['id']
    assert [command[0] for command in calls] == ['click', 'evaluate_script']
    assert calls[0][2] == '1_1'  # Open the generated preview, never send again.
    assert not list(worker.root.glob('*.browser-image.json'))


@pytest.mark.parametrize('field,value', [
    ('conversation_url','https://chatgpt.com/c/another-user-request'),
    ('mime','image/svg+xml'), ('sha256','0'*64), ('bytes',1), ('width',159),
    ('data','data:image/png;base64,not-valid!'),
    ('data','https://chatgpt.com/backend-api/private'),
])
def test_invalid_browser_image_cannot_be_saved_or_uploaded(worker, field, value):
    _, exported = browser_image()
    worker.job, worker.conversation_url = job(), exported['conversation_url']
    exported[field] = value
    with pytest.raises(worker_module.WorkerError, match='worker_error'):
        worker.save_browser_image(exported)
    assert not list(worker.root.glob('*.png')) and not list(worker.root.glob('*.part'))


def test_expired_image_is_not_saved_and_export_is_removed(worker, monkeypatch):
    _, exported = browser_image()
    worker.job, worker.page, worker.conversation_url = job(), 9, exported['conversation_url']
    worker.job['expires_at'] = time.time() + 20
    monkeypatch.setattr(worker, 'snapshot', lambda:'uid=2_1 button "知识图 的文件操作"\nuid=2_2 image "已生成图像 1"\nuid=2_3 button "下载"')
    def cli(*args):
        if args[0] == 'evaluate_script':
            Path(args[-1]).write_text(json.dumps(exported), encoding='utf-8')
        return ''
    monkeypatch.setattr(worker, 'cli', cli)
    with pytest.raises(worker_module.WorkerError, match='timeout'):
        worker.download('uid=1_1 button "已生成图像 1"')
    assert not list(worker.root.glob('*.browser-image.json')) and not list(worker.root.glob('*.png'))


def test_disabled_download_control_stops_without_extracting_image(worker, monkeypatch):
    worker.job, worker.page, worker.conversation_url = job(), 9, 'https://chatgpt.com/c/test-123'
    calls = []
    monkeypatch.setattr(worker, 'cli', lambda *args: calls.append(args) or '')
    monkeypatch.setattr(worker, 'snapshot', lambda:'uid=2_1 button "知识图 的文件操作"\nuid=2_2 image "已生成图像 1"\nuid=2_3 button "下载" disableable disabled')
    with pytest.raises(worker_module.WorkerError, match='interaction_required'):
        worker.download('uid=1_1 button "已生成图像 1"')
    assert [command[0] for command in calls] == ['click']
