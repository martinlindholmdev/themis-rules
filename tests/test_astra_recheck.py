"""Purpose: reproduce and guard against GPT-6 Astra's re-check findings
[2] (a path carrying a newline could turn a printed "# this failed"
comment into a second, unprefixed, executable line if the whole block
were pasted into a shell) and [6] (uninstall's final directory cleanup
followed a symlinked tools/ and rmdir'd an external, unrelated
directory).
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: builds throwaway repos under a TemporaryDirectory; the
external directory [6] protects lives alongside it, never inside it.
Never change without a decision: control characters are rejected before
any other safe_path check, so the rejection message never echoes one.
"""

import argparse
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("install", ROOT / "install.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


def init_repo(root: Path) -> None:
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    (root / "main.py").write_text("def f():\n    return 1\n", encoding="utf-8")


class NewlineInjectionTests(unittest.TestCase):
    def test_a_newline_in_a_path_is_rejected(self):
        with self.assertRaises(install.PathEscapesRepo):
            install.safe_path(Path("/repo"), "evil\n$(touch PWNED)")

    def test_a_control_character_rejection_never_echoes_the_path(self):
        try:
            install.safe_path(Path("/repo"), "evil\n$(touch PWNED)")
            self.fail("should have raised")
        except install.PathEscapesRepo as exc:
            self.assertNotIn("\n", str(exc))
            self.assertNotIn("PWNED", str(exc))

    def test_print_commit_instructions_never_emits_an_unprefixed_second_line(self):
        """Defence in depth: even if an unsafe rel reached this far (it
        cannot, via safe_path), every physical line of a comment is
        '#'-prefixed on its own, so pasting the block runs nothing extra."""
        change = install.Change("../evil\n$(touch PWNED)", None, None)
        lines = []
        import builtins
        from unittest import mock
        with mock.patch.object(builtins, "print", side_effect=lambda *a: lines.append(" ".join(str(x) for x in a))):
            install.print_commit_instructions(Path("/tmp"), [change], "Install Themis")
        for line in lines:
            stripped = line.lstrip("\n").lstrip()
            if stripped:
                self.assertTrue(stripped.startswith("#") or stripped.startswith("Nothing")
                                 or stripped.startswith("git") or stripped.startswith("(.git"))

    def test_a_change_that_failed_to_apply_is_dropped_from_the_instructions(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "repo"
            root.mkdir()
            sentinel = tmp / "sentinel.txt"
            sentinel.write_text("DO NOT TOUCH\n", encoding="utf-8")
            (root / "CLAUDE.md").symlink_to(sentinel)
            change = install.Change("CLAUDE.md", None, "@AGENTS.md\n")
            failures, failed_rels = install.apply_plan(root, [change])
            self.assertIn("CLAUDE.md", failed_rels)
            lines = []
            import builtins
            from unittest import mock
            with mock.patch.object(builtins, "print",
                                    side_effect=lambda *a: lines.append(" ".join(str(x) for x in a))):
                install.print_commit_instructions(root, [change], "Install Themis", exclude=failed_rels)
            self.assertFalse(lines)  # nothing left to commit at all


class UninstallCleanupSymlinkTests(unittest.TestCase):
    def test_a_symlinked_tools_directory_is_never_rmdird_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "repo"
            root.mkdir()
            init_repo(root)
            external = tmp / "external"
            external.mkdir()
            (root / "tools").symlink_to(external)
            args = argparse.Namespace(answers=None, defaults=True, dry_run=False, yes=True)
            install.do_uninstall(root, args)  # nothing installed; must still not touch `external`
            self.assertTrue(external.is_dir())
            self.assertTrue((root / "tools").is_symlink())


if __name__ == "__main__":
    unittest.main()
