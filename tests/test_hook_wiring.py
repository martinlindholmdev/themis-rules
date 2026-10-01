"""Purpose: reproduce and guard against Fable's release-review findings
6a (a trailing top-level YAML key after "repos:" must stop the
pre-commit-framework append, not produce invalid YAML) and 6b (the call
line must land right after the shebang, never before whichever "exit" or
"exec" line happens to appear first, which can be inside a conditional
and then run only sometimes).
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: builds throwaway repos under a TemporaryDirectory.
Never change without a decision: which fixture proves which rule.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("install", ROOT / "install.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


class PreCommitConfigTests(unittest.TestCase):
    def test_a_trailing_top_level_key_after_repos_stops_the_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".pre-commit-config.yaml").write_text(
                "repos:\n-   repo: foo\n    hooks: []\nci:\n  autofix: true\n", encoding="utf-8")
            changes, notes = install.plan_hook(root)
            self.assertEqual(changes, [])
            self.assertTrue(any("isn't the last top-level key" in n for n in notes))

    def test_repos_as_the_only_key_appends_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".pre-commit-config.yaml").write_text("repos:\n-   repo: foo\n    hooks: []\n", encoding="utf-8")
            changes, notes = install.plan_hook(root)
            self.assertEqual(len(changes), 1)
            self.assertIn("id: themis", changes[0].new)


class ClassicHookInsertionTests(unittest.TestCase):
    def test_the_call_line_lands_right_after_the_shebang_not_inside_a_conditional(self):
        with tempfile.TemporaryDirectory() as tmp:
            import subprocess
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
            hooks = root / ".git" / "hooks"
            hooks.mkdir(parents=True, exist_ok=True)
            (hooks / "pre-commit").write_text(
                "#!/bin/sh\nif [ -z \"$SKIP\" ]; then\n  echo running\n  exit 0\nfi\n", encoding="utf-8")
            changes, notes = install.plan_classic_hook(root)
            self.assertEqual(len(changes), 1)
            lines = changes[0].new.splitlines()
            self.assertEqual(lines[0], "#!/bin/sh")
            self.assertIn("themis.py", lines[1])


if __name__ == "__main__":
    unittest.main()
