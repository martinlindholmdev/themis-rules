"""Purpose: reproduce and guard against an independent release review's finding 3:
install.py's final `status` run must never execute code from the target
repo. Without `-I`, Python puts the script's own directory first on
sys.path, so a target repo's own tools/argparse.py (or any stdlib-named
module) shadows the real one and runs during `import argparse`.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: builds a throwaway git repo under a TemporaryDirectory; never
touches this repo.
Never change without a decision: the `-I` flag in run_verified_status.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NoTargetCodeRunsTests(unittest.TestCase):
    def test_a_same_named_module_in_the_target_repo_never_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "tools").mkdir()
            (repo / "tools" / "themis.py").write_bytes((ROOT / "tools" / "themis.py").read_bytes())
            # shadows the stdlib module `tools/themis.py` imports at startup
            (repo / "tools" / "argparse.py").write_text(
                "open('pwned.txt', 'w').write('TARGET REPO CODE RAN')\nimport sys\nsys.exit(1)\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)

            install = importlib_module()
            install.HERE = ROOT  # so the byte-compare passes against our real source
            install.PLAN.run_verified_status(repo)

            self.assertFalse((repo / "pwned.txt").exists(),
                              "the target repo's tools/argparse.py ran during status")


def importlib_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("install", ROOT / "install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
