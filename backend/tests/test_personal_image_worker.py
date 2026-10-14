import importlib.util
import json
import sys
import time
import threading
from pathlib import Path
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
    assert json.loads((worker.root/'active.json').read_text())['completed'] is True


def test_download_uses_matching_frame_guid_and_exact_completed_path(worker, tmp_path):
    target=tmp_path/'expected.png'
    target.write_bytes(b'test')
    unrelated=tmp_path/'same-title.png'
    unrelated.write_bytes(b'wrong')
    def event(method, **params): return json.dumps({"method":'Browser.'+method,"params":params})
    events=iter([
        event('downloadWillBegin', frameId='other',guid='wrong',suggestedFilename='title.png'),
        event('downloadProgress',guid='wrong',state='completed',filePath=str(unrelated)),
        event('downloadWillBegin',frameId='ours',guid='right',suggestedFilename='title.png'),
        event('downloadProgress',guid='right',state='completed',filePath=str(target)),
    ])
    class Socket:
        def settimeout(self, _): pass
        def recv(self): return next(events)
    download=worker_module.ChromeDownload(worker.config,'https://chatgpt.com/c/test','title')
    download.frame, download.socket='ours',Socket()
    assert download.wait(threading.Event()) == target.resolve()
