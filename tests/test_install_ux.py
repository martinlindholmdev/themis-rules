"""Purpose: cover the M4 release-test usability findings: Ctrl-D at a
question must not crash (finding 5), a y/n reply is normalised before
being written into AGENTS.md (finding 6), a brand-new vendored file is
summarised rather than shown as a ~600-line diff (finding 7), the fresh
baseline is part of the shown plan, not a silent write after (finding 8
/ Astra [1]), and a secret already sitting in an existing file's context
lines is never echoed into a diff (Fable finding 8).
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: builds throwaway repos under a TemporaryDirectory.
Never change without a decision: which reply strings count as yes/no.
"""

import argparse
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.py"

spec = importlib.util.spec_from_file_location("install", ROOT / "install.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(path), check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)


class EofAndNormalisationTests(unittest.TestCase):
    def test_eof_at_a_question_raises_cancelled_not_eoferror(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            init_repo(repo)
            (repo / "main.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)

            args = argparse.Namespace(answers=None, defaults=False)
            with mock.patch("sys.stdin.isatty", return_value=True), \
                 mock.patch("builtins.input", side_effect=EOFError):
                with self.assertRaises(install.Cancelled):
                    install.resolve_answers(repo, args)

    def test_a_bare_y_reply_is_stored_as_yes(self):
        self.assertEqual(install._normalise_yes_no("y", "no"), "yes")
        self.assertEqual(install._normalise_yes_no("N", "yes"), "no")
        self.assertEqual(install._normalise_yes_no("", "no"), "no")


class PlanPresentationTests(unittest.TestCase):
    def test_a_brand_new_vendored_file_is_summarised_with_a_hash_not_a_full_diff(self):
        source = (ROOT / "tools" / "themis.py").read_text(encoding="utf-8")
        change = install.Change("tools/themis.py", None, source)
        with mock.patch("builtins.print") as mock_print:
            install.print_plan([change])
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list)
        self.assertIn("identical to Themis v3", printed)
        self.assertIn("sha256", printed)
        self.assertNotIn("+++ b/tools/themis.py", printed)

    def test_the_fresh_baseline_is_part_of_the_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            init_repo(repo)
            (repo / "main.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)
            changes = install.plan_core_files(repo)
            self.assertTrue(any(c.rel == "themis-baseline.json" for c in changes))

    def test_a_secret_in_an_existing_files_context_lines_is_redacted(self):
        fake_key = "openai-api-key: " + "sk-1234567890abcdef1234"  # themis: allow-secret
        old = "read: CONVENTIONS.md\n%s\nverbose: true\n" % fake_key
        new = "read: CONVENTIONS.md\n  - AGENTS.md\n%s\nverbose: true\n" % fake_key
        change = install.Change(".aider.conf.yml", old, new)
        with mock.patch("builtins.print") as mock_print:
            install.print_plan([change])
        printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list)
        self.assertNotIn(fake_key, printed)
        self.assertIn("redacted", printed)


if __name__ == "__main__":
    unittest.main()
