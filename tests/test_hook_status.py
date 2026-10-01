"""Purpose: reproduce and guard against Fable's release-review finding 9:
`status` must say "off" for husky/lefthook/pre-commit when the manager's
own file names themis.py but the manager was never actually installed in
this clone (core.hooksPath never pointed at its shim) — naming the
script is not the same as a commit ever running it.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: builds throwaway git repos under a TemporaryDirectory.
Never change without a decision: the install command named in each note.
"""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("themis", ROOT / "tools" / "themis.py")
themis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(themis)


class HuskyStatusTests(unittest.TestCase):
    def test_a_husky_file_naming_themis_but_never_installed_reports_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
            (root / ".husky").mkdir()
            (root / ".husky" / "pre-commit").write_text(
                "#!/bin/sh\npython3 tools/themis.py check --staged\n", encoding="utf-8")
            status = themis.hook_status(root)
            self.assertIn("not installed in this clone", status)
            self.assertIn("off", status)

    def test_a_husky_file_actually_wired_via_core_hooksPath_reports_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
            (root / ".husky").mkdir()
            (root / ".husky" / "pre-commit").write_text(
                "#!/bin/sh\npython3 tools/themis.py check --staged\n", encoding="utf-8")
            (root / ".husky" / "_").mkdir()
            (root / ".husky" / "_" / "pre-commit").write_text("#!/bin/sh\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "config", "core.hooksPath", ".husky/_"], check=True)
            status = themis.hook_status(root)
            self.assertTrue(status.endswith("— on"))


if __name__ == "__main__":
    unittest.main()
