"""Purpose: a baseline entry may move with an over-limit Python function that
moves unchanged to another file in the same change; any other new or raised
entry is still refused, through both the staged and the range check.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: throwaway git repos under a TemporaryDirectory; nothing outside it.
Never change without a decision: the move needs identical text (only common
indentation and trailing whitespace ignored) and no definition left behind.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from headers import PY

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ("themis.py", "themis_lang.py", "themis_scan.py", "themis_gate.py")


def long_function(lines: int = 120, comment: str = "keeps the running total", text: str = "total") -> str:
    body = ["    # %s" % comment, "    label = %r" % text]
    body += ["    x = %d" % i for i in range(lines - 4)]
    return "\n".join(["def big():"] + body + ["    return label, x"]) + "\n"


def git(root, *args):
    return subprocess.run(["git", "-C", str(root)] + list(args), check=True, capture_output=True, text=True)


class MovedEntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "t")
        (self.root / "tools").mkdir()
        for name in TOOLS:
            (self.root / "tools" / name).write_bytes((ROOT / "tools" / name).read_bytes())
        self.write("themis.json", '{"version": "v3"}\n')
        self.write("a.py", PY + "\n\n" + long_function() + "\n\ndef small():\n    return 1\n")
        self.baseline({"a.py": {"big": 120}})
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "base", "--no-verify")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        (self.root / rel).write_text(text, encoding="utf-8")

    def baseline(self, functions):
        self.write("themis-baseline.json", json.dumps({"files": {}, "functions": functions}, indent=1) + "\n")

    def stage(self, *paths):
        git(self.root, "add", "--", *paths)

    def themis(self, *args):
        return subprocess.run([sys.executable, str(self.root / "tools" / "themis.py")] + list(args),
                              cwd=str(self.root), capture_output=True, text=True)

    def move(self, b_text, a_text="\n\ndef small():\n    return 1\n", functions=None):
        """Writes b.py, rewrites a.py, moves the entry to b.py and stages all three."""
        self.write("b.py", PY + "\n\n" + b_text)
        self.write("a.py", PY + "from b import big\n" + a_text)
        self.baseline(functions or {"b.py": {"big": 120}})
        self.stage("a.py", "b.py", "themis-baseline.json")

    def assert_refused(self, result, entry="functions b.py/big: new entry"):
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("baseline only goes down", result.stdout)
        self.assertIn(entry, result.stdout)

    def test_an_unchanged_move_carrying_its_entry_passes(self):
        self.move(long_function())
        result = self.themis("check", "--staged")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_a_move_with_one_changed_token_is_refused(self):
        self.move(long_function().replace("x = 7\n", "x = 8\n"))
        self.assert_refused(self.themis("check", "--staged"))

    def test_a_move_with_a_reworded_comment_or_string_is_refused(self):
        self.move(long_function(comment="keeps the sum"))
        self.assert_refused(self.themis("check", "--staged"))
        self.move(long_function(text="sum"))
        self.assert_refused(self.themis("check", "--staged"))

    def test_a_copy_that_leaves_the_definition_behind_is_refused_staged_and_in_a_range(self):
        self.move(long_function(), a_text="\n\n" + long_function(30) + "\n\ndef small():\n    return 1\n")
        self.assert_refused(self.themis("check", "--staged"))
        git(self.root, "commit", "-q", "-m", "copy", "--no-verify")
        self.assert_refused(self.themis("check", "--range", "HEAD~1...HEAD"))

    def test_a_new_long_function_under_an_old_name_is_refused(self):
        other = "def big():\n" + "".join("    y = %d\n" % i for i in range(118)) + "    return y\n"
        self.move(other)
        self.assert_refused(self.themis("check", "--staged"))

    def test_one_old_entry_cannot_pay_for_two_new_ones(self):
        self.write("c.py", PY + "\n\n" + long_function())
        self.stage("c.py")
        self.move(long_function(), functions={"b.py": {"big": 120}, "c.py": {"big": 120}})
        self.assert_refused(self.themis("check", "--staged"), entry="big: new entry")

    def test_two_sources_find_their_destinations_in_either_baseline_order(self):
        self.write("d.py", PY + "\n\n" + long_function())
        self.baseline({"a.py": {"big": 130}, "d.py": {"big": 120}})
        self.stage("d.py", "themis-baseline.json")
        git(self.root, "commit", "-q", "-m", "two sources", "--no-verify")
        base = git(self.root, "rev-parse", "HEAD").stdout.strip()
        for order in ((("b.py", 120), ("c.py", 130)), (("c.py", 130), ("b.py", 120))):
            with self.subTest(order=order):
                git(self.root, "reset", "-q", "--hard", base)
                for rel in ("b.py", "c.py"):
                    self.write(rel, PY + "\n\n" + long_function())
                for rel in ("a.py", "d.py"):
                    self.write(rel, PY + "\n\ndef small():\n    return 1\n")
                self.baseline({rel: {"big": size} for rel, size in order})
                self.stage("a.py", "b.py", "c.py", "d.py", "themis-baseline.json")
                staged = self.themis("check", "--staged")
                git(self.root, "commit", "-q", "-m", "split", "--no-verify")
                ranged = self.themis("check", "--range", "HEAD~1...HEAD")
                self.assertEqual((staged.returncode, ranged.returncode), (0, 0), staged.stdout + ranged.stdout)

    def test_a_move_that_keeps_the_old_entry_is_refused(self):
        self.move(long_function(), functions={"a.py": {"big": 120}, "b.py": {"big": 120}})
        self.assert_refused(self.themis("check", "--staged"))

    def test_a_move_that_raises_the_size_is_refused(self):
        self.move(long_function(), functions={"b.py": {"big": 125}})
        self.assert_refused(self.themis("check", "--staged"))


if __name__ == "__main__":
    unittest.main()
