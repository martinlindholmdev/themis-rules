"""Purpose: reproduce and guard against an independent release review's finding 2:
`check --staged` must measure staged files against the baseline that is
actually staged (or committed), never one just sitting unstaged in the
working tree — otherwise `rebaseline` without `git add` silently widens
what a commit is allowed to contain.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: builds a throwaway git repo under a TemporaryDirectory.
Never change without a decision: staged, then HEAD, then empty — the
fallback order `load_baseline_staged` tries.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEMIS = ROOT / "tools" / "themis.py"
BIG = "\n".join(["def big():"] + ["    x = %d" % i for i in range(900)] + ["    return x"]) + "\n"


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(path), check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)


class HookBypassTests(unittest.TestCase):
    def test_an_unstaged_baseline_widening_does_not_let_an_oversized_commit_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "tools").mkdir()
            for name in ("themis.py", "themis_lang.py", "themis_scan.py"):
                (repo / "tools" / name).write_bytes((THEMIS.parent / name).read_bytes())
            (repo / "themis.json").write_text('{"version": "v3"}\n', encoding="utf-8")
            (repo / "main.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            init_repo(repo)
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)

            (repo / "big.py").write_text(BIG, encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "big.py"], check=True)
            # an unstaged edit pretending big.py's size is already baselined
            (repo / "themis-baseline.json").write_text(
                json.dumps({"files": {"big.py": 902}, "functions": {"big.py": {"big": 902}}, "history_words": {}}),
                encoding="utf-8")

            result = subprocess.run([sys.executable, str(repo / "tools" / "themis.py"), "check", "--staged"],
                                     cwd=str(repo), capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("over the 800-line limit", result.stdout)


if __name__ == "__main__":
    unittest.main()
