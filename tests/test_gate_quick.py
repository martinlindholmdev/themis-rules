"""Purpose: prove the quick tier of the pre-push gate: when only the files the
owner lists under test.docs_quick changed since a full run, test.quick runs in
place of the suite, and every other case still runs the whole suite.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: every repository is a throwaway under a TemporaryDirectory with a
counting test command, so a marker file shows whether the suite ran; the quick
command leaves its own marker; nothing touches this checkout.
Never change without a decision: the quick-tier PASS wording and the rule that
a quick pass writes no receipt, which readers of a push log depend on.
"""

import json
import subprocess
import sys
import unittest

from test_gate import GateCase, gate, sh

QUICK_OK = [sys.executable, "-c", "open('quick.log', 'a').write('q')"]
QUICK_FAIL = [sys.executable, "-c", "open('quick.log', 'a').write('q'); raise SystemExit(3)"]
QUICK_SLOW = [sys.executable, "-c", "import time; open('quick.log', 'a').write('q'); time.sleep(60)"]

# name, settings, files changed after the full run, expected exit status,
# suite runs in all, quick runs in all, a phrase the output must hold
ROWS = [
    ("only a listed file runs quick, not the suite", {"quick": QUICK_OK, "docs_quick": ["spec.md"]},
     {"spec.md": "words\n"}, 0, 1, 1, "quick tier"),
    ("a failing quick fails the push", {"quick": QUICK_FAIL, "docs_quick": ["spec.md"]},
     {"spec.md": "words\n"}, 1, 1, 1, "exited with status 3"),
    ("a timing-out quick fails the push", {"quick": QUICK_SLOW, "docs_quick": ["spec.md"], "timeout": 3},
     {"spec.md": "words\n"}, 1, 1, 1, "timed out"),
    ("a listed file beside an unlisted one runs the suite", {"quick": QUICK_OK, "docs_quick": ["spec.md"]},
     {"spec.md": "words\n", "notes.txt": "x\n"}, 0, 2, 0, "gate PASS"),
    ("a list edited in the same change is ignored", {"quick": QUICK_OK, "docs_quick": ["spec.md"]},
     {"notes.txt": "x\n", "themis.json": "WIDEN"}, 0, 2, 0, "gate PASS"),
    ("docs_only wins when a path is in both lists",
     {"quick": QUICK_OK, "docs_quick": ["spec.md"], "docs_only": ["spec.md"]},
     {"spec.md": "words\n"}, 0, 1, 0, "reused"),
    ("docs_quick without quick is a configuration problem", {"docs_quick": ["spec.md"]},
     {"spec.md": "words\n"}, 1, 0, 0, "test.docs_quick needs test.quick"),
]


class QuickTier(GateCase):
    def pre_push(self, repo):
        line = "refs/heads/work %s refs/heads/main %s\n" % (sh(repo, "rev-parse", "HEAD"), "0" * 40)
        return subprocess.run([sys.executable, str(repo / "tools" / "themis.py"), "gate", "--pre-push"],
                              cwd=str(repo), input=line, capture_output=True, text=True)

    def marks(self, repo, name):
        path = repo / name
        return len(path.read_text()) if path.exists() else 0

    def test_quick_runs_for_listed_files_only_and_the_suite_for_everything_else(self):
        for name, settings, files, status, suite_runs, quick_runs, phrase in ROWS:
            with self.subTest(name):
                repo = self.counting_repo()
                (repo / ".gitignore").write_text("ran.log\nquick.log\n__pycache__/\n", encoding="utf-8")
                self.set_test(repo, **settings)
                self.gate(repo)
                for rel, text in files.items():
                    if text == "WIDEN":
                        data = json.loads((repo / rel).read_text(encoding="utf-8"))
                        data["test"]["docs_quick"] = ["spec.md", "notes.txt"]
                        text = json.dumps(data)
                    self.write(repo, rel, text)
                self.commit(repo, "change")
                done = self.pre_push(repo)
                self.assertEqual(done.returncode, status, done.stdout + done.stderr)
                self.assertIn(phrase, done.stdout)
                self.assertEqual(self.marks(repo, "ran.log"), suite_runs)
                self.assertEqual(self.marks(repo, "quick.log"), quick_runs)

    def test_no_receipt_runs_the_suite_and_the_settings_hash_is_unchanged_when_the_key_is_unset(self):
        repo = self.counting_repo()
        self.set_test(repo, quick=QUICK_OK, docs_quick=["spec.md"])
        self.write(repo, "spec.md", "words\n")
        self.commit(repo, "doc")
        done = self.pre_push(repo)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("quick tier", done.stdout)
        raw = json.loads((repo / "themis.json").read_text(encoding="utf-8"))["test"]
        with_key, _ = gate.parse_test_config(raw)
        without_key, _ = gate.parse_test_config({k: v for k, v in raw.items() if k not in ("quick", "docs_quick")})
        no_list, _ = gate.parse_test_config({k: v for k, v in raw.items() if k != "docs_quick"})
        self.assertEqual(gate.settings_hash(no_list), gate.settings_hash(without_key))
        self.assertNotEqual(gate.settings_hash(with_key), gate.settings_hash(no_list))


if __name__ == "__main__":
    unittest.main()
