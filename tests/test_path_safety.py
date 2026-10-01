"""Purpose: reproduce and guard against GPT-6 Astra's finding [1]: a
tracked file that is itself a symlink to something outside the target
repo must never be read (its content shown in a diff), written through,
or deleted — and a hook config pointing outside the repo must be
refused rather than silently turned into a write there.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: every repo this test builds, and the external sentinel file
it protects, live under one TemporaryDirectory; never touches this repo.
Never change without a decision: `safe_path`'s three checks (absolute,
'..', resolved containment) and that `read_text` never follows a
symlinked leaf.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("install", ROOT / "install.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


class SafePathTests(unittest.TestCase):
    def test_absolute_path_is_rejected(self):
        with self.assertRaises(install.PathEscapesRepo):
            install.safe_path(Path("/repo"), "/etc/passwd")

    def test_dotdot_is_rejected(self):
        with self.assertRaises(install.PathEscapesRepo):
            install.safe_path(Path("/repo"), "../outside.txt")

    def test_a_symlinked_leaf_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "repo"
            root.mkdir()
            target = tmp / "outside.txt"
            target.write_text("x", encoding="utf-8")  # must exist: a dangling
            (root / "link.txt").symlink_to(target)     # link resolves oddly on Windows
            with self.assertRaises(install.PathEscapesRepo):
                install.safe_path(root, "link.txt")

    def test_a_symlinked_parent_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "repo"
            root.mkdir()
            outside = tmp / "outside"
            outside.mkdir()
            (root / "tools").symlink_to(outside)
            with self.assertRaises(install.PathEscapesRepo):
                install.safe_path(root, "tools/themis.py")

    def test_an_ordinary_path_is_accepted(self):
        root = Path("/repo")
        self.assertEqual(install.safe_path(root, "AGENTS.md"), root / "AGENTS.md")


class SymlinkedTrackedFileTests(unittest.TestCase):
    def test_a_symlinked_claude_md_is_never_read_or_written_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "repo"
            root.mkdir()
            sentinel = tmp / "external_sentinel.txt"
            sentinel.write_text("DO NOT TOUCH\n", encoding="utf-8")
            (root / "CLAUDE.md").symlink_to(sentinel)

            # planning never reads the sentinel's content
            self.assertIsNone(install.read_text(root / "CLAUDE.md"))

            # applying a plan never writes through the symlink
            change = install.Change("CLAUDE.md", None, "@AGENTS.md\n")
            failures = install.apply_plan(root, [change])
            self.assertTrue(failures, "writing through a symlink should have been refused")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "DO NOT TOUCH\n")

    def test_a_symlinked_file_is_never_deleted_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "repo"
            root.mkdir()
            sentinel = tmp / "external_sentinel.txt"
            sentinel.write_text("DO NOT TOUCH\n", encoding="utf-8")
            (root / "themis.json").symlink_to(sentinel)

            change = install.Change("themis.json", "whatever", None)
            install.apply_plan(root, [change])
            self.assertTrue(sentinel.exists())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "DO NOT TOUCH\n")


if __name__ == "__main__":
    unittest.main()
