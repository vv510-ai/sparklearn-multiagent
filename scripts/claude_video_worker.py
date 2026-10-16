"""LearnLoop · Claude 讲解视频接入程序（在拥有者自己的 Mac 上运行）。

    python scripts/claude_video_worker.py setup  --tools DIR
    python scripts/claude_video_worker.py run    --site URL --state DIR --tools DIR --claude PATH --token-file CONFIG
    python scripts/claude_video_worker.py check  VIDEO [--expect SECONDS]
    python scripts/claude_video_worker.py doctor --tools DIR --claude PATH

The worker claims video jobs from the local LearnLoop backend and produces them
with the official Claude Code CLI that the owner signed in to. It never reads,
stores or forwards Claude credentials. An optional Console API key arrives from
the owner's own backend and is only placed in the CLI's environment for one run.

Per job: Claude writes ``storyboard.json`` → the worker records the Chinese
narration (edge-tts, macOS ``say`` as fallback) and times every scene → Claude
builds the HyperFrames composition, snapshots and fixes it, renders the MP4 →
the worker validates it with ffprobe, adds a poster and uploads both.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

PINNED_SKILLS_CLI = "skills@1.7.2"
SKILLS_SOURCE = "heygen-com/hyperframes"
# Domain knowledge only; the request-routing workflows ask the user questions.
SKILLS = ("hyperframes", "hyperframes-core", "hyperframes-animation", "hyperframes-creative",
          "hyperframes-cli", "hyperframes-keyframes", "hyperframes-audio")
GUIDES = {"visual-design.md": "faceless-explainer/references/visual-design.md",
          "motion-language.md": "faceless-explainer/references/motion-language.md",
          "story-design.md": "faceless-explainer/references/story-design.md"}
HYPERFRAMES_BLOCKED = ("publish", "cloud", "lambda", "cloudrun", "auth", "preview", "present", "open", "catch-up",
                       "feedback", "upgrade", "skills", "telemetry", "add", "catalog", "capture", "tts", "transcribe",
                       "models", "remove-background", "history")
ALLOW = ["Edit(./**)", "Skill", "Bash(hyperframes *)", "Bash(npx hyperframes *)", "Bash(ffmpeg *)", "Bash(ffprobe *)",
         "Bash(learnloop-check *)", "Bash(learnloop-check)", "Bash(mkdir *)", "Bash(cp *)", "Bash(mv *)", "Bash(touch *)"]
DENY = ["WebFetch", "WebSearch"] + [f"Bash({prefix}hyperframes {name}{tail})" for prefix in ("", "npx ")
                                    for name in HYPERFRAMES_BLOCKED for tail in ("", " *")]
STORYBOARD = {"turns": 40, "timeout": 20 * 60}
PRODUCTION = {"turns": 240, "timeout": 85 * 60}
REPAIR = {"turns": 80, "timeout": 30 * 60}
HEARTBEAT_SECONDS = 20
HELLO_SECONDS = 45
KEEP_WORKSPACES = 6
LEAD_IN, SCENE_GAP, TAIL = 0.3, 0.45, 1.6
FALLBACK_VOICE = "Tingting"
# ASCII "," "." ":" also appear inside numbers and times, so they never end a subtitle line.
CLAUSE_END = "，。！？；：!?;"
LOGIN_ERRORS = {"authentication_failed", "oauth_org_not_allowed", "account_on_hold"}
LIMIT_ERRORS = {"rate_limit", "billing_error"}


class WorkerError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code, self.detail = code, detail


class Cancelled(Exception):
    pass


def say(text: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + text, flush=True)


def clean_detail(text: str, limit: int = 180) -> str:
    """Short, path-free diagnostics for the learner-facing error."""
    text = str(text or "").replace(str(Path.home()), "~")
    text = re.sub(r"(sk-ant-[A-Za-z0-9_-]{4})[A-Za-z0-9_-]+", r"\1…", text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


# ----------------------------------------------------------------------------- tools
def arch() -> str:
    return "arm64" if platform.machine() in {"arm64", "aarch64"} else "x64"


def tool_paths(tools: Path) -> dict[str, Path]:
    modules = tools / "node_modules"
    return {"bin": tools / "bin", "node_bin": modules / ".bin",
            "ffmpeg": modules / "ffmpeg-static" / "ffmpeg",
            "ffprobe": modules / "ffprobe-static" / "bin" / "darwin" / arch() / "ffprobe",
            "gsap": modules / "gsap" / "dist" / "gsap.min.js",
            "three": modules / "three" / "build" / "three.module.min.js",
            "skills": tools / "skills" / ".claude" / "skills", "guides": tools / "guides"}


def tool_env(tools: Path, api_key: str = "", *, offline: bool = True) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}}
    paths = tool_paths(tools)
    env["PATH"] = os.pathsep.join([str(paths["bin"]), str(paths["node_bin"]), env.get("PATH", "")])
    env.update({"HYPERFRAMES_SKIP_SKILLS": "1", "NO_UPDATE_NOTIFIER": "1", "npm_config_update_notifier": "false",
                "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
    if offline:
        # npx must resolve the pinned local HyperFrames, never download another version mid-job.
        env["npm_config_offline"] = "true"
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
    return env


def run_quiet(args, *, cwd=None, env=None, timeout=120) -> subprocess.CompletedProcess:
    return subprocess.run([str(a) for a in args], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def setup(tools: Path) -> None:
    """Finish the npm-installed toolchain: binaries, wrappers, skills, guides."""
    paths = tool_paths(tools)
    if not (tools / "node_modules" / "hyperframes").exists():
        raise SystemExit("视频工具还没有安装：请先运行启动菜单里的“首次安装 / 修复安装”。")
    if not paths["ffmpeg"].exists():
        run_quiet(["node", "install.js"], cwd=tools / "node_modules" / "ffmpeg-static", timeout=600)
    if not paths["ffmpeg"].exists():
        raise SystemExit("ffmpeg 下载失败，请检查网络后重试。")
    paths["ffprobe"].chmod(0o755)
    paths["bin"].mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        link = paths["bin"] / name
        link.unlink(missing_ok=True)
        link.symlink_to(paths[name])
    wrapper = paths["bin"] / "learnloop-check"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{Path(__file__).resolve()}" check "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    env = tool_env(tools, offline=False)
    if not (paths["skills"] / "hyperframes-core").exists():
        say("正在下载 HyperFrames 制作技能（约 18 MB）…")
        target = tools / "skills"
        target.mkdir(parents=True, exist_ok=True)
        done = run_quiet(["npx", "--yes", PINNED_SKILLS_CLI, "add", SKILLS_SOURCE, "--skill", "*", "-a", "claude-code",
                          "-y", "--copy"], cwd=target, env=env, timeout=900)
        if not (paths["skills"] / "hyperframes-core").exists():
            raise SystemExit("HyperFrames 技能下载失败：" + clean_detail(done.stderr or done.stdout))
    paths["guides"].mkdir(parents=True, exist_ok=True)
    for name, source in GUIDES.items():
        if (paths["skills"] / source).exists():
            shutil.copy2(paths["skills"] / source, paths["guides"] / name)
    run_quiet(["hyperframes", "telemetry", "disable"], env=env, timeout=60)
    say("视频制作工具已就绪。")


def version_tuple(text: str) -> tuple[int, ...]:
    found = re.search(r"(\d+)\.(\d+)\.(\d+)", str(text or ""))
    return tuple(int(part) for part in found.groups()) if found else (0, 0, 0)


def claude_version(claude: str) -> str:
    try:
        return run_quiet([claude, "--version"], timeout=30).stdout.strip()[:40]
    except (OSError, subprocess.SubprocessError):
        return ""


def auth_status(claude: str, env: dict) -> dict:
    """Ask the official CLI whether it is signed in; only the method and plan are kept."""
    try:
        done = run_quiet([claude, "auth", "status"], env=env, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return {"logged_in": False, "method": "", "plan": ""}
    try:
        data = json.loads(done.stdout or "{}")
    except ValueError:
        data = {}
    method = str(data.get("authMethod") or "")
    plan = str(data.get("subscriptionType") or data.get("plan") or data.get("subscription") or "")
    return {"logged_in": done.returncode == 0 and method != "none", "method": method[:24], "plan": plan[:24]}


def doctor(tools: Path, claude: str) -> dict:
    paths, env = tool_paths(tools), tool_env(tools)

    def first_line(args) -> str:
        try:
            done = run_quiet(args, env=env, timeout=60)
            return (done.stdout or done.stderr).strip().splitlines()[0][:40] if done.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError, IndexError):
            return ""

    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    try:
        import edge_tts  # noqa: F401
        tts = "edge-tts"
    except ImportError:
        tts = "say" if shutil.which("say") else ""
    return {"cli_version": claude_version(claude) if claude else "",
            "tools": {"hyperframes": first_line(["hyperframes", "--version"]),
                      "ffmpeg": (first_line([paths["ffmpeg"], "-hide_banner", "-version"]).replace("ffmpeg version ", "").split() or [""])[0],
                      "ffprobe": "ok" if paths["ffprobe"].exists() else "",
                      "chrome": "system" if Path(chrome).exists() else "", "tts": tts,
                      "node": first_line(["node", "--version"])}}


# ----------------------------------------------------------------------------- media checks
def probe(path: Path, ffprobe: str = "ffprobe") -> dict:
    done = run_quiet([ffprobe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path], timeout=60)
    if done.returncode != 0:
        raise WorkerError("invalid_output", "ffprobe 无法读取视频")
    return json.loads(done.stdout or "{}")


def media_duration(path: Path, ffprobe: str = "ffprobe") -> float:
    return float(probe(path, ffprobe).get("format", {}).get("duration") or 0)


def check_video(path: Path, expected: float | None = None, ffprobe: str = "ffprobe") -> tuple[list[str], dict]:
    if not path.is_file():
        return ["没有找到成片文件"], {}
    try:
        info = probe(path, ffprobe)
    except WorkerError:
        return ["成片无法读取，文件可能损坏"], {}
    streams = info.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float((info.get("format") or {}).get("duration") or 0)
    problems: list[str] = []
    if not video:
        problems.append("没有视频画面轨道")
    else:
        if video.get("codec_name") != "h264":
            problems.append(f"视频编码是 {video.get('codec_name')}，需要 H.264")
        if (video.get("width"), video.get("height")) != (1920, 1080):
            problems.append(f"分辨率是 {video.get('width')}×{video.get('height')}，需要 1920×1080")
        try:
            num, den = (float(x) for x in str(video.get("r_frame_rate") or "0/1").split("/"))
            fps = num / den if den else 0
        except ValueError:
            fps = 0
        if not 29.0 <= fps <= 31.0:
            problems.append(f"帧率是 {fps:.2f}，需要 30fps")
        if video.get("pix_fmt") not in {"yuv420p", "yuvj420p"}:
            problems.append(f"像素格式是 {video.get('pix_fmt')}，浏览器需要 yuv420p")
    if not audio:
        problems.append("没有旁白音轨")
    elif audio.get("codec_name") not in {"aac", "mp3"}:
        problems.append(f"音频编码是 {audio.get('codec_name')}，需要 AAC")
    if duration < 8:
        problems.append(f"时长只有 {duration:.1f} 秒")
    if expected and abs(duration - expected) > max(1.5, expected * 0.03):
        problems.append(f"时长 {duration:.1f} 秒，与配音时间轴 {expected:.1f} 秒不一致")
    return problems, {"duration": round(duration, 2), "width": (video or {}).get("width"),
                      "height": (video or {}).get("height")}


def check_command(video: str, expect: float | None) -> int:
    if expect is None and Path("storyboard.json").is_file():
        try:
            expect = float(json.loads(Path("storyboard.json").read_text(encoding="utf-8")).get("duration") or 0) or None
        except (ValueError, OSError):
            expect = None
    problems, meta = check_video(Path(video), expect)
    if problems:
        print("未通过：\n" + "\n".join(f"- {item}" for item in problems))
        return 1
    print(f"OK {meta['width']}x{meta['height']} {meta['duration']}s")
    return 0


# ----------------------------------------------------------------------------- narration
def tts_text(text: str) -> str:
    text = re.sub(r"[`*#>_\[\]{}<>|~]", "", str(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def split_clauses(text: str, limit: int = 24) -> list[str]:
    parts = re.findall(rf"[^{CLAUSE_END}]+[{CLAUSE_END}]*", text) or [text]
    merged: list[str] = []
    for part in (p.strip() for p in parts):
        if not part:
            continue
        if merged and (len(merged[-1]) < 6 or len(part) < 4) and len(merged[-1]) + len(part) <= limit:
            merged[-1] += part
        else:
            merged.append(part)
    out: list[str] = []
    for part in merged:
        while len(part) > limit + 4:
            cut = max((part.rfind(mark, 0, limit) for mark in "、 "), default=-1)
            cut = cut + 1 if cut >= limit // 2 else limit
            out.append(part[:cut])
            part = part[cut:]
        if part:
            out.append(part)
    return out


def caption_text(clause: str) -> str:
    return clause.strip().rstrip("，。、；：,.;:")


def scene_captions(text: str, words: list[dict], offset: float, duration: float) -> list[dict]:
    """Clause-level subtitles from word boundaries; proportional timing when there are none."""
    clauses = split_clauses(text)
    spans, cursor = [], 0
    for clause in clauses:
        start = text.find(clause, cursor)
        start = cursor if start < 0 else start
        spans.append((start, start + len(clause)))
        cursor = start + len(clause)
    located, cursor = [], 0
    for word in words:
        index = text.find(word["text"], cursor)
        if index < 0:
            continue
        located.append((index, word))
        cursor = index + len(word["text"])
    total_chars = max(1, sum(len(c) for c in clauses))
    captions, elapsed = [], 0.0
    for clause, (a, b) in zip(clauses, spans):
        inside = [w for index, w in located if a <= index < b]
        if inside:
            start, end = inside[0]["start"], inside[-1]["end"]
        else:
            start = elapsed
            end = elapsed + duration * len(clause) / total_chars
        elapsed = end
        if caption_text(clause):
            captions.append({"text": caption_text(clause), "start": round(offset + start, 2),
                             "end": round(offset + max(end, start + 0.4), 2)})
    for current, following in zip(captions, captions[1:]):
        current["end"] = min(current["end"], following["start"])
    return captions


def plan_timeline(durations: list[float]) -> tuple[list[float], list[tuple[float, float]], float]:
    """Narration offsets, scene windows and total length (short breath between scenes)."""
    offsets, cursor = [], LEAD_IN
    for duration in durations:
        offsets.append(round(cursor, 3))
        cursor += duration + SCENE_GAP
    total = round(offsets[-1] + durations[-1] + TAIL, 2)
    starts = [0.0] + [round(offset - SCENE_GAP / 2, 2) for offset in offsets[1:]]
    windows = [(starts[i], starts[i + 1] if i + 1 < len(starts) else total) for i in range(len(starts))]
    return offsets, windows, total


async def _edge_scene(text: str, voice: str, target: Path) -> list[dict]:
    import edge_tts
    words: list[dict] = []
    communicate = edge_tts.Communicate(text, voice, rate="-4%", boundary="WordBoundary")
    with target.open("wb") as handle:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                handle.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append({"text": chunk["text"], "start": round(start, 3),
                              "end": round(start + chunk["duration"] / 1e7, 3)})
    if target.stat().st_size < 1024:
        raise RuntimeError("empty speech")
    return words


class EdgeUnavailable(Exception):
    pass


def speak_edge(text: str, voice: str, target: Path) -> list[dict]:
    for attempt in range(3):
        try:
            return asyncio.run(_edge_scene(text, voice, target))
        except ImportError:
            break
        except Exception:  # noqa: BLE001 - network or service hiccup, retry then give up
            time.sleep(1.5 * (attempt + 1))
    raise EdgeUnavailable()


def speak_say(text: str, target: Path, ffmpeg: str) -> list[dict]:
    if not shutil.which("say"):
        raise WorkerError("tts_failed", "edge-tts 不可用，且本机没有 say 命令")
    aiff = target.with_suffix(".aiff")
    done = run_quiet(["say", "-v", FALLBACK_VOICE, "-o", aiff, text], timeout=300)
    if done.returncode != 0 or not aiff.exists():
        raise WorkerError("tts_failed", "系统语音也没有生成成功")
    run_quiet([ffmpeg, "-y", "-v", "error", "-i", aiff, "-ar", "24000", "-ac", "1", target], timeout=300)
    aiff.unlink(missing_ok=True)
    return []


def record_narration(workspace: Path, storyboard: dict, voice: str, tools: Path) -> dict:
    paths = tool_paths(tools)
    audio = workspace / "audio"
    audio.mkdir(exist_ok=True)
    scenes = storyboard["scenes"]
    texts = [tts_text(scene["narration"]) for scene in scenes]
    targets = [audio / f"scene-{index:02d}.mp3" for index in range(1, len(scenes) + 1)]
    engine = "edge-tts"
    try:
        all_words = [speak_edge(text, voice, target) for text, target in zip(texts, targets)]
    except EdgeUnavailable:
        # One voice for the whole video: never mix the online voice with the system fallback.
        engine = "macos-say"
        all_words = [speak_say(text, target, str(paths["ffmpeg"])) for text, target in zip(texts, targets)]
    durations = [media_duration(target, str(paths["ffprobe"])) for target in targets]
    captions_by_scene = list(zip(texts, all_words, durations))
    offsets, windows, total = plan_timeline(durations)
    captions = []
    for (text, words, duration), offset in zip(captions_by_scene, offsets):
        captions.extend(scene_captions(text, words, offset, duration))
    inputs, chains = [], []
    for index, offset in enumerate(offsets):
        inputs += ["-i", audio / f"scene-{index + 1:02d}.mp3"]
        delay = int(round(offset * 1000))
        chains.append(f"[{index}:a]aresample=48000,adelay={delay}:all=1[a{index}]")
    mix = "".join(f"[a{index}]" for index in range(len(offsets)))
    graph = ";".join(chains) + f";{mix}amix=inputs={len(offsets)}:normalize=0:dropout_transition=0,apad,loudnorm=I=-16:TP=-1.5:LRA=11[out]"
    assets = workspace / "video" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    narration = assets / "narration.mp3"
    done = run_quiet([paths["ffmpeg"], "-y", "-v", "error", *inputs, "-filter_complex", graph, "-map", "[out]",
                      "-t", f"{total:.2f}", "-ac", "2", "-ar", "48000", "-c:a", "libmp3lame", "-b:a", "192k", narration],
                     timeout=600)
    if done.returncode != 0 or not narration.exists():
        raise WorkerError("tts_failed", "配音拼接失败：" + clean_detail(done.stderr))
    for scene, (start, end) in zip(scenes, windows):
        scene["start"], scene["end"] = start, end
    storyboard["duration"] = total
    (workspace / "storyboard.json").write_text(json.dumps(storyboard, ensure_ascii=False, indent=2), encoding="utf-8")
    (audio / "captions.json").write_text(json.dumps(captions, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"duration": total, "engine": engine, "captions": len(captions)}


# ----------------------------------------------------------------------------- storyboard
def read_storyboard(path: Path) -> dict:
    if not path.is_file():
        raise WorkerError("storyboard_invalid", "没有写出 storyboard.json")
    raw = path.read_text(encoding="utf-8").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except ValueError:
        raise WorkerError("storyboard_invalid", "storyboard.json 不是合法 JSON") from None
    scenes = [scene for scene in data.get("scenes") or [] if isinstance(scene, dict)
              and tts_text(scene.get("narration"))][:16]
    if len(scenes) < 2:
        raise WorkerError("storyboard_invalid", "分镜少于两镜或缺少旁白")
    for scene in scenes:
        scene.pop("start", None)
        scene.pop("end", None)
    data["scenes"] = scenes
    return data


# ----------------------------------------------------------------------------- Claude Code
def permission_settings() -> dict:
    return {"permissions": {"allow": ALLOW, "deny": DENY, "defaultMode": "dontAsk"}, "disableAllHooks": True}


def claude_command(claude: str, settings: dict, *, rules_file: Path, settings_file: Path, turns: int,
                   version: tuple[int, ...]) -> list[str]:
    cmd = [claude, "-p", "--output-format", "stream-json", "--verbose",
           "--model", settings.get("model") or "claude-opus-5-5", "--effort", settings.get("effort") or "high",
           "--permission-mode", "dontAsk", "--settings", str(settings_file), "--strict-mcp-config",
           "--no-session-persistence", "--append-system-prompt-file", str(rules_file), "--max-turns", str(turns)]
    if settings.get("access") == "api_key":
        cmd += ["--max-budget-usd", str(settings.get("budget_usd") or 8)]
    if version >= (2, 1, 259):
        cmd += ["--permission-prompts", "none"]
    return cmd + ["--disallowedTools", *DENY, "--allowedTools", *ALLOW]


def describe(event: dict, stage: str) -> tuple[str, str] | None:
    """Turn a stream-json event into (phase, learner-facing message)."""
    if event.get("type") != "assistant":
        return None
    for block in (event.get("message") or {}).get("content") or []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        name, data = block.get("name"), block.get("input") or {}
        if name == "Bash":
            command = str(data.get("command") or "")
            for needle, phase, text in (("hyperframes render", "render", "正在渲染 1080P 成片"),
                                        ("hyperframes snapshot", "review", "正在逐镜截图自查"),
                                        ("learnloop-check", "check", "正在校验成片"),
                                        ("hyperframes lint", "compose", "正在检查合成结构"),
                                        ("hyperframes check", "compose", "正在检查合成结构")):
                if needle in command:
                    return phase, text
        elif name == "Read" and str(data.get("file_path") or "").lower().endswith(".png"):
            return "review", "Claude 正在查看截图，检查排版与内容"
        elif name in {"Write", "Edit", "MultiEdit"}:
            path = str(data.get("file_path") or "")
            if path.endswith("storyboard.json"):
                return "storyboard", "Claude 正在写分镜方案"
            if "video/" in path:
                return "compose", "Claude 正在编写画面与动效"
        elif name in {"TodoWrite", "TaskCreate", "TaskUpdate"}:
            todos = data.get("todos") if isinstance(data.get("todos"), list) else [data]
            current = next((t for t in todos if isinstance(t, dict) and t.get("status") == "in_progress"), None)
            if current:
                text = str(current.get("activeForm") or current.get("content") or current.get("subject") or "")
                if text:
                    return "", clean_detail(text, 60)
        elif name == "Skill":
            return "", "Claude 正在阅读 HyperFrames 制作技能"
    return None


def classify(result: dict | None, retry_errors: list[str], stderr: str) -> str:
    text = " ".join(filter(None, [str((result or {}).get("result") or ""), stderr]))
    last = retry_errors[-1] if retry_errors else ""
    subtype = str((result or {}).get("subtype") or "")
    if last in LOGIN_ERRORS or re.search(r"/login|not logged in|invalid api key|authentication|oauth token|\b401\b", text, re.I):
        return "login_required"
    if last in LIMIT_ERRORS or re.search(r"usage limit|limit reached|rate limit|quota|credit balance|billing", text, re.I):
        return "usage_limit"
    if last == "model_not_found" or re.search(r"model\b.*\b(not found|not available|does not exist|invalid)|unknown model", text, re.I):
        return "model_unavailable"
    if "budget" in subtype:
        return "budget"
    if subtype == "error_max_turns":
        return "timeout"
    return "worker_error"


class ClaudeRun:
    """One headless Claude Code run with live progress, cancellation and a hard timeout."""

    def __init__(self, cmd: list[str], prompt: str, cwd: Path, env: dict, log: Path, *, stage: str,
                 on_progress, should_stop, timeout: int):
        self.cmd, self.prompt, self.cwd, self.env, self.log = cmd, prompt, cwd, env, log
        self.stage, self.on_progress, self.should_stop, self.timeout = stage, on_progress, should_stop, timeout

    def _stop(self, process: subprocess.Popen) -> None:
        for sig, wait in ((signal.SIGINT, 15), (signal.SIGTERM, 10), (signal.SIGKILL, 5)):
            if process.poll() is not None:
                return
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                return
            try:
                process.wait(wait)
            except subprocess.TimeoutExpired:
                continue

    def run(self) -> dict:
        self.log.parent.mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen(self.cmd, cwd=self.cwd, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True, bufsize=1)
        process.stdin.write(self.prompt)
        process.stdin.close()
        stderr_lines: list[str] = []
        threading.Thread(target=lambda: stderr_lines.extend(process.stderr), daemon=True).start()
        state = {"result": None, "retry": [], "stopped": ""}

        def watchdog():
            deadline = time.monotonic() + self.timeout
            while process.poll() is None:
                if self.should_stop():
                    state["stopped"] = "cancelled"
                elif time.monotonic() > deadline:
                    state["stopped"] = "timeout"
                if state["stopped"]:
                    self._stop(process)
                    return
                time.sleep(2)

        threading.Thread(target=watchdog, daemon=True).start()
        try:
            with self.log.open("a", encoding="utf-8") as log:
                for line in process.stdout:
                    log.write(line)
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("type") == "result":
                        state["result"] = event
                    elif event.get("type") == "system" and event.get("subtype") == "api_retry":
                        state["retry"].append(str(event.get("error") or ""))
                    progress = describe(event, self.stage)
                    if progress:
                        self.on_progress(*progress)
            process.wait()
        except BaseException:
            # Claude runs in its own process group; take it down with the worker (e.g. Ctrl+C).
            self._stop(process)
            raise
        if state["stopped"] == "cancelled":
            raise Cancelled()
        if state["stopped"] == "timeout":
            raise WorkerError("timeout", "超过制作时间上限")
        result = state["result"]
        if not result or result.get("is_error") or result.get("subtype") != "success":
            code = classify(result, state["retry"], "".join(stderr_lines[-20:]))
            raise WorkerError(code, clean_detail((result or {}).get("result") or "".join(stderr_lines[-3:])))
        return result


# ----------------------------------------------------------------------------- backend API
class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"{status} {detail}")
        self.status, self.detail = status, detail


class Api:
    def __init__(self, site: str, token: str):
        self.site, self.token = site.rstrip("/"), token
        # Loopback only: never send the pairing token through a proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _send(self, request: urllib.request.Request, timeout: int) -> dict:
        request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read() or b"{}").get("detail", "")
            except ValueError:
                detail = ""
            raise ApiError(error.code, str(detail)) from None

    def post(self, path: str, body: dict | None = None, timeout: int = 60) -> dict:
        request = urllib.request.Request(self.site + path, data=json.dumps(body or {}).encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
        return self._send(request, timeout)

    def upload(self, path: str, file: Path, content_type: str, lease: str) -> dict:
        with file.open("rb") as handle:
            request = urllib.request.Request(self.site + path, data=handle, method="POST", headers={
                "Content-Type": content_type, "Content-Length": str(file.stat().st_size), "x-video-lease": lease})
            return self._send(request, timeout=600)


# ----------------------------------------------------------------------------- jobs
class Job:
    """Shared progress state for one claimed job; a thread keeps its lease alive."""

    def __init__(self, api: Api, data: dict, info_fn):
        self.api, self.data, self.info_fn = api, data, info_fn
        self.id, self.lease = data["id"], data["lease"]
        self.phase, self.message, self.cancelled = "prepare", "", False
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._beat, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._done.set()
        self._thread.join(5)

    def progress(self, phase: str = "", message: str = "") -> None:
        if phase:
            self.phase = phase
        self.message = message
        self.beat()

    def beat(self) -> None:
        if self.data.get("kind") != "video" or self.cancelled:
            return
        try:
            answer = self.api.post(f"/api/claude-video-worker/{self.id}/heartbeat",
                                   {"lease": self.lease, "phase": self.phase, "message": self.message})
            self.cancelled = bool(answer.get("cancelled"))
        except ApiError as error:
            if error.status in {404, 409}:
                self.cancelled = True
        except (urllib.error.URLError, OSError):
            pass

    def _beat(self) -> None:
        last_hello = 0.0
        while not self._done.wait(HEARTBEAT_SECONDS):
            self.beat()
            if time.monotonic() - last_hello > HELLO_SECONDS:
                last_hello = time.monotonic()
                try:
                    self.api.post("/api/claude-video-worker/hello", {"info": {**self.info_fn(), "busy": True}})
                except (ApiError, urllib.error.URLError, OSError):
                    pass

    def check_cancel(self) -> None:
        if self.cancelled:
            raise Cancelled()


class Worker:
    def __init__(self, *, site: str, state: Path, tools: Path, claude: str, token: str):
        self.api, self.state, self.tools, self.claude = Api(site, token), state, tools, claude
        self.version = version_tuple(claude_version(claude))
        self._info: dict = {}
        self._info_at = 0.0

    # -- environment -----------------------------------------------------------------
    def info(self) -> dict:
        if time.monotonic() - self._info_at > 300 or not self._info:
            env = tool_env(self.tools)
            report = doctor(self.tools, self.claude)
            report["auth"] = auth_status(self.claude, env)
            self._info, self._info_at = report, time.monotonic()
        return self._info

    def env_for(self, job: dict) -> dict:
        return tool_env(self.tools, job.get("api_key", "") if job["settings"].get("access") == "api_key" else "")

    # -- workspace -------------------------------------------------------------------
    def workspace(self, job: dict) -> Path:
        root = self.state / "jobs" / job["id"]
        reuse = job.get("stage") == "production" and (root / "video" / "index.html").exists() \
            and (root / "video" / "assets" / "narration.mp3").exists()
        paths = tool_paths(self.tools)
        if not reuse:
            shutil.rmtree(root, ignore_errors=True)
            (root / ".claude").mkdir(parents=True)
            for name in SKILLS:
                if (paths["skills"] / name).exists():
                    shutil.copytree(paths["skills"] / name, root / ".claude" / "skills" / name)
            if paths["guides"].exists():
                shutil.copytree(paths["guides"], root / "guides")
            else:
                (root / "guides").mkdir()
            done = run_quiet(["hyperframes", "init", "video", "--example", "blank", "--non-interactive"],
                             cwd=root, env=tool_env(self.tools), timeout=300)
            if not (root / "video" / "index.html").exists():
                raise WorkerError("tools_missing", "HyperFrames 项目初始化失败：" + clean_detail(done.stderr or done.stdout))
            # Our task prompt replaces HyperFrames' interactive agent guide; without package.json npx
            # resolves "hyperframes" through the workspace's link to the pinned local install.
            for name in ("CLAUDE.md", "AGENTS.md", "package.json"):
                (root / "video" / name).unlink(missing_ok=True)
            (root / "node_modules").symlink_to(self.tools / "node_modules", target_is_directory=True)
            vendor = root / "video" / "vendor"
            vendor.mkdir()
            for key in ("gsap", "three"):
                if paths[key].exists():
                    shutil.copy2(paths[key], vendor / paths[key].name)
            for name in ("audio", "out", "video/assets"):
                (root / name).mkdir(parents=True, exist_ok=True)
        (root / "guides" / "learnloop-style.md").write_text(job["prompts"]["style"], encoding="utf-8")
        self.prune()
        return root

    def prune(self) -> None:
        jobs = sorted((p for p in (self.state / "jobs").glob("claude_*") if p.is_dir()), key=lambda p: p.stat().st_mtime)
        for old in jobs[:-KEEP_WORKSPACES]:
            shutil.rmtree(old, ignore_errors=True)
            shutil.rmtree(self.state / "runs" / old.name, ignore_errors=True)

    def run_claude(self, job: Job, workspace: Path, prompt: str, *, stage: str, limits: dict) -> dict:
        runs = self.state / "runs" / job.id
        runs.mkdir(parents=True, exist_ok=True)
        rules, settings_file = runs / "rules.md", runs / "settings.json"
        rules.write_text(job.data["prompts"]["rules"], encoding="utf-8")
        settings_file.write_text(json.dumps(permission_settings(), ensure_ascii=False), encoding="utf-8")
        cmd = claude_command(self.claude, job.data["settings"], rules_file=rules, settings_file=settings_file,
                             turns=limits["turns"], version=self.version)
        run = ClaudeRun(cmd, prompt, workspace, self.env_for(job.data), runs / f"{stage}.jsonl", stage=stage,
                        on_progress=lambda phase, text: job.progress(phase if stage != "storyboard" else "storyboard", text),
                        should_stop=lambda: job.cancelled, timeout=limits["timeout"])
        return run.run()

    # -- stages ----------------------------------------------------------------------
    def storyboard_stage(self, job: Job, workspace: Path) -> str:
        job.progress("storyboard", "Claude 正在设计分镜")
        (workspace / "storyboard.json").unlink(missing_ok=True)
        self.run_claude(job, workspace, job.data["prompts"]["storyboard"], stage="storyboard", limits=STORYBOARD)
        storyboard = read_storyboard(workspace / "storyboard.json")
        job.check_cancel()
        job.progress("voice", "正在录制中文配音并对齐字幕")
        voice = record_narration(workspace, storyboard, job.data["settings"].get("voice") or "zh-CN-XiaoxiaoNeural", self.tools)
        say(f"配音完成：{voice['duration']} 秒，{voice['captions']} 句字幕（{voice['engine']}）")
        answer = self.api.post(f"/api/claude-video-worker/{job.id}/storyboard", {"lease": job.lease, "storyboard": storyboard})
        return answer.get("next", "production")

    def restore_storyboard(self, job: Job, workspace: Path) -> None:
        """Production after approval on a fresh workspace: rebuild narration from the saved storyboard."""
        if (workspace / "video" / "assets" / "narration.mp3").exists() and (workspace / "storyboard.json").exists():
            return
        saved = job.data.get("storyboard") or {}
        storyboard = {key: saved.get(key) for key in ("title", "hook", "summary", "visual_style", "quiz", "self_check")}
        storyboard["scenes"] = [{k: v for k, v in scene.items() if k not in {"start", "end"}} for scene in saved.get("scenes") or []]
        job.progress("voice", "正在重新录制配音")
        record_narration(workspace, storyboard, job.data["settings"].get("voice") or "zh-CN-XiaoxiaoNeural", self.tools)

    def production_stage(self, job: Job, workspace: Path) -> None:
        paths = tool_paths(self.tools)
        job.progress("compose", "Claude 正在制作画面与动效")
        (workspace / "out" / "video.mp4").unlink(missing_ok=True)
        self.run_claude(job, workspace, job.data["prompts"]["production"], stage="production", limits=PRODUCTION)
        expected = float(json.loads((workspace / "storyboard.json").read_text(encoding="utf-8")).get("duration") or 0)
        problems, meta = check_video(workspace / "out" / "video.mp4", expected, str(paths["ffprobe"]))
        if problems:
            job.check_cancel()
            say("成片校验未通过，请 Claude 修复：" + "；".join(problems))
            job.progress("render", "成片校验未通过，Claude 正在修复")
            repair = job.data["prompts"]["repair"].replace("{{problems}}", "\n".join(f"- {p}" for p in problems))
            self.run_claude(job, workspace, repair, stage="repair", limits=REPAIR)
            problems, meta = check_video(workspace / "out" / "video.mp4", expected, str(paths["ffprobe"]))
        if problems:
            error = workspace / "out" / "error.txt"
            detail = error.read_text(encoding="utf-8")[:200] if error.exists() else "；".join(problems)
            raise WorkerError("invalid_output" if (workspace / "out" / "video.mp4").exists() else "render_failed",
                              clean_detail(detail))
        job.check_cancel()
        job.progress("upload", "正在保存视频")
        final = workspace / "out" / "final.mp4"
        done = run_quiet([paths["ffmpeg"], "-y", "-v", "error", "-i", workspace / "out" / "video.mp4", "-c", "copy",
                          "-movflags", "+faststart", final], timeout=600)
        if done.returncode != 0 or not final.exists():
            final = workspace / "out" / "video.mp4"
        storyboard = json.loads((workspace / "storyboard.json").read_text(encoding="utf-8"))
        first = (storyboard.get("scenes") or [{}])[0]
        at = max(1.5, (float(first.get("start") or 0) + float(first.get("end") or 3)) / 2)
        poster = workspace / "out" / "poster.jpg"
        run_quiet([paths["ffmpeg"], "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", final, "-frames:v", "1", "-q:v", "3", poster],
                  timeout=120)
        self.api.upload(f"/api/claude-video-worker/{job.id}/video", final, "video/mp4", job.lease)
        if poster.exists():
            try:
                self.api.upload(f"/api/claude-video-worker/{job.id}/poster", poster, "image/jpeg", job.lease)
            except ApiError:
                pass
        result = {}
        if (workspace / "out" / "result.json").exists():
            try:
                result = json.loads((workspace / "out" / "result.json").read_text(encoding="utf-8"))
            except ValueError:
                result = {}
        meta.update({"title": result.get("title") or storyboard.get("title", ""), "notes": result.get("notes", ""),
                     "chapters": result.get("chapters") or []})
        self.api.post(f"/api/claude-video-worker/{job.id}/finish", {"lease": job.lease, "meta": meta})

    def process(self, data: dict) -> None:
        with Job(self.api, data, self.info) as job:
            try:
                if data["kind"] == "ping":
                    return self.ping(job)
                say(f"开始制作讲解视频「{data.get('topic', '')}」（{data['settings'].get('model')}，阶段：{data.get('stage')}）")
                workspace = self.workspace(data)
                stage = data.get("stage", "storyboard")
                if stage == "storyboard":
                    if self.storyboard_stage(job, workspace) == "wait":
                        say("分镜已上传，等待在网页上确认后再制作。")
                        return
                else:
                    self.restore_storyboard(job, workspace)
                job.check_cancel()
                self.production_stage(job, workspace)
                say("讲解视频已完成并保存。")
            except Cancelled:
                say("任务已在网页上取消。")
                self._fail(job, "cancelled", "")
            except WorkerError as error:
                say(f"任务失败：{error.code} {error.detail}")
                self._fail(job, error.code, error.detail)
            except ApiError as error:
                say(f"与 LearnLoop 通信失败：{error.status} {error.detail}")
                if error.status not in {404, 409}:
                    self._fail(job, "worker_error", error.detail)
            except Exception as error:  # noqa: BLE001 - report and keep the worker alive
                say(f"任务异常：{type(error).__name__}")
                self._fail(job, "worker_error", type(error).__name__)

    def _fail(self, job: Job, code: str, detail: str) -> None:
        path = "ping" if job.data["kind"] == "ping" else "fail"
        body = ({"lease": job.lease, "ok": False, "code": code, "detail": detail} if path == "ping"
                else {"lease": job.lease, "code": code, "detail": detail})
        try:
            self.api.post(f"/api/claude-video-worker/{job.id}/{path}", body)
        except (ApiError, urllib.error.URLError, OSError):
            pass

    def ping(self, job: Job) -> None:
        settings = job.data["settings"]
        cmd = [self.claude, "-p", "--output-format", "json", "--model", settings.get("model") or "claude-opus-5-5",
               "--max-turns", "1", "--tools", "", "--strict-mcp-config", "--no-session-persistence"]
        try:
            done = subprocess.run(cmd, input="请只回复四个字：连接成功", capture_output=True, text=True, timeout=180,
                                  env=self.env_for(job.data), cwd=self.state)
            result = json.loads(done.stdout or "{}")
        except (subprocess.SubprocessError, OSError, ValueError) as error:
            return self._fail(job, "worker_error", type(error).__name__)
        if result.get("is_error") or result.get("subtype") != "success":
            return self._fail(job, classify(result, [], done.stderr), clean_detail(result.get("result") or done.stderr))
        self.api.post(f"/api/claude-video-worker/{job.id}/ping",
                      {"lease": job.lease, "ok": True, "reply": clean_detail(result.get("result"), 60)})
        say("Claude 连接测试成功。")

    # -- loop ------------------------------------------------------------------------
    def loop(self, *, once: bool = False) -> None:
        stop_file = self.state / "stop.requested"
        stop_file.unlink(missing_ok=True)
        say("Claude 讲解视频接入已启动；保持此窗口运行即可，按 Ctrl+C 停止。")
        info = self.info()
        if not info["auth"]["logged_in"]:
            say("提示：本机 Claude Code 还没有登录。请在启动菜单选择“登录 Claude”，否则只能使用 API Key 模式。")
        while not stop_file.exists():
            try:
                answer = self.api.post("/api/claude-video-worker/claim", {"info": {**self.info(), "busy": False}})
            except ApiError as error:
                say(f"LearnLoop 拒绝了接入：{error.detail or error.status}")
                if error.status in {401, 403}:
                    time.sleep(30)
                answer = {}
            except (urllib.error.URLError, OSError):
                answer = {}
            if answer.get("job"):
                self.process(answer["job"])
            elif once:
                return
            else:
                time.sleep(5)
            if once:
                return
        say("已收到停止请求，视频接入程序退出。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_setup = sub.add_parser("setup")
    p_setup.add_argument("--tools", type=Path, required=True)
    p_run = sub.add_parser("run")
    for name in ("--site", "--claude"):
        p_run.add_argument(name, required=True)
    for name in ("--state", "--tools", "--token-file"):
        p_run.add_argument(name, type=Path, required=True)
    p_run.add_argument("--once", action="store_true")
    p_check = sub.add_parser("check")
    p_check.add_argument("video")
    p_check.add_argument("--expect", type=float)
    p_doctor = sub.add_parser("doctor")
    p_doctor.add_argument("--tools", type=Path, required=True)
    p_doctor.add_argument("--claude", default="")
    args = parser.parse_args(argv)
    if args.command == "setup":
        setup(args.tools)
        return 0
    if args.command == "check":
        return check_command(args.video, args.expect)
    if args.command == "doctor":
        report = doctor(args.tools, args.claude)
        report["auth"] = auth_status(args.claude, tool_env(args.tools)) if args.claude else {}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    token = json.loads(args.token_file.read_text(encoding="utf-8")).get("video_worker_token", "")
    if not 32 <= len(token) <= 256:
        raise SystemExit("缺少视频接入配对密钥：请重新运行启动菜单里的“首次安装 / 修复安装”。")
    if not Path(args.claude).exists() and not shutil.which(args.claude):
        raise SystemExit("没有找到 Claude Code：请先在启动菜单选择“登录 Claude”。")
    args.state.mkdir(parents=True, exist_ok=True, mode=0o700)
    Worker(site=args.site, state=args.state, tools=args.tools, claude=args.claude, token=token).loop(once=args.once)
    return 0


if __name__ == "__main__":
    sys.exit(main())
