"""Purpose: Aider's auto-commit runs `git commit --no-verify` unless
.aider.conf.yml sets git-commit-verify, so Themis creates that file when
Aider is in use (or --agents aider), marks every line it owns, and
uninstall removes exactly those lines — the whole file when nothing else
is left, and never a dangling `read:` header.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: throwaway repos under a TemporaryDirectory.
Never change without a decision: the `# themis` marker on each owned line.
"""

import argparse
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("install", ROOT / "install.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


def repo(tmp, files=None):
    root = Path(tmp)
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    (root / "main.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    for name, text in (files or {}).items():
        (root / name).write_text(text, encoding="utf-8")
    return root


class AiderAdapterTests(unittest.TestCase):
    def test_a_fresh_repo_with_aider_detected_gets_the_file_and_uninstall_removes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp, {".gitignore": ".aider*\n"})
            changes, _ = install.PLAN.plan_adapters(root)
            created = [c for c in changes if c.rel == ".aider.conf.yml"]
            self.assertEqual(len(created), 1)
            self.assertIn("git-commit-verify: true", created[0].new)
            install.PLAN.apply_plan(root, created)
            removal = [c for c in install.plan_remove_adapters(root) if c.rel == ".aider.conf.yml"]
            self.assertEqual(len(removal), 1)
            self.assertIsNone(removal[0].new)

    def test_the_agents_flag_creates_it_without_any_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            changes, notes = install.PLAN.plan_adapters(root, ("aider",))
            self.assertTrue(any(c.rel == ".aider.conf.yml" for c in changes))

    def test_without_detection_or_flag_nothing_is_created_and_nothing_is_said(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            changes, notes = install.PLAN.plan_adapters(root)
            self.assertFalse(any(c.rel == ".aider.conf.yml" for c in changes))
            self.assertFalse(any("Aider" in n for n in notes))

    def test_an_owner_file_holding_only_an_empty_read_key_is_never_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp, {".aider.conf.yml": "read:\n"})
            change = [c for c in install.PLAN.plan_adapters(root)[0] if c.rel == ".aider.conf.yml"][0]
            install.PLAN.apply_plan(root, [change])
            removal = [c for c in install.plan_remove_adapters(root) if c.rel == ".aider.conf.yml"][0]
            self.assertEqual(removal.new, "read:\n")

    def test_an_owners_git_commit_verify_false_is_kept_with_a_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp, {".aider.conf.yml": "git-commit-verify: false\n"})
            changes, notes = install.PLAN.plan_adapters(root)
            self.assertTrue(any("git-commit-verify: false" in n for n in notes))
            for c in changes:
                if c.rel == ".aider.conf.yml":
                    self.assertNotIn("git-commit-verify: true", c.new)

    def test_a_symlinked_config_is_left_alone_with_a_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            target = root / "elsewhere.yml"
            target.write_text("x: 1\n", encoding="utf-8")
            (root / ".aider.conf.yml").symlink_to(target)
            changes, notes = install.PLAN.plan_adapters(root)
            self.assertFalse(any(c.rel == ".aider.conf.yml" for c in changes))
            self.assertTrue(any("symlink" in n and "Aider" in n for n in notes))

    def test_an_owners_file_gets_only_themis_lines_and_loses_only_those(self):
        original = "model: gpt-5\nverbose: true\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp, {".aider.conf.yml": original})
            changes, _ = install.PLAN.plan_adapters(root)
            change = [c for c in changes if c.rel == ".aider.conf.yml"][0]
            self.assertIn("model: gpt-5", change.new)
            install.PLAN.apply_plan(root, [change])
            removal = [c for c in install.plan_remove_adapters(root) if c.rel == ".aider.conf.yml"][0]
            self.assertEqual(removal.new, original)

    def test_uninstall_leaves_no_dangling_read_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp, {".aider.conf.yml": "model: gpt-5\n"})
            changes, _ = install.PLAN.plan_adapters(root)
            change = [c for c in changes if c.rel == ".aider.conf.yml"][0]
            self.assertIn("read:", change.new)
            install.PLAN.apply_plan(root, [change])
            removal = [c for c in install.plan_remove_adapters(root) if c.rel == ".aider.conf.yml"][0]
            self.assertNotIn("read:", removal.new)

    def test_an_owner_entry_added_under_themis_header_survives_uninstall(self):
        text = "model: x\nread:  # themis\n  - OWN.md\n  - AGENTS.md  # themis\n"
        out = install._strip_aider(text)
        self.assertIn("read:\n  - OWN.md", out)
        self.assertNotIn("AGENTS.md", out)


if __name__ == "__main__":
    unittest.main()
