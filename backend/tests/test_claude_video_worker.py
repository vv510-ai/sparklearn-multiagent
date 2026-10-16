"""The local Claude video worker: timing, subtitles, locked-down CLI flags and failure handling."""
import importlib.util
import json
import sys
import textwrap
import time
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "claude_video_worker", Path(__file__).resolve().parents[2] / "scripts/claude_video_worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def test_subtitle_clauses_never_split_numbers_and_stay_short():
    clauses = worker.split_clauses("人体正常体温约为 36.5 摄氏度，1,000 毫升等于 1 升。酶在适宜温度下活性最强，温度过高会失活！")
    assert clauses[0] == "人体正常体温约为 36.5 摄氏度，"
    assert "1,000 毫升等于 1 升。" in clauses
    assert all(len(clause) <= 28 for clause in clauses)
    assert worker.caption_text("活性最强，") == "活性最强" and worker.caption_text("会失活吗？") == "会失活吗？"


def test_captions_follow_word_boundaries_and_fall_back_to_proportional_timing():
    text = "在叶绿体里，植物利用光能。"
    words = [{"text": "在", "start": 0.1, "end": 0.2}, {"text": "叶绿体", "start": 0.2, "end": 0.8},
             {"text": "里", "start": 0.8, "end": 1.0}, {"text": "植物", "start": 1.3, "end": 1.7},
             {"text": "利用", "start": 1.7, "end": 2.0}, {"text": "光能", "start": 2.0, "end": 2.6}]
    timed = worker.scene_captions(text, words, offset=10.0, duration=2.8)
    assert timed == [{"text": "在叶绿体里", "start": 10.1, "end": 11.0}, {"text": "植物利用光能", "start": 11.3, "end": 12.6}]
    rough = worker.scene_captions(text, [], offset=0.0, duration=3.0)
    assert [c["text"] for c in rough] == ["在叶绿体里", "植物利用光能"]
    assert rough[0]["start"] == 0.0 and rough[0]["end"] <= rough[1]["start"] and rough[1]["end"] == pytest.approx(3.0, abs=0.01)


def test_timeline_gives_each_scene_its_narration_plus_a_breath():
    offsets, windows, total = worker.plan_timeline([2.0, 3.0])
    assert offsets == [0.3, 2.75]
    assert total == pytest.approx(2.75 + 3.0 + worker.TAIL)
    assert windows[0][0] == 0.0 and windows[0][1] == windows[1][0] == pytest.approx(2.52, abs=0.01)
    assert windows[-1][1] == total


def test_claude_runs_locked_down_with_subscription_or_api_budget(tmp_path):
    settings = {"model": "claude-sonnet-5-5", "effort": "medium", "access": "subscription"}
    cmd = worker.claude_command("claude", settings, rules_file=tmp_path / "r.md", settings_file=tmp_path / "s.json",
                                turns=40, version=(2, 1, 299))
    assert cmd[:2] == ["claude", "-p"] and cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-5-5" and cmd[cmd.index("--effort") + 1] == "medium"
    assert "--strict-mcp-config" in cmd and "--no-session-persistence" in cmd and "--max-budget-usd" not in cmd
    assert cmd[cmd.index("--permission-prompts") + 1] == "none"
    # Variadic tool lists come last so nothing after them is swallowed as a rule.
    assert cmd.index("--allowedTools") > cmd.index("--disallowedTools") > cmd.index("--permission-prompts")
    old = worker.claude_command("claude", {**settings, "access": "api_key", "budget_usd": 5}, rules_file=tmp_path / "r.md",
                                settings_file=tmp_path / "s.json", turns=40, version=(2, 1, 200))
    assert "--permission-prompts" not in old and old[old.index("--max-budget-usd") + 1] == "5"
    rules = worker.permission_settings()
    assert rules["disableAllHooks"] is True and rules["permissions"]["defaultMode"] == "dontAsk"
    assert "Bash(hyperframes publish *)" in rules["permissions"]["deny"] and "WebFetch" in rules["permissions"]["deny"]
    assert "Edit(./**)" in rules["permissions"]["allow"] and not any(r in {"Read", "Bash", "Edit"} for r in rules["permissions"]["allow"])


def test_api_key_only_reaches_claude_in_api_key_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-shell")
    plain = worker.tool_env(tmp_path)
    assert "ANTHROPIC_API_KEY" not in plain and plain["npm_config_offline"] == "true"
    assert plain["PATH"].startswith(str(tmp_path / "bin"))
    assert worker.tool_env(tmp_path, "sk-ant-owner")["ANTHROPIC_API_KEY"] == "sk-ant-owner"
    assert "npm_config_offline" not in worker.tool_env(tmp_path, offline=False)
    assert worker.clean_detail(f"{Path.home()}/x sk-ant-api03-SECRETSECRET") == "~/x sk-ant-api0…"


def event(name, data):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": data}]}}


def test_progress_and_failures_are_described_for_the_learner():
    assert worker.describe(event("Bash", {"command": "hyperframes render video -o out/video.mp4"}), "production")[0] == "render"
    assert worker.describe(event("Read", {"file_path": "out/snapshots/at-3s.png"}), "production")[0] == "review"
    assert worker.describe(event("Write", {"file_path": "/w/video/compositions/s1.html"}), "production")[0] == "compose"
    todo = worker.describe(event("TodoWrite", {"todos": [{"content": "a", "status": "completed"},
                                                         {"content": "b", "activeForm": "正在制作第 2 镜", "status": "in_progress"}]}), "production")
    assert todo == ("", "正在制作第 2 镜")
    assert worker.describe({"type": "user"}, "production") is None
    assert worker.classify({"is_error": True, "result": "x"}, ["authentication_failed"], "") == "login_required"
    assert worker.classify({"is_error": True, "result": "Claude AI usage limit reached|1792140000"}, [], "") == "usage_limit"
    assert worker.classify({"is_error": True, "result": "x"}, ["model_not_found"], "") == "model_unavailable"
    assert worker.classify({"is_error": True, "subtype": "error_max_turns", "result": ""}, [], "") == "timeout"
    assert worker.classify(None, [], "boom") == "worker_error"


def test_storyboard_must_be_parseable_with_narrated_scenes(tmp_path):
    path = tmp_path / "storyboard.json"
    with pytest.raises(worker.WorkerError) as missing:
        worker.read_storyboard(path)
    assert missing.value.code == "storyboard_invalid"
    path.write_text("```json\n" + json.dumps({"title": "t", "scenes": [
        {"title": "a", "narration": "第一镜旁白", "start": 3, "end": 9}, {"title": "空", "narration": " "},
        {"title": "b", "narration": "第二镜旁白"}]}, ensure_ascii=False) + "\n```", encoding="utf-8")
    board = worker.read_storyboard(path)
    assert [s["title"] for s in board["scenes"]] == ["a", "b"] and "start" not in board["scenes"][0]
    path.write_text(json.dumps({"scenes": [{"narration": "只有一镜"}]}), encoding="utf-8")
    with pytest.raises(worker.WorkerError):
        worker.read_storyboard(path)


def test_video_check_reports_every_problem(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    good = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
                         "r_frame_rate": "30/1", "pix_fmt": "yuv420p"}, {"codec_type": "audio", "codec_name": "aac"}],
            "format": {"duration": "61.2"}}
    monkeypatch.setattr(worker, "probe", lambda path, ffprobe="ffprobe": good)
    assert worker.check_video(video, 61.0)[0] == []
    bad = {"streams": [{"codec_type": "video", "codec_name": "hevc", "width": 1280, "height": 720,
                        "r_frame_rate": "60/1", "pix_fmt": "yuv444p"}], "format": {"duration": "40"}}
    monkeypatch.setattr(worker, "probe", lambda path, ffprobe="ffprobe": bad)
    problems = worker.check_video(video, 61.0)[0]
    assert len(problems) == 6 and any("旁白音轨" in p for p in problems) and any("不一致" in p for p in problems)
    assert worker.check_video(tmp_path / "missing.mp4")[0] == ["没有找到成片文件"]


def fake_claude(tmp_path, body: str) -> list[str]:
    script = tmp_path / "fake_claude.py"
    script.write_text("import json, sys, time\nprompt = sys.stdin.read()\n" + textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(script)]


def run(cmd, tmp_path, *, stop=lambda: False, timeout=30, progress=None):
    seen = progress if progress is not None else []
    return worker.ClaudeRun(cmd, "任务", tmp_path, {"PATH": "/usr/bin:/bin"}, tmp_path / "log.jsonl", stage="production",
                            on_progress=lambda phase, text: seen.append((phase, text)), should_stop=stop,
                            timeout=timeout).run()


def test_headless_run_streams_progress_and_returns_the_result(tmp_path):
    cmd = fake_claude(tmp_path, '''
        print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash",
              "input": {"command": "hyperframes render video"}}]}}), flush=True)
        print("not json", flush=True)
        print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": prompt}), flush=True)
    ''')
    seen = []
    result = run(cmd, tmp_path, progress=seen)
    assert result["result"] == "任务" and seen == [("render", "正在渲染 1080P 成片")]
    assert (tmp_path / "log.jsonl").read_text(encoding="utf-8").count("\n") == 3


def test_headless_run_classifies_login_failure_and_honours_cancel_and_timeout(tmp_path):
    failing = fake_claude(tmp_path, '''
        print(json.dumps({"type": "system", "subtype": "api_retry", "error": "authentication_failed"}), flush=True)
        print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
              "result": "Invalid API key · Please run /login"}), flush=True)
        sys.exit(1)
    ''')
    with pytest.raises(worker.WorkerError) as failed:
        run(failing, tmp_path)
    assert failed.value.code == "login_required" and "/login" in failed.value.detail
    slow = fake_claude(tmp_path, "time.sleep(60)\n")
    started = time.monotonic()
    with pytest.raises(worker.Cancelled):
        run(slow, tmp_path, stop=lambda: True)
    with pytest.raises(worker.WorkerError) as timed_out:
        run(slow, tmp_path, timeout=1)
    assert timed_out.value.code == "timeout" and time.monotonic() - started < 40


class StubApi:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def post(self, path, body=None, timeout=60):
        self.calls.append((path, body))
        answer = self.answers.pop(0) if self.answers else {"status": "running", "cancelled": False}
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_heartbeat_learns_about_cancellation_and_lost_leases():
    api = StubApi([{"status": "running", "cancelled": False}, {"status": "cancelled", "cancelled": True}])
    job = worker.Job(api, {"id": "claude_" + "a" * 40, "lease": "b" * 48, "kind": "video"}, lambda: {})
    job.progress("compose", "Claude 正在制作画面与动效")
    assert not job.cancelled and api.calls[0][1] == {"lease": "b" * 48, "phase": "compose", "message": "Claude 正在制作画面与动效"}
    job.beat()
    assert job.cancelled
    with pytest.raises(worker.Cancelled):
        job.check_cancel()
    lost = worker.Job(StubApi([worker.ApiError(409, "lease")]), {"id": "x", "lease": "b" * 48, "kind": "video"}, lambda: {})
    lost.beat()
    assert lost.cancelled
