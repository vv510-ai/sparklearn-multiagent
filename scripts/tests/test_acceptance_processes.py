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
                marker, started = folder / "must-not-appear", folder / "started"
                child = ("from pathlib import Path; import time; "
                         + "Path(" + repr(str(started)) + ").write_text('started'); "
                         + "time.sleep(2); Path(" + repr(str(marker)) + ").write_text('unsafe')")
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
                time.sleep(2.1)
                self.assertFalse(marker.exists(), "Child continued after acceptance lost its lock")

if __name__ == "__main__":
    unittest.main()
