"""Repeatable feedback checks. No model calls in local mode; live is explicit."""
from __future__ import annotations
import argparse
import contextlib
import datetime as dt
import json
import os
from pathlib import Path
import queue
import re
import shlex
import signal
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
UI_SPECS = [
    "assessment-scroll", "one-page-feedback", "math-rendering",
    "generation-progress", "feedback-batch", "conversation-first",
    "responsive-workspace", "feedback-audit",
]
REMOTE_LEASE = """
import fcntl,json,pathlib,select,sys,time
expected,ttl=sys.argv[1],int(sys.argv[2])
lock=open('/run/lock/sparklearn-auto-deploy.lock','a')
until=time.monotonic()+20
while True:
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        break
    except BlockingIOError:
        if time.monotonic()>until:
            raise SystemExit('Deployment or acceptance already holds the lock; retry after it finishes.')
        time.sleep(.25)
commit=pathlib.Path('/opt/sparklearn/shared/deployed_commit').read_text().strip()
if commit!=expected:
    raise SystemExit('Deployed revision differs from expected revision: '+commit)
print(json.dumps({'event':'locked','release':commit}),flush=True)
ready,_,_=select.select([sys.stdin],[],[],ttl)
if ready:
    sys.stdin.readline()
    print(json.dumps({'event':'released'}),flush=True)
else:
    print(json.dumps({'event':'expired'}),flush=True)
    raise SystemExit(75)
"""

def revision():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()

def clean_error(text):
    lines = text.splitlines()
    return "\n".join("[redacted header]" if re.search(r"cookie:|authorization:|set-cookie:", line, re.I) else line
                     for line in lines[-18:])

class ReleaseLease:
    """Uses the existing deployer's lock. Disconnect/TTL releases it; no timer changes."""
    def __init__(self, target, identity, expected, ttl, out):
        if not re.fullmatch(r"[a-zA-Z0-9_.@:-]+", target) or target.startswith("-"):
            raise ValueError("Invalid SSH target")
        if not re.fullmatch(r"[0-9a-f]{40}", expected):
            raise ValueError("Expected release must be a full 40-character commit")
        if not 30 <= ttl <= 1800:
            raise ValueError("Lease duration must be 30..1800 seconds")
        self.args = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                     "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2"]
        if identity:
            self.args += ["-i", str(Path(identity).resolve())]
        command = "python3 -u -c " + shlex.quote(REMOTE_LEASE) + " " + expected + " " + str(ttl)
        self.args += [target, command]
        self.out, self.expected, self.ttl = out, expected, ttl
        self.proc = None
        self.err = None

    def __enter__(self):
        self.err = (self.out / "lease-stderr.log").open("w", encoding="utf-8")
        self.proc = subprocess.Popen(self.args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self.err, text=True, encoding="utf-8")
        ready = queue.Queue()
        threading.Thread(target=lambda: ready.put(self.proc.stdout.readline()), daemon=True).start()
        try:
            line = ready.get(timeout=35)
            record = json.loads(line)
            if record != {"event": "locked", "release": self.expected}:
                raise RuntimeError("Unexpected lease response")
            self.deadline = time.monotonic() + self.ttl
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise RuntimeError("Cannot acquire production acceptance lock; see lease-stderr.log")

    def check(self):
        if self.proc.poll() is not None or time.monotonic() >= self.deadline:
            raise RuntimeError("Production acceptance lock lost or expired; results are not valid")

    def __exit__(self, *args):
        if self.proc:
            with contextlib.suppress(OSError):
                self.proc.stdin.close()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                self.proc.wait(timeout=10)
        if self.err:
            self.err.close()

def run_step(name, cmd, cwd, env, out, lease=None, timeout=1200):
    print(f"[START] {name}", flush=True)
    start = time.monotonic()
    log = out / (name + ".log")
    with log.open("w", encoding="utf-8") as stream:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
        try:
            while proc.poll() is None:
                if lease:
                    lease.check()
                if time.monotonic() - start > timeout:
                    raise TimeoutError(name + " exceeded its time limit")
                time.sleep(.25)
        except BaseException:
            # Terminate only the process tree created by this check.
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                # All descendants share this new process group. Stop them before
                # releasing the remote lease, even if the CLI itself exits first.
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGTERM)
                time.sleep(.2)
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=15)
            raise
    result = {"name": name, "exit_code": proc.returncode, "seconds": round(time.monotonic()-start, 2),
              "log": str(log), "passed": proc.returncode == 0}
    print(f"[{'PASS' if result['passed'] else 'FAIL'}] {name} ({result['seconds']}s)", flush=True)
    if not result["passed"]:
        print(clean_error(log.read_text(encoding="utf-8", errors="replace")), flush=True)
    return result

def validate_browser_report(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    stats = data["stats"]
    if stats.get("unexpected", 0) or stats.get("flaky", 0) or stats.get("skipped", 0) or not stats.get("expected", 0):
        raise RuntimeError("Browser suite has failures, retries, skipped tests or no tests: " + str(stats))
    return stats

def ledger_status(write_markdown=False):
    data = json.loads((ROOT / "docs/quality/feedback-ledger.json").read_text(encoding="utf-8"))
    ids = [item["id"] for item in data["issues"]]
    if len(ids) != 25 or len(set(ids)) != 25:
        raise ValueError("Original feedback must map to exactly 25 unique entries")
    counts = {}
    for item in data["issues"]:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
        if item["status"] == "verified" and (not item["evidence"] or not item["checked_commit"]):
            raise ValueError(item["id"] + " has no acceptance evidence")
        print(f"{item['id']} [{item['status']}] {item['title']}")
    print(json.dumps(counts, ensure_ascii=False))
    images = {image for item in data["issues"] for image in item["source_images"]}
    if len(images) != data["source_image_count"]:
        raise ValueError("Feedback screenshots are missing from the ledger")
    for item in data["issues"]:
        for reference in item["test_refs"]:
            if not (ROOT / reference).is_file():
                raise ValueError(item["id"] + " has a missing test/document reference: " + reference)
    if write_markdown:
        labels = {"verified": "已验证（见范围）", "partial": "部分解决", "open": "仍未解决", "unverified": "证据不足"}
        lines = ["# 原始用户反馈逐项台账", "", "原文 25 项、29 张截图。状态以约定验收范围为准；不以测试数量代替关闭问题。", "",
                 "源文件 SHA-256：" + data["source_sha256"], "",
                 "|编号|原始问题|状态|", "|---|---|---|"]
        for item in data["issues"]:
            lines.append("|" + item["id"] + "|" + item["title"] + "|" + labels[item["status"]] + "|")
        for item in data["issues"]:
            lines += ["", "## " + item["id"] + " " + item["title"], "",
                      "- 原文位置：段落 " + ", ".join(map(str, item["source_paragraphs"])) + "；截图 " + ", ".join(item["source_images"]),
                      "- 验收要求：" + item["acceptance"],
                      "- 原因/判断：" + item.get("cause", "待核验"),
                      "- 状态：" + labels[item["status"]] + "；版本：" + (item["checked_commit"] or "待复核"),
                      "- 证据：" + ("；".join(item["evidence"]) or "待补"),
                      "- 限制：" + item["limitations"],
                      "- 下一步：" + item["next_action"],
                      "- 固定检查：" + ", ".join(item["test_refs"])]
        for finding in data.get("new_findings", []):
            lines += ["", "## " + finding["id"] + " 本轮新增：" + finding["title"], "",
                      "- 状态：" + labels[finding["status"]] + "（不混入原文 25 项计数）",
                      "- 版本：" + finding["checked_commit"],
                      "- 证据：" + "；".join(finding["evidence"]),
                      "- 下一步：" + finding["next_action"]]
        (ROOT / "docs/quality/feedback-ledger.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return data

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["status", "local", "live"])
    p.add_argument("--python", default=os.environ.get("PLAYWRIGHT_PYTHON", sys.executable))
    p.add_argument("--node", default=shutil.which("node") or "node")
    p.add_argument("--markdown", action="store_true", help="status: refresh the readable ledger from JSON")
    p.add_argument("--suite", choices=["feedback", "trusted-course", "english-scenes", "english-generation", "materials", "course-study", "reading-training"], default="feedback")
    p.add_argument("--scope", choices=["all", "backend", "ui"], default="all")
    p.add_argument("--backend-port", type=int, default=18480)
    p.add_argument("--frontend-port", type=int, default=13480)
    p.add_argument("--base-url", default="https://47.121.24.54")
    p.add_argument("--ssh-target", default="root@47.121.24.54")
    p.add_argument("--identity", default=os.environ.get("ACCEPTANCE_SSH_KEY"))
    p.add_argument("--expected-commit")
    p.add_argument("--lease-seconds", type=int, default=1200)
    p.add_argument("--allow-self-signed", action="store_true")
    p.add_argument("--allow-live-models", action="store_true")
    args = p.parse_args(argv)
    if args.mode == "status":
        ledger_status(args.markdown)
        return 0
    if args.mode == "live" and args.suite not in {"materials", "course-study", "reading-training"} and not args.allow_live_models:
        p.error("live makes fixed synthetic QA requests to the configured model; add --allow-live-models")
    if args.mode == "live" and not args.expected_commit:
        p.error("live requires --expected-commit so acceptance is bound to one deployed version")
    out = ROOT / ".tmp/acceptance" / (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + args.mode)
    out.mkdir(parents=True, exist_ok=False)
    report = {"mode": args.mode, "commit": revision(), "started": dt.datetime.now(dt.timezone.utc).isoformat(),
              "steps": [], "passed": False, "output": str(out)}
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PLAYWRIGHT_PYTHON=str(Path(args.python).resolve()))
    env["PLAYWRIGHT_JSON_OUTPUT_NAME"] = str(out / "playwright.json")
    env["PLAYWRIGHT_OUTPUT_DIR"] = str(out / "browser")
    cli = str(ROOT / "frontend/node_modules/@playwright/test/cli.js")
    def save_report():
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    save_report()
    def step(name, cmd, cwd=ROOT, lease=None):
        result = run_step(name, cmd, cwd, env, out, lease)
        report["steps"].append(result)
        save_report()
        if not result["passed"]:
            raise RuntimeError(name + " failed")
    try:
        if args.mode == "local":
            for key in ["PLAYWRIGHT_BASE_URL", "PLAYWRIGHT_REAL_MODE", "ACCEPTANCE_EXPECTED_COMMIT"]:
                env.pop(key, None)
            env.update(DEMO_MODE="true", AUTH_REQUIRED="false",
                       DATABASE_URL="sqlite:///" + (out / "backend.db").as_posix())
            for key in ["SPARK_API_PASSWORD", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "KIMI_API_KEY"]:
                env[key] = ""
            step("runner-tests", [args.python, "-m", "unittest", "discover", "-s", "scripts/tests", "-v"])
            if args.scope in {"all", "backend"}:
                step("backend", [args.python, "-m", "pytest", "backend/tests", "-q"])
            if args.scope in {"all", "ui"}:
                env.update(PLAYWRIGHT_BACKEND_PORT=str(args.backend_port),
                           PLAYWRIGHT_FRONTEND_PORT=str(args.frontend_port), PLAYWRIGHT_PRODUCTION="true")
                step("build", [args.node, "node_modules/next/dist/bin/next", "build", "--webpack"], ROOT / "frontend")
                step("browser", [args.node, cli, "test", "--config", "frontend/playwright.config.ts",
                     *["frontend/e2e/" + name + ".spec.ts" for name in (["study-materials"] if args.suite == "materials" else ["course-study"] if args.suite == "course-study" else ["reading-training", "course-study"] if args.suite == "reading-training" else UI_SPECS)], "--reporter=list,json"])
                report["browser"] = validate_browser_report(out / "playwright.json")
        else:
            env.update(PLAYWRIGHT_BASE_URL=args.base_url, PLAYWRIGHT_REAL_MODE="1",
                       ACCEPTANCE_EXPECTED_COMMIT=args.expected_commit,
                       ACCEPTANCE_ALLOW_SELF_SIGNED="1" if args.allow_self_signed else "0")
            with ReleaseLease(args.ssh_target, args.identity, args.expected_commit, args.lease_seconds, out) as lease:
                report["release_lock"] = {"expected_commit": args.expected_commit, "ttl_seconds": args.lease_seconds}
                print("[LOCKED] auto-deploy is excluded during this acceptance window", flush=True)
                step("live-browser", [args.node, cli, "test", "--config", "frontend/playwright.config.ts",
                     "frontend/e2e/" + {"reading-training": "reading-training.spec.ts", "course-study": "course-study.spec.ts", "materials": "study-materials.spec.ts", "trusted-course": "trusted-course-library.spec.ts", "english-scenes": "english-scenes.spec.ts", "english-generation": "english-generation-live.spec.ts", "feedback": "feedback-live.spec.ts"}[args.suite], "--reporter=list,json"], lease=lease)
                lease.check()
                report["browser"] = validate_browser_report(out / "playwright.json")
        report["passed"] = True
    except (Exception, KeyboardInterrupt) as exc:
        report["error"] = clean_error(str(exc))
        print("[FAILED] " + report["error"], flush=True)
    finally:
        report["finished"] = dt.datetime.now(dt.timezone.utc).isoformat()
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Evidence: " + str(out / "report.json"), flush=True)
    return 0 if report["passed"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
