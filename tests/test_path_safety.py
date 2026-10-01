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

import argparse
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("install", ROOT / "install.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    (root / "main.py").write_text("def f():\n    return 1\n", encoding="utf-8")


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

    def test_a_symlink_resolving_inside_the_repo_is_still_rejected(self):
        """Fable's re-check, must-fix 5: tools/themis.py -> ../README.md
        resolves back inside the repo, so the old containment-only check
        accepted it — and the write landed on README.md, not themis.py."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "repo"
            root.mkdir()
            (root / "README.md").write_text("original readme\n", encoding="utf-8")
            (root / "tools").mkdir()
            (root / "tools" / "themis.py").symlink_to(root / "README.md")
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
            self.assertIsNone(install.read_text(root, "CLAUDE.md"))

            # applying a plan never writes through the symlink
            change = install.Change("CLAUDE.md", None, "@AGENTS.md\n")
            failures, failed_rels = install.apply_plan(root, [change])
            self.assertTrue(failures, "writing through a symlink should have been refused")
            self.assertIn("CLAUDE.md", failed_rels)
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


class PlanTimeRejectionTests(unittest.TestCase):
    """Fable's re-check, follow-up 7: an escaping path must refuse the
    whole install before anything is written, not fail partway through
    applying it with themis.json and AGENTS.md already on disk — and a
    parent-symlinked tools/ must refuse cleanly, never crash."""

    def test_an_escaping_baseline_path_refuses_before_anything_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            (root / "themis.json").write_text(json.dumps({"baseline_path": "../escaped.json"}), encoding="utf-8")
            args = argparse.Namespace(answers=None, defaults=True, dry_run=False, yes=True)
            rc = install.do_install(root, args)
            self.assertNotEqual(rc, 0)
            self.assertFalse((root / "AGENTS.md").exists())
            self.assertFalse((Path(tmp).parent / "escaped.json").exists())

    def test_a_parent_symlinked_tools_directory_never_crashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            (root / "tools").symlink_to(root / "nonexistent-target")
            args = argparse.Namespace(answers=None, defaults=True, dry_run=False, yes=True)
            rc = install.do_install(root, args)  # must not raise
            self.assertEqual(rc, 0)


class SymlinkAwareConfigReadsTests(unittest.TestCase):
    """Fable's re-check, follow-up 6: lefthook.yml, .pre-commit-config.yaml
    and themis.json must be read the same symlink-aware way as every
    other tracked file install.py touches — a dry run must never print an
    external file's content just because a config name pointed at it."""

    def test_a_symlinked_lefthook_yml_is_never_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "repo"
            root.mkdir()
            _init_repo(root)
            sentinel = tmp / "sentinel.yml"
            sentinel.write_text("SECRET EXTERNAL CONTENT\n", encoding="utf-8")
            (root / "lefthook.yml").symlink_to(sentinel)
            changes, _ = install.plan_hook(root)
            self.assertFalse(any("SECRET EXTERNAL" in str(c.new) for c in changes))

    def test_a_symlinked_themis_json_is_never_read_as_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "repo"
            root.mkdir()
            _init_repo(root)
            sentinel = tmp / "sentinel.json"
            sentinel.write_text("not valid json at all", encoding="utf-8")
            (root / "themis.json").symlink_to(sentinel)
            # must not raise json.JSONDecodeError trying to parse the
            # sentinel's content as this repo's own config
            changes = install.plan_core_files(root)
            self.assertFalse(any("not valid json" in str(c.old) for c in changes))

    def test_a_parent_symlinked_tools_directory_is_never_read_through(self):
        """Astra's re-check [1]: read_text checked only the leaf, so
        tools -> outside still disclosed the external file's content
        when comparing it against our own vendored tools/themis.py."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "repo"
            root.mkdir()
            outside = tmp / "outside"
            outside.mkdir()
            (outside / "themis.py").write_text("SECRET EXTERNAL PAYLOAD\n", encoding="utf-8")
            (root / "tools").symlink_to(outside)
            self.assertIsNone(install.read_text(root, "tools/themis.py"))

    def test_a_symlinked_legacy_baseline_is_never_copied(self):
        """Astra's re-check [1]: the legacy agent-rules-baseline.json
        migration copied a symlink's target bytes straight into the new
        themis-baseline.json."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "repo"
            root.mkdir()
            _init_repo(root)
            sentinel = tmp / "sentinel.json"
            sentinel.write_text("SECRET EXTERNAL BASELINE\n", encoding="utf-8")
            (root / "agent-rules-baseline.json").symlink_to(sentinel)
            changes = install.plan_core_files(root)
            self.assertFalse(any("SECRET EXTERNAL" in str(c.new) for c in changes))


if __name__ == "__main__":
    unittest.main()
