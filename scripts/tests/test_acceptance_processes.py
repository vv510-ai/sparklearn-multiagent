import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from test_acceptance import module

class ProcessCleanupTests(unittest.TestCase):
    def test_timeout_and_lost_lock_stop_the_child_before_returning(self):
        for mode in ("timeout", "lost-lock", "interrupt"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                marker, started = folder / "heartbeat", folder / "started"
                child = ("from pathlib import Path; import time; "
                         + "Path(" + repr(str(started)) + ").write_text('started'); "
                         + "marker=Path(" + repr(str(marker)) + "); "
                         + "\nwhile True:\n marker.write_text(str(time.monotonic_ns())); time.sleep(.05)")
                parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); time.sleep(30)"
                class LostLease:
                    def check(self):
                        if started.exists():
                            if mode == "interrupt":
                                raise KeyboardInterrupt()
                            raise RuntimeError("synthetic lock loss")
                with self.assertRaises((TimeoutError, RuntimeError, KeyboardInterrupt)):
                    module.run_step("cleanup-" + mode, [sys.executable, "-c", parent], folder,
                                    dict(os.environ), folder, None if mode == "timeout" else LostLease(),
                                    timeout=1)
                self.assertTrue(started.exists(), "The child must start before the cleanup can be tested")
                # Windows taskkill may itself take longer than a fixed marker delay.
                # The lease must remain held until cleanup returns; after that return
                # the child must never write again, regardless of termination latency.
                stopped = marker.read_bytes() if marker.exists() else None
                time.sleep(.5)
                after = marker.read_bytes() if marker.exists() else None
                self.assertEqual(after, stopped, "Child continued after cleanup returned")

if __name__ == "__main__":
    unittest.main()
