"""Purpose: guard tools/themis.py against a target repository's own tools/
folder: Python puts the script's folder first on sys.path, so a planted
tools/json.py (or __future__.py, re.py ...) would be imported instead of the
standard library and run with the committer's rights, under the hook, CI and
any direct `python3 tools/themis.py` run.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: builds a throwaway git repo under a TemporaryDirectory and runs
the vendored checker there exactly as the pre-commit hook does; never
touches this repo; no network.
Never change without a decision: that the planted modules must not run and
the check must still pass in the same run.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL_NAMES = ("themis.py", "themis_lang.py", "themis_scan.py", "themis_gate.py")
PLANTED = ("json", "__future__")


class ToolsShadowingTests(unittest.TestCase):
    def test_a_stdlib_named_module_in_the_target_tools_folder_never_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "tools").mkdir(parents=True)
            for name in TOOL_NAMES:
                (repo / "tools" / name).write_bytes((ROOT / "tools" / name).read_bytes())
            for name in PLANTED:
                (repo / "tools" / (name + ".py")).write_text(
                    "open('%s-ran.txt', 'w').write('TARGET REPO CODE RAN')\nannotations = None\n" % name, encoding="utf-8")
            (repo / "themis.json").write_text('{"version": "v3"}\n', encoding="utf-8")
            (repo / "main.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
            subprocess.run(["git", "-C", str(repo), "add", "--", "main.py", "themis.json"], check=True)

            result = subprocess.run([sys.executable, str(repo / "tools" / "themis.py"), "check", "--staged"],
                                    cwd=str(repo), capture_output=True, text=True)

            ran = [n for n in PLANTED if (repo / (n + "-ran.txt")).exists()]
            self.assertEqual(ran, [], "the target repo's planted tools/ module ran: %s" % ran)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("themis: pass", result.stdout)


if __name__ == "__main__":
    unittest.main()
