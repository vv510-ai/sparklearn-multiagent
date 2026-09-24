import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("acceptance", Path(__file__).parents[1] / "acceptance.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class AcceptanceGuardTests(unittest.TestCase):
    def test_skipped_and_empty_suites_never_count_as_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "report.json"
            for stats in [{"expected": 0}, {"expected": 3, "skipped": 1},
                          {"expected": 3, "unexpected": 1}, {"expected": 3, "flaky": 1}]:
                p.write_text(json.dumps({"stats": stats}), encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    module.validate_browser_report(p)
            p.write_text(json.dumps({"stats": {"expected": 3, "skipped": 0}}), encoding="utf-8")
            self.assertEqual(module.validate_browser_report(p)["expected"], 3)

    def test_release_lock_rejects_shell_injection_and_ambiguous_revision(self):
        for target, revision in [("host; touch /tmp/x", "a"*40), ("-oProxyCommand=x", "a"*40), ("root@host", "HEAD")]:
            with self.assertRaises(ValueError):
                module.ReleaseLease(target, None, revision, 60, Path("."))

    def test_sensitive_headers_do_not_enter_console_error_summary(self):
        summary = module.clean_error("failure\n  Cookie: secret\nAuthorization: secret\nplain")
        self.assertNotIn("secret", summary)
        self.assertIn("plain", summary)

if __name__ == "__main__":
    unittest.main()
