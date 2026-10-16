"""LearnLoop 优化版 · Windows / Mac 原生运行（不需要 Docker）。

    python3 scripts/mac/native.py [menu|setup|start|stop|status|login-kimi|login-chatgpt|login-claude|image-worker|video-worker]

Everything stays on this Mac: the website listens on localhost only, the text
subscriptions (Kimi Code / ChatGPT) run through the paired local relay, the
ChatGPT web image worker drives your own Chrome, and videos use your own
Claude Code login. Secrets live in files readable only by you (0600).
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import tomllib
import urllib.request
import webbrowser
from pathlib import Path

DEV = Path(__file__).resolve().parents[2]
STATE = DEV.parent / "native" if DEV.parent.name == "runtime" else DEV / ".native"
BACKEND, FRONTEND, SCRIPTS = DEV / "backend", DEV / "frontend", DEV / "scripts"
MAC = SCRIPTS / "mac"
WINDOWS = os.name == "nt"
VENV_PY = BACKEND / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
CONFIG = STATE / "config.json"
ENV_FILE = BACKEND / ".env"
BACKEND_PORT, FRONTEND_PORT = 18010, 18090
SITE = f"http://localhost:{FRONTEND_PORT}"
SERVICES = ("subscriptions", "frontend", "backend", "relay")
if not WINDOWS:
    os.environ["PATH"] = os.pathsep.join(["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local/bin"), os.environ.get("PATH", "")])
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def say(text: str) -> None:
    print(text, flush=True)


def private_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def load_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}


def save_config(data: dict) -> None:
    private_write(CONFIG, json.dumps(data, ensure_ascii=False, indent=2))


def run(args, **kwargs) -> None:
    command = [str(a) for a in args]
    command[0] = shutil.which(command[0]) or command[0]
    subprocess.run(command, check=True, **kwargs)


def node_version() -> tuple[int, ...]:
    node = shutil.which("node")
    if not node:
        raise SystemExit("请先安装 Node.js 22.19 或更高版本（推荐 24 LTS）。")
    raw = subprocess.check_output([node, "--version"], text=True).strip().lstrip("v")
    return tuple(int(part) for part in raw.split(".")[:3])


def env_lines() -> dict[str, str]:
    values = {}
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def merge_env(updates: dict[str, str]) -> None:
    """Add missing keys; never overwrite a value the owner already set."""
    current = env_lines()
    additions = [f"{key}={value}" for key, value in updates.items() if key not in current]
    if additions:
        text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
        private_write(ENV_FILE, text.rstrip("\n") + ("\n" if text else "") + "# --- native local run (generated) ---\n" + "\n".join(additions) + "\n")


# ----------------------------------------------------------------------------- setup
def ask_owner_email() -> None:
    """Ask before the long installs, so nobody waits ten minutes for the only question."""
    cfg = load_config()
    if cfg.get("owner_email"):
        return
    say("\n请输入你（本机唯一拥有者）用来登录网站的邮箱。订阅、一图看懂与视频接入只对这个账号开放。")
    email = input("拥有者邮箱：").strip().lower()
    if "@" not in email:
        raise SystemExit("邮箱格式不正确，请重新运行安装。")
    cfg["owner_email"] = email
    save_config(cfg)


def setup() -> None:
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.chmod(0o700)
    if node_version() < (22, 19, 0):
        raise SystemExit("需要 Node.js 22.19 或更高版本。")
    ask_owner_email()
    if not VENV_PY.exists():
        say("① 创建 Python 环境…")
        uv = shutil.which("uv")
        if uv:
            run([uv, "venv", "--python", "3.12", BACKEND / ".venv"])
        else:
            run([sys.executable, "-m", "venv", BACKEND / ".venv"])
    say("② 安装后端依赖（首次约 3~6 分钟）…")
    uv = shutil.which("uv")
    if uv:
        run([uv, "pip", "install", "--python", VENV_PY, "-r", BACKEND / "requirements.txt"], env={**os.environ, "UV_HTTP_TIMEOUT": "120"})
    else:
        run([VENV_PY, "-m", "pip", "install", "-r", BACKEND / "requirements.txt"])
    say("③ 安装前端依赖并构建网站（首次约 2~4 分钟）…")
    lock = hashlib.sha256((FRONTEND / "package-lock.json").read_bytes()).hexdigest()
    marker = FRONTEND / "node_modules" / ".learnloop-lock"
    if not marker.exists() or marker.read_text() != lock:
        run(["npm", "ci", "--no-audit", "--no-fund"], cwd=FRONTEND)
        marker.write_text(lock)
    build_frontend(force=True)
    say("④ 安装本机接入工具（Kimi Code、Chrome 接入、讲解视频制作工具）…")
    install_tool("kimi-cli", MAC / "kimi-cli.package.json")
    install_tool("image-worker", MAC / "image-worker.package.json")
    install_video_tools()
    configure()
    say("\n✅ 安装完成。接下来：先“启动网站”，用你填写的邮箱注册账号，再分别登录 Kimi / ChatGPT / Claude。")


def install_video_tools() -> None:
    """HyperFrames + ffmpeg + GSAP for Claude videos, and edge-tts for the Chinese narration."""
    install_tool("video-tools", MAC / "video-tools.package.json")
    uv = shutil.which("uv")
    requirements = MAC / "video-worker.requirements.txt"
    if uv:
        run([uv, "pip", "install", "--python", VENV_PY, "-r", requirements], env={**os.environ, "UV_HTTP_TIMEOUT": "120"})
    else:
        run([VENV_PY, "-m", "pip", "install", "-r", requirements])
    run([VENV_PY, SCRIPTS / "claude_video_worker.py", "setup", "--tools", STATE / "video-tools"])


def install_tool(name: str, package_json: Path) -> Path:
    target = STATE / name
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(package_json, target / "package.json")
    run(["npm", "install", "--prefix", target, "--no-audit", "--no-fund"])
    return target


def build_frontend(force: bool = False) -> None:
    stamp = FRONTEND / ".next" / "learnloop-build-stamp"
    digest = hashlib.sha256()
    sources = [p for name in ("app", "components", "lib", "scripts") for p in (FRONTEND / name).rglob("*") if p.is_file()]
    sources += [p for p in FRONTEND.iterdir() if p.is_file() and p.suffix in {".json", ".mjs", ".ts"} and p.name != "next-env.d.ts"]
    for path in sorted(sources):
        digest.update(path.relative_to(FRONTEND).as_posix().encode())
        digest.update(path.read_bytes())
    wanted = sys.platform + ":" + digest.hexdigest()
    standalone = FRONTEND / ".next" / "standalone"
    artifact = FRONTEND / ".next" / "BUILD_ID" if WINDOWS else standalone / "server.js"
    if not force and stamp.exists() and stamp.read_text() == wanted and artifact.exists():
        return
    run(["npm", "run", "build"], cwd=FRONTEND, env={**os.environ, "NEXT_TELEMETRY_DISABLED": "1"})
    if WINDOWS:
        # next start uses the native dependency tree; no privileged symlinks needed.
        stamp.write_text(wanted)
        return
    # The standalone server serves static assets and /public from its own folder.
    for link, source in ((standalone / "public", FRONTEND / "public"), (standalone / ".next" / "static", FRONTEND / ".next" / "static")):
        if link.is_symlink() or link.exists():
            if link.is_symlink():
                link.unlink()
            else:
                shutil.rmtree(link)
        link.symlink_to(source, target_is_directory=True)
    stamp.write_text(wanted)


def configure() -> None:
    ask_owner_email()
    cfg = load_config()
    cfg.setdefault("relay_token", secrets.token_urlsafe(48))
    cfg.setdefault("image_worker_token", secrets.token_urlsafe(48))
    cfg.setdefault("video_worker_token", secrets.token_urlsafe(48))
    cfg.setdefault("chatgpt_model", "gpt-6.1-sol")
    cfg.setdefault("kimi_model", "kimi-code/k3")
    save_config(cfg)
    (STATE / "data").mkdir(parents=True, exist_ok=True, mode=0o700)
    merge_env({
        "AUTH_SECRET": (BACKEND / ".auth_secret").read_text().strip() if (BACKEND / ".auth_secret").exists() else secrets.token_urlsafe(48),
        "AUTH_REQUIRED": "true",
        "DEMO_MODE": "false",
        "DATABASE_URL": f"sqlite:///{(BACKEND / 'sparklearn.db' if (BACKEND / 'sparklearn.db').exists() else STATE / 'data' / 'learnloop.db').as_posix()}",
        "GENERATION_JOBS_ENABLED": "true",
        "GENERATION_WORKER_MODE": "embedded",
        "GENERATION_MAX_RUNNING": "2",
        "FRONTEND_ORIGIN": SITE,
        "TRACE_ENABLED": "false",
        "LEARNLOOP_OWNER_EMAIL": cfg["owner_email"],
        "PORTABLE_TEXT_MODE": "subscription",
        "PORTABLE_DEFAULT_MODEL": "kimi-subscription",
        "PORTABLE_RELAY_TOKEN": cfg["relay_token"],
        "PERSONAL_RELAY_URL": "http://127.0.0.1:18431",
        "PERSONAL_CHAT_IMAGE_ENABLED": "true",
        "PERSONAL_CHAT_IMAGE_WORKER_TOKEN_SHA256": hashlib.sha256(cfg["image_worker_token"].encode()).hexdigest(),
        "CLAUDE_VIDEO_ENABLED": "true",
        "CLAUDE_VIDEO_WORKER_TOKEN_SHA256": hashlib.sha256(cfg["video_worker_token"].encode()).hexdigest(),
    })
    write_worker_configs(cfg)


def write_worker_configs(cfg: dict) -> None:
    private_write(STATE / "subscription-worker.json", json.dumps({
        "relay_url": "http://127.0.0.1:18431", "relay_token": cfg["relay_token"],
        "state_dir": str(STATE / "subscription-state"), "chatgpt_auth_path": str(STATE / "auth" / "chatgpt.json"),
        "chatgpt_model": cfg["chatgpt_model"], "kimi_model": cfg["kimi_model"], "kimi_home": cfg.get("kimi_home", str(STATE / "kimi-home")),
        "kimi_executable": cfg.get("kimi_executable", str(STATE / "kimi-cli" / "node_modules" / ".bin" / ("kimi.cmd" if WINDOWS else "kimi")))}, indent=2))
    downloads = Path.home() / "Downloads"
    downloads.mkdir(exist_ok=True)
    private_write(STATE / "image-worker.json", json.dumps({
        "site_url": SITE, "worker_token": cfg["image_worker_token"], "node_path": shutil.which("node") or "node",
        "cli_path": str(STATE / "image-worker" / "node_modules" / "chrome-devtools-mcp" / "build" / "src" / "bin" / "chrome-devtools.js"),
        "downloads_dir": str(downloads), "state_dir": str(STATE / "image-state"), "site_connection": "direct"}, indent=2))


# ----------------------------------------------------------------------------- processes
def pid_file(name: str) -> Path:
    return STATE / "pids" / f"{name}.pid"


def windows_process_stamp(pid: int) -> str | None:
    """Read process creation time without sending Windows' destructive signal 0."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        exit_code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) or exit_code.value != 259:
            return None
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


def alive(name: str) -> bool:
    try:
        pid = int(pid_file(name).read_text())
        if WINDOWS:
            saved = json.loads(pid_file(name).with_suffix(".json").read_text())
            stamp = windows_process_stamp(pid)
            return stamp is not None and saved.get("created") == stamp and saved.get("pid") == pid
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def spawn(name: str, args, cwd: Path, extra_env: dict | None = None) -> None:
    if alive(name):
        return
    (STATE / "logs").mkdir(parents=True, exist_ok=True, mode=0o700)
    (STATE / "pids").mkdir(parents=True, exist_ok=True, mode=0o700)
    command = [str(a) for a in args]
    command[0] = shutil.which(command[0]) or command[0]
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {"start_new_session": True}
    with open(STATE / "logs" / f"{name}.log", "ab") as log:
        process = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, env={**os.environ, **(extra_env or {})}, **flags)
    pid_file(name).write_text(str(process.pid))
    if WINDOWS:
        private_write(pid_file(name).with_suffix(".json"), json.dumps({"pid": process.pid, "created": windows_process_stamp(process.pid)}))


@contextmanager
def launcher_lock():
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "launcher.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if WINDOWS:
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit("另一个启动或停止操作正在进行，请等它完成后再试。") from None
        yield


def require_free_port(name: str, port: int) -> None:
    if alive(name):
        return
    with socket.socket() as connection:
        connection.settimeout(1)
        if connection.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(f"端口 {port} 已被其他程序占用，未停止该程序。请关闭占用程序后重试。")


def wait_http(url: str, seconds: int) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with opener.open(url, timeout=5) as response:
                if response.status < 500:
                    return True
        except Exception:
            time.sleep(2)
    return False


def start() -> None:
    cfg = load_config()
    if not VENV_PY.exists() or not cfg:
        raise SystemExit("请先运行“首次安装”。")
    build_frontend()
    write_worker_configs(cfg)
    for name, port in (("relay", 18431), ("backend", BACKEND_PORT), ("frontend", FRONTEND_PORT)):
        require_free_port(name, port)
    spawn("relay", [VENV_PY, MAC / "relay.py"], MAC, {"PORTABLE_RELAY_TOKEN": cfg["relay_token"], "RELAY_HOST": "127.0.0.1"})
    spawn("backend", [VENV_PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", BACKEND_PORT], BACKEND)
    frontend_command = ["node", FRONTEND / "node_modules" / "next" / "dist" / "bin" / "next", "start", "--hostname", "127.0.0.1", "--port", FRONTEND_PORT] if WINDOWS else ["node", "server.js"]
    spawn("frontend", frontend_command, FRONTEND if WINDOWS else FRONTEND / ".next" / "standalone",
          {"PORT": str(FRONTEND_PORT), "HOSTNAME": "127.0.0.1", "BACKEND_URL": f"http://127.0.0.1:{BACKEND_PORT}", "NODE_ENV": "production"})
    (STATE / "subscription-state" / "subscriptions.stop").unlink(missing_ok=True)
    spawn("subscriptions", [VENV_PY, MAC / "subscription_worker.py", "--config", STATE / "subscription-worker.json"], MAC)
    say("正在启动网站（首次启动需要加载检索模型，约 30~90 秒）…")
    if not wait_http(f"http://127.0.0.1:{BACKEND_PORT}/api/health", 180):
        raise SystemExit(f"后端没有按时启动，请查看日志：{STATE / 'logs' / 'backend.log'}")
    if not wait_http(f"http://127.0.0.1:{FRONTEND_PORT}/", 60):
        raise SystemExit(f"网站没有按时启动，请查看日志：{STATE / 'logs' / 'frontend.log'}")
    status()
    if os.environ.get("LEARNLOOP_NO_BROWSER") != "1":
        webbrowser.open(SITE)


def stop() -> None:
    for path in (STATE / "subscription-state" / "subscriptions.stop", STATE / "image-state" / "stop.requested",
                 STATE / "video-state" / "stop.requested"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    failures = []
    for name in SERVICES:
        try:
            pid = int(pid_file(name).read_text())
            if WINDOWS:
                if alive(name):
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=20)
                    deadline = time.monotonic() + 5
                    while alive(name) and time.monotonic() < deadline:
                        time.sleep(0.1)
                    if alive(name):
                        failures.append(name)
                        continue
            else:
                os.killpg(pid, signal.SIGTERM)
        except subprocess.TimeoutExpired:
            if alive(name):
                failures.append(name)
                continue
        except (OSError, ValueError):
            if alive(name):
                failures.append(name)
                continue
        pid_file(name).unlink(missing_ok=True)
        pid_file(name).with_suffix(".json").unlink(missing_ok=True)
    if failures:
        raise SystemExit("以下程序未停止，已保留进程记录供重试：" + "、".join(failures))
    say("已停止网站与接入程序；数据库与生成的内容都保留。")


def logins() -> dict[str, bool]:
    cfg = load_config()
    kimi = (Path(cfg.get("kimi_home", str(STATE / "kimi-home"))) / "credentials" / "kimi-code.json").exists()
    chatgpt = (STATE / "auth" / "chatgpt.json").exists() and "access_token" in (STATE / "auth" / "chatgpt.json").read_text()
    return {"Kimi Code 订阅": kimi, "ChatGPT/Codex 订阅": chatgpt, "Claude Code（讲解视频）": claude_signed_in()}


def status() -> None:
    say("\n—— LearnLoop 优化版运行状态 ——")
    for name, label in (("backend", "后端"), ("frontend", "网站"), ("relay", "订阅中继"), ("subscriptions", "订阅接入")):
        say(f"{label}：{'运行中' if alive(name) else '未运行'}")
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open("http://127.0.0.1:18431/health", timeout=4) as response:
            connected = json.load(response).get("worker_connected")
        say(f"文字模型接入：{'已连接' if connected else '中继在线，接入程序未连接'}")
    except Exception:
        say("文字模型接入：中继未运行")
    for label, ok in logins().items():
        say(f"{label}：{'已就绪' if ok else '未登录/未安装'}")
    say(f"网站地址：{SITE}（只在本机可访问）\n")


# ----------------------------------------------------------------------------- logins
def login_kimi() -> None:
    cfg = load_config()
    exe = Path(cfg.get("kimi_executable", str(STATE / "kimi-cli" / "node_modules" / ".bin" / ("kimi.cmd" if WINDOWS else "kimi"))))
    if not exe.exists():
        install_tool("kimi-cli", MAC / "kimi-cli.package.json")
    home = Path(cfg.get("kimi_home", str(STATE / "kimi-home")))
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    run([exe, "login"], env={**os.environ, "KIMI_CODE_HOME": str(home), "KIMI_CODE_EXPERIMENTAL_FLAG": "1"})
    settings = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    candidates = [key for key, value in settings.get("models", {}).items() if value.get("provider") == "managed:kimi-code"]
    model = settings.get("default_model") if settings.get("default_model") in candidates else (candidates[0] if candidates else "")
    if not model:
        raise SystemExit("没有找到 Kimi Code 订阅模型，请确认登录的是订阅账号。")
    cfg["kimi_model"] = model
    save_config(cfg)
    write_worker_configs(cfg)
    say(f"Kimi Code 订阅登录完成（模型 {model}）。重新“启动网站”后生效。")


def login_chatgpt() -> None:
    sys.path.insert(0, str(MAC))
    import chatgpt_auth  # noqa: E402  (local module)
    cfg = load_config()
    models = chatgpt_auth.login(STATE / "auth" / "chatgpt.json")
    if cfg.get("chatgpt_model") not in models:
        cfg["chatgpt_model"] = models[0]
    save_config(cfg)
    write_worker_configs(cfg)
    say("ChatGPT 订阅登录完成。一图看懂还需要在 Chrome 里登录同一个 ChatGPT 账号。")


def claude_executable() -> str:
    local = STATE / "claude-cli" / "node_modules" / ".bin" / ("claude.cmd" if WINDOWS else "claude")
    return str(local) if local.exists() else (shutil.which("claude") or "")


def claude_signed_in() -> bool:
    exe = claude_executable()
    if not exe:
        return False
    try:
        return subprocess.run([exe, "auth", "status"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def login_claude() -> None:
    exe = claude_executable()
    if not exe:
        say("正在安装官方 Claude Code（只装在本项目目录里）…")
        target = STATE / "claude-cli"
        target.mkdir(parents=True, exist_ok=True)
        (target / "package.json").write_text(json.dumps({"private": True, "dependencies": {"@anthropic-ai/claude-code": "latest"}}))
        run(["npm", "install", "--prefix", target, "--no-audit", "--no-fund"])
        exe = claude_executable()
    if claude_signed_in():
        say("官方 Claude Code 已登录，可以直接“启动讲解视频接入”。")
        return
    say("接下来由官方 Claude Code 打开浏览器登录页：请选择你的 Claude 订阅账号（Pro / Max）并完成授权。")
    say("（LearnLoop 不读取、不保存任何 Claude 凭据；制作视频时只调用你已登录的官方 claude 命令。）")
    subprocess.run([exe, "auth", "login"], cwd=str(STATE))
    say("Claude 登录完成。" if claude_signed_in() else "还没有检测到登录，可以重新选择“登录 Claude”。")


# ----------------------------------------------------------------------------- workers
def image_worker() -> None:
    cfg = load_config()
    if not (STATE / "image-worker" / "node_modules").exists():
        install_tool("image-worker", MAC / "image-worker.package.json")
    write_worker_configs(cfg)
    say("请在 Chrome 打开 chatgpt.com 并登录你自己的 ChatGPT 账号；")
    say("然后在 chrome://inspect/#remote-debugging 允许远程调试，并接受 Chrome 的连接提示。保持此窗口运行。")
    args = [VENV_PY, SCRIPTS / "personal_chat_image_worker.py", "--config", STATE / "image-worker.json"]
    run(args + ["--check-browser"])
    run(args)


def video_worker() -> None:
    cfg = load_config()
    if not cfg:
        raise SystemExit("请先运行“首次安装”。")
    exe = claude_executable()
    if not exe:
        raise SystemExit("请先运行“登录 Claude”。")
    if not cfg.get("video_worker_token") or "CLAUDE_VIDEO_WORKER_TOKEN_SHA256" not in env_lines():
        configure()  # Older installs: add the video pairing secret, then the website must reload .env.
        say("已开启讲解视频接入。请先“停止网站与接入”再“启动网站”，然后重新选择本项。")
        return
    if not (STATE / "video-tools" / "bin" / "learnloop-check").exists():
        say("正在安装讲解视频制作工具（HyperFrames、ffmpeg、中文配音，首次约 1~3 分钟）…")
        install_video_tools()
    say("讲解视频由你本机已登录的官方 Claude Code 制作；在网页“设置 → 讲解视频”里可以选模型、思考强度、配音和时长。")
    say("保持此窗口运行；网页上生成“讲解视频”时会自动开始制作。")
    run([VENV_PY, SCRIPTS / "claude_video_worker.py", "run", "--site", f"http://127.0.0.1:{BACKEND_PORT}",
         "--state", STATE / "video-state", "--tools", STATE / "video-tools", "--claude", exe, "--token-file", CONFIG])


ACTIONS = {"setup": setup, "start": start, "stop": stop, "status": status, "login-kimi": login_kimi,
           "login-chatgpt": login_chatgpt, "login-claude": login_claude, "image-worker": image_worker,
           "video-worker": video_worker}
MENU = [("首次安装 / 修复安装", "setup"), ("启动网站（含文字订阅接入）", "start"), ("登录 Kimi Code 订阅", "login-kimi"),
        ("登录 ChatGPT 订阅", "login-chatgpt"), ("登录 Claude（讲解视频）", "login-claude"),
        ("启动一图看懂接入（ChatGPT 网页）", "image-worker"), ("启动讲解视频接入（Claude Code）", "video-worker"),
        ("查看运行状态", "status"), ("停止网站与接入", "stop")]


def menu() -> None:
    say("\n=== 知行循证 LearnLoop · 优化版（本机运行，无需 Docker）===")
    for index, (label, _) in enumerate(MENU, 1):
        say(f"  {index}. {label}")
    choice = input("请输入序号：").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(MENU):
        raise SystemExit("没有这个选项。")
    dispatch(MENU[int(choice) - 1][1])


def dispatch(action: str) -> None:
    if action in {"start", "stop", "setup"}:
        with launcher_lock():
            ACTIONS[action]()
    else:
        ACTIONS[action]()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default="menu", choices=["menu", *ACTIONS])
    action = parser.parse_args().action
    try:
        menu() if action == "menu" else dispatch(action)
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"步骤未完成（退出码 {error.returncode}）。数据没有被重置，请保留窗口内容排查。") from None
    except KeyboardInterrupt:
        say("已取消。")


if __name__ == "__main__":
    main()
