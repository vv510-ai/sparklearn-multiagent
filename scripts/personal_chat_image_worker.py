"""Explicitly started personal Chat UI worker; uses the official Chrome DevTools CLI.

Run: python scripts/personal_chat_image_worker.py --config .tmp/personal-image/worker.json
No cookies, login tokens, private ChatGPT endpoints, API calls, or automatic startup.
The config contains a LearnLoop-only pairing token, never a ChatGPT credential.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class WorkerError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def validate_config(config):
    address = urllib.parse.urlsplit(config["site_url"])
    if not address.hostname or (address.scheme != "https" and not (address.scheme == "http" and address.hostname in {"localhost", "127.0.0.1"})) or address.username or address.password or address.query or address.fragment or address.path not in {"", "/"}:
        raise ValueError("site_url must be an HTTPS origin or loopback development origin")
    if not 32 <= len(config["worker_token"]) <= 256:
        raise ValueError("invalid pairing token")
    for name in ("node_path", "cli_path"):
        if not Path(config[name]).is_file():
            raise ValueError(f"missing {name}")
    if not Path(config["downloads_dir"]).is_dir():
        raise ValueError("downloads_dir must be the browser's existing Downloads folder")
    config["site_url"] = config["site_url"].rstrip("/")
    return config


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never forward the pairing secret to another origin.


class ChromeDownload:
    """Bind the native download to this Chat frame and its Chrome download GUID."""
    def __init__(self, config, conversation_url, title):
        self.config, self.url, self.title = config, conversation_url, title
        self.socket, self.sequence, self.armed = None, 0, False

    def call(self, method, params=None, session=None):
        self.sequence += 1
        message = {"id": self.sequence, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        self.socket.send(json.dumps(message))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            value = json.loads(self.socket.recv())
            if value.get("id") == self.sequence:
                if "error" in value:
                    raise WorkerError("ui_changed")
                return value.get("result", {})
        raise WorkerError("timeout")

    def __enter__(self):
        import websocket
        profile = Path(self.config.get("chrome_user_data_dir") or
                       Path(os.environ["LOCALAPPDATA"]) / "Google/Chrome/User Data")
        lines = (profile / "DevToolsActivePort").read_text().splitlines()
        if (len(lines) != 2 or not lines[0].isdigit() or not 0 < int(lines[0]) < 65536
                or not re.fullmatch(r"/devtools/browser/[A-Za-z0-9-]+", lines[1])):
            raise WorkerError("ui_changed")
        # Local Chrome protocol only; never read cookies or request ChatGPT backend URLs.
        self.socket = websocket.create_connection(f"ws://127.0.0.1:{lines[0]}{lines[1]}",
                                                   timeout=10, suppress_origin=True)
        try:
            targets = self.call("Target.getTargets")["targetInfos"]
            matches = [t for t in targets if t.get("type") == "page" and t.get("url") == self.url]
            if len(matches) != 1 or not re.fullmatch(r"https://chatgpt.com/c/[A-Za-z0-9-]+", self.url):
                raise WorkerError("ui_changed")
            session = self.call("Target.attachToTarget", {"targetId": matches[0]["targetId"], "flatten": True})["sessionId"]
            self.frame = self.call("Page.getFrameTree", session=session)["frameTree"]["frame"]["id"]
            # Keep the user's native Chrome download location and download restrictions.
            self.call("Browser.setDownloadBehavior", {"behavior": "default", "eventsEnabled": True})
            self.armed = True
            return self
        except BaseException:
            self.socket.close()
            raise

    def wait(self, lost, timeout=60):
        import websocket
        self.socket.settimeout(1)
        guid = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if lost.is_set():
                raise WorkerError("uncertain")
            try:
                event = json.loads(self.socket.recv())
            except websocket.WebSocketTimeoutException:
                continue
            data = event.get("params", {})
            if event.get("method") == "Browser.downloadWillBegin" and data.get("frameId") == self.frame:
                if guid or not re.fullmatch(re.escape(self.title) + r"\.(?:png|jpe?g|webp)", data.get("suggestedFilename", ""), re.I):
                    raise WorkerError("uncertain")
                guid = data["guid"]
            if event.get("method") == "Browser.downloadProgress" and guid and data.get("guid") == guid:
                if data.get("state") == "canceled":
                    raise WorkerError("interaction_required")
                if data.get("state") == "completed":
                    # No filename/mtime fallback: it could belong to another concurrent download.
                    if not data.get("filePath"):
                        raise WorkerError("uncertain")
                    path = Path(data["filePath"]).resolve()
                    if path.parent != Path(self.config["downloads_dir"]).resolve() or not path.is_file():
                        raise WorkerError("uncertain")
                    return path
        raise WorkerError("timeout")

    def __exit__(self, *args):
        try:
            if self.armed:
                self.socket.settimeout(10)
                self.call("Browser.setDownloadBehavior", {"behavior": "default", "eventsEnabled": False})
        finally:
            self.socket.close()  # Detach only; never close the user's Chrome.


class Worker:
    def __init__(self, config):
        self.config = validate_config(config)
        self.root = Path(config["state_dir"]).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.opener = urllib.request.build_opener(NoRedirect)
        self.session = hashlib.sha256(str(self.root).encode()).hexdigest()[:16]
        self.page = None
        self.job = None
        self.sent = False
        self.stop_pulse = threading.Event()
        self.lost = threading.Event()
        self.browser_started = False
        self.keep_browser = False

    def api(self, path, payload=None, *, image=None, mime=None):
        headers = {"Authorization": "Bearer " + self.config["worker_token"]}
        if image is not None:
            data = image
            headers.update({"Content-Type": mime, "X-Image-Lease": self.job["lease"]})
        else:
            data = json.dumps(payload or {}).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.config["site_url"] + "/api/personal-image-worker/" + path,
                                         data=data, headers=headers, method="POST")
        with self.opener.open(request, timeout=35) as response:
            return json.load(response)

    def update(self, action, **extra):
        return self.api(f"{self.job['id']}/{action}", {"lease": self.job["lease"], **extra})

    def cli(self, *args, timeout=55):
        result = subprocess.run([self.config["node_path"], self.config["cli_path"], *map(str, args),
                                 "--sessionId", self.session], shell=False, capture_output=True,
                                encoding="utf-8", errors="replace", timeout=timeout)
        # Keep raw browser output, user data and CLI internals out of application logs.
        if result.returncode or re.search(r"^Error:|^Protocol error", result.stdout, re.M):
            raise WorkerError("ui_changed")
        return result.stdout

    def snapshot(self):
        if (self.root / "stop.requested").exists():
            raise WorkerError("cancelled")
        if self.lost.is_set():
            raise WorkerError("uncertain")
        value = self.cli("take_snapshot", self.page)
        root = re.search(r'RootWebArea .*url="([^\"]+)"', value)
        if not root or not root[1].startswith("https://chatgpt.com/"):
            raise WorkerError("login_required")
        return value

    @staticmethod
    def elements(snapshot, role, pattern):
        matches = re.findall(r'^\s*uid=(\S+) ' + re.escape(role) + r' "([^"\n]*)"([^\n]*)', snapshot, re.M)
        return [(uid, label, flags) for uid, label, flags in matches if re.fullmatch(pattern, label)]

    def one(self, snapshot, role, pattern):
        matches = self.elements(snapshot, role, pattern)
        if len(matches) != 1:
            raise WorkerError("ui_changed")
        return matches[0][0]

    def click(self, uid):
        self.cli("click", self.page, uid)

    def journal(self, **fields):
        path = self.root / "active.json"
        data = {"job_id": self.job["id"], "lease": self.job["lease"], "submitted": self.sent, **fields}
        temporary = path.with_suffix(".part")
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def heartbeat(self, job, stop, lost):
        while not stop.wait(20):
            try:
                self.api(f"{job['id']}/heartbeat", {"lease": job["lease"]})
            except Exception:
                if not stop.is_set():
                    lost.set()
                return

    def connect(self):
        if not self.browser_started:
            self.cli("start", "--autoConnect", "--channel", "stable", "--headless=false",
                     "--no-usageStatistics", "--no-performanceCrux", "--redactNetworkHeaders",
                     "--categoryExtensions=false", "--categoryNetwork=false", "--categoryPerformance=false",
                     "--allowUnrestrictedPaths=false", "--workspace", self.root)
            self.browser_started = True
        result = self.cli("new_page", "https://chatgpt.com/", "--timeout", "45000", "--output-format=json")
        payload = next((json.loads(line) for line in reversed(result.splitlines())
                        if line.startswith('{') and '"pages"' in line), {})
        matches = [page["id"] for page in payload.get("pages", [])
                   if page.get("selected") and page.get("url", "").startswith("https://chatgpt.com/")]
        if len(matches) != 1:
            raise WorkerError("ui_changed")
        self.page = matches[0]
        deadline = time.time() + 45
        while time.time() < deadline:
            snapshot = self.snapshot()
            if self.elements(snapshot, "button", "登录|Log in|Sign in"):
                raise WorkerError("login_required")
            chat = self.elements(snapshot, "button", "Chat|聊天")
            if len(chat) == 1 and "disabled" not in chat[0][2]:
                break
            time.sleep(1)
        else:
            raise WorkerError("ui_changed")
        if "pressed" not in chat[0][2]:
            self.click(chat[0][0])
            snapshot = self.snapshot()
        chat = self.elements(snapshot, "button", "Chat|聊天")
        if len(chat) != 1 or "pressed" not in chat[0][2]:
            raise WorkerError("ui_changed")
        return snapshot

    def disconnect(self):
        try:
            self.cli("stop")
            self.browser_started = False
        except Exception:
            print("未能确认浏览器连接已断开，接入程序已停止，请检查专用 CLI 连接。", flush=True)
            raise WorkerError("disconnect_failed") from None

    def download(self, snapshot):
        self.click(self.one(snapshot, "button", r"已生成图像 1|Generated image 1"))
        for _ in range(12):
            snapshot = self.snapshot()
            names = self.elements(snapshot, "button", r".+ 的文件操作|File actions for .+")
            if names:
                break
            time.sleep(1)
        if len(names) != 1:
            raise WorkerError("ui_changed")
        title = re.sub(r" 的文件操作$|^File actions for ", "", names[0][1]).strip()
        if not title or re.search(r'[<>:"/\\|?*]', title):
            raise WorkerError("ui_changed")
        with ChromeDownload(self.config, self.conversation_url, title) as download:
            self.click(self.one(snapshot, "button", "下载|Download"))
            source = download.wait(self.lost)
        if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or not 0 < source.stat().st_size <= 20 * 1024 * 1024:
            raise WorkerError("worker_error")
        from PIL import Image
        with Image.open(source) as image:
            image.verify()
        target = self.root / (self.job["id"] + source.suffix.lower())
        shutil.copy2(source, target)
        return target

    def check_time(self, job):
        if (self.root / "stop.requested").exists():
            raise WorkerError("cancelled")
        if job["expires_at"] - time.time() < 150:
            raise WorkerError("timeout")
        if self.lost.is_set():
            raise WorkerError("uncertain")

    def run_job(self, job):
        if (not re.fullmatch(r"[a-f0-9]{64}", str(job.get("id", "")))
                or not re.fullmatch(r"[a-f0-9]{48}", str(job.get("lease", "")))
                or not isinstance(job.get("prompt"), str) or not 0 < len(job["prompt"]) <= 14000
                or not isinstance(job.get("expires_at"), (int, float))
                or not time.time() < job["expires_at"] <= time.time() + 1205):
            raise WorkerError("worker_error")
        self.job, self.sent = job, False
        # An old in-flight heartbeat cannot affect this job or adopt its new lease.
        self.stop_pulse, self.lost = threading.Event(), threading.Event()
        pulse = threading.Thread(target=self.heartbeat, args=(dict(job), self.stop_pulse, self.lost), daemon=True)
        pulse.start()
        self.journal()
        try:
            self.check_time(job)
            snapshot = self.connect()
            self.check_time(job)
            editor = self.one(snapshot, "textbox", "询问 ChatGPT|Ask ChatGPT|Message ChatGPT")
            self.cli("fill", self.page, editor, job["prompt"])
            for _ in range(15):
                snapshot = self.snapshot()
                sends = self.elements(snapshot, "button", "发送|发送消息|Send|Send message|发送提示")
                if len(sends) == 1 and "disabled" not in sends[0][2]:
                    send = sends[0][0]
                    break
                self.check_time(job)
                time.sleep(1)
            else:
                raise WorkerError("ui_changed")
            self.check_time(job)
            self.update("submitted")  # Commit the fence before touching the send button.
            self.check_time(job)
            self.sent = True
            self.journal()
            self.click(send)  # Exactly once; never retry this action.
            deadline = min(job["expires_at"] - 30, time.time() + 900)
            stable_image = False
            while time.time() < deadline:
                snapshot = self.snapshot()
                root = re.search(r'RootWebArea .*url="(https://chatgpt.com/c/[A-Za-z0-9-]+)"', snapshot)
                if root:
                    self.conversation_url = root[1]
                    self.journal(conversation_url=self.conversation_url)
                if self.elements(snapshot, "button", "登录|Log in|Sign in"):
                    raise WorkerError("login_required")
                if self.elements(snapshot, "button", "验证|Verify|重新生成|Regenerate|重试|Retry"):
                    raise WorkerError("interaction_required")
                images = self.elements(snapshot, "button", r"已生成图像 1|Generated image 1")
                busy = self.elements(snapshot, "button", r"停止|停止生成|Stop|Stop generating")
                ready = len(images) == 1 and "disabled" not in images[0][2] and not busy and bool(root)
                if ready and stable_image:
                    path = self.download(snapshot)
                    data = path.read_bytes()
                    self.journal(download=str(path), sha256=hashlib.sha256(data).hexdigest())
                    for attempt in range(3):
                        try:
                            result = self.api(f"{job['id']}/complete", image=data,
                                              mime=mimetypes.guess_type(path.name)[0])
                            if result.get("sha256") != hashlib.sha256(data).hexdigest():
                                raise WorkerError("worker_error")
                            self.journal(completed=True, download=str(path), sha256=result["sha256"])
                            print("图片已自动回传并保存；网站将继续内容核验。", flush=True)
                            return
                        except (urllib.error.URLError, TimeoutError):
                            if attempt == 2:
                                raise WorkerError("uncertain") from None
                            time.sleep(2)
                # Live-region 'Response complete' may be stale while a new image is loading.
                stable_image = ready
                time.sleep(4)
            raise WorkerError("timeout")
        except BaseException as error:
            code = error.code if isinstance(error, WorkerError) else "uncertain" if self.sent else "worker_error"
            try:
                self.update("fail", code=code)
            except Exception:
                pass
            self.journal(failed=code)
            print(f"图片任务已暂停：{code}。不会自动重复发送。", flush=True)
            raise
        finally:
            self.stop_pulse.set()
            pulse.join(timeout=2)
            if not self.keep_browser:
                self.disconnect()


@contextmanager
def single_instance(root):
    with (root / "worker.lock").open("a+b") as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--once", action="store_true", help="Process one task, then disconnect and exit")
    parser.add_argument("--check-browser", action="store_true", help="Check a new Chat tab, send nothing, then disconnect")
    parser.add_argument("--stop", action="store_true", help="Ask this paired worker to disconnect and stop")
    args = parser.parse_args()
    worker = Worker(json.loads(args.config.read_text(encoding="utf-8-sig")))
    if args.stop:
        (worker.root / "stop.requested").touch()
        print("已请求停止；接入程序会结束当前等待并断开浏览器。", flush=True)
        return
    with single_instance(worker.root):
        (worker.root / "stop.requested").unlink(missing_ok=True)
        run(worker, args)


def run(worker, args):
    if args.check_browser:
        try:
            worker.connect()
            print("已确认普通 Chat 登录页面；未发送请求。", flush=True)
        finally:
            worker.cli("stop")
        return
    print("个人 Chat 图片接入程序运行中；仅处理配对账号，按 Ctrl+C 停止。", flush=True)
    worker.keep_browser = not args.once
    try:
        while True:
            if (worker.root / "stop.requested").exists():
                return
            try:
                job = worker.api("claim").get("job")
                if job:
                    worker.run_job(job)
                    if args.once:
                        return
            except KeyboardInterrupt:
                return
            except Exception:
                # A new login, permission or interface problem requires human attention.
                print("接入已停止，请检查网站连接与本机 ChatGPT 页面后重新启动。", flush=True)
                raise SystemExit(1) from None
            time.sleep(5)
    finally:
        if worker.browser_started:
            worker.disconnect()


if __name__ == "__main__":
    main()
