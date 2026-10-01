"""Purpose: reproduce and guard against Fable's re-check, must-fix 2:
`rebaseline` must confine `baseline_path` to the repo exactly like
install.py's safe_path — an owner or agent can set it to anything in
themis.json, and `write_baseline`/`load_baseline` wrote or read it
unconfined.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: builds a throwaway repo under a TemporaryDirectory.
Never change without a decision: `safe_rel_path`'s three checks
(absolute, '..', any symlink component) must match install.py's
safe_path exactly.
"""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("themis", ROOT / "tools" / "themis.py")
themis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(themis)


class SafeRelPathTests(unittest.TestCase):
    def test_absolute_path_is_rejected(self):
        with self.assertRaises(themis.PathEscapesRepo):
            themis.safe_rel_path(Path("/repo"), "/etc/passwd")

    def test_dotdot_is_rejected(self):
        with self.assertRaises(themis.PathEscapesRepo):
            themis.safe_rel_path(Path("/repo"), "../escaped.json")

    def test_a_symlink_component_is_rejected_even_resolving_inside(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "repo"
            root.mkdir()
            (root / "inside.json").write_text("{}", encoding="utf-8")
            (root / "link.json").symlink_to(root / "inside.json")
            with self.assertRaises(themis.PathEscapesRepo):
                themis.safe_rel_path(root, "link.json")


class RebaselinePathSafetyTests(unittest.TestCase):
    def test_a_baseline_path_escaping_the_repo_is_refused_not_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo = tmp / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
            (repo / "main.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            (repo / "themis.json").write_text(
                json.dumps({"baseline_path": "../escaped.json"}), encoding="utf-8")
            config = themis.load_config(repo)
            with self.assertRaises(themis.PathEscapesRepo):
                themis.write_baseline(repo, config, {"files": {}, "functions": {}, "history_words": {}})
            self.assertFalse((tmp / "escaped.json").exists())

    def test_check_still_works_when_baseline_path_escapes_the_repo(self):
        """Reading must fail safely (empty baseline), not raise, so a
        bad config does not also break every ordinary `check`."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo = tmp / "repo"
            repo.mkdir()
            (repo / "themis.json").write_text(
                json.dumps({"baseline_path": "../escaped.json"}), encoding="utf-8")
            config = themis.load_config(repo)
            baseline = themis.load_baseline(repo, config)
            self.assertEqual(baseline, {"files": {}, "functions": {}, "history_words": {}})


if __name__ == "__main__":
    unittest.main()
