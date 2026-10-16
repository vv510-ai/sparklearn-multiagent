"""Keep launcher records safe across Windows permission boundaries and PID reuse."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("native_launcher", Path(__file__).parents[1] / "mac/native.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def record(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "WINDOWS", True)
    monkeypatch.setattr(native, "STATE", tmp_path)
    pid = native.pid_file("backend")
    pid.parent.mkdir()
    pid.write_text("12345")
    pid.with_suffix(".json").write_text(json.dumps({"pid": 12345, "created": "original"}))
    return pid


def test_protected_process_does_not_spawn_or_overwrite_its_record(monkeypatch, tmp_path):
    pid = record(monkeypatch, tmp_path)
    def denied(_pid):
        raise PermissionError("Windows denied process access")
    monkeypatch.setattr(native, "windows_process_stamp", denied)
    monkeypatch.setattr(native.subprocess, "Popen", lambda *a, **kw: pytest.fail("must not spawn"))
    with pytest.raises(SystemExit, match="denied process access"):
        native.spawn("backend", ["python"], tmp_path)
    assert pid.read_text() == "12345"
    assert json.loads(pid.with_suffix(".json").read_text())["created"] == "original"


def test_reused_pid_is_not_terminated(monkeypatch, tmp_path):
    pid = record(monkeypatch, tmp_path)
    monkeypatch.setattr(native, "SERVICES", ("backend",))
    monkeypatch.setattr(native, "windows_process_stamp", lambda _pid: "different-process")
    monkeypatch.setattr(native.subprocess, "run", lambda *a, **kw: pytest.fail("must not terminate"))
    native.stop()
    assert not pid.exists()
