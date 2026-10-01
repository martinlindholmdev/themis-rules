"""Purpose: the baseline only ever goes down — `rebaseline` lowers numbers
and drops entries for files that shrank under the limit or were deleted,
refuses (writing nothing) if it would raise any number or add an entry,
and the commit of a lowered baseline passes the pre-commit check.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: throwaway git repos under a TemporaryDirectory.
Never change without a decision: no override exists, by design.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEMIS = ROOT / "tools" / "themis.py"


def big(lines: int) -> str:
    return "\n".join(["def big():"] + ["    x = %d" % i for i in range(lines - 2)] + ["    return x"]) + "\n"


def git(root, *args):
    return subprocess.run(["git", "-C", str(root)] + list(args), check=True, capture_output=True, text=True)


def themis(root, *args):
    return subprocess.run([sys.executable, str(root / "tools" / "themis.py")] + list(args),
                          cwd=str(root), capture_output=True, text=True)


class RebaselineOnlyLowersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "t")
        (self.root / "tools").mkdir()
        (self.root / "tools" / "themis.py").write_bytes(THEMIS.read_bytes())
        (self.root / "themis.json").write_text('{"version": "v3"}\n', encoding="utf-8")
        (self.root / "main.py").write_text(big(900), encoding="utf-8")
        self.assertEqual(themis(self.root, "rebaseline").returncode, 0)  # first baseline: nothing to raise
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "base", "--no-verify")
        self.baseline = self.root / "themis-baseline.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_rebaseline_after_a_file_grew_refuses_and_writes_nothing(self):
        before = self.baseline.read_text(encoding="utf-8")
        (self.root / "main.py").write_text(big(950), encoding="utf-8")
        result = themis(self.root, "rebaseline")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("refusing", result.stdout)
        self.assertEqual(self.baseline.read_text(encoding="utf-8"), before)

    def test_rebaseline_after_a_file_shrank_lowers_the_number_and_the_commit_passes(self):
        (self.root / "main.py").write_text(big(850), encoding="utf-8")
        self.assertEqual(themis(self.root, "rebaseline").returncode, 0)
        self.assertEqual(json.loads(self.baseline.read_text(encoding="utf-8"))["files"]["main.py"], 850)
        git(self.root, "add", "-A")
        self.assertEqual(themis(self.root, "check", "--staged").returncode, 0)

    def test_rebaseline_after_a_file_dropped_under_the_limit_drops_its_entry(self):
        (self.root / "main.py").write_text(big(100), encoding="utf-8")
        self.assertEqual(themis(self.root, "rebaseline").returncode, 0)
        self.assertEqual(json.loads(self.baseline.read_text(encoding="utf-8"))["files"], {})

    def test_a_new_oversized_file_cannot_be_baselined(self):
        (self.root / "other.py").write_text(big(900), encoding="utf-8")
        result = themis(self.root, "rebaseline")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertNotIn("other.py", self.baseline.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
