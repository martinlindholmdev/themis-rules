"""Purpose: a throwaway git repository with the checker copied in, for the
tests of the opt-in review checks (documentation budget, tamper tripwire).
Entry points: Repo (write, commit, stage, staged, range, rebaseline, run) and
TOOLS, ALL_TOOLS, imported by test_docs_budget.py and test_tamper.py.
Invariants: every repository lives under the caller's temporary directory;
the checker files are copies of this checkout's, never the checkout itself;
commands run with the repository as working directory and capture all output.
Never change without a decision: TOOLS, the four files an older gate workflow
copies, which also serve as the fixture for a missing optional file.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ("themis.py", "themis_lang.py", "themis_scan.py", "themis_gate.py")
ALL_TOOLS = TOOLS + ("themis_review.py",)


class Repo:
    def __init__(self, tmp, config=None, tools=ALL_TOOLS, baseline=None):
        self.path = Path(tmp) / "repo"
        (self.path / "tools").mkdir(parents=True)
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        for name in tools:
            (self.path / "tools" / name).write_bytes((ROOT / "tools" / name).read_bytes())
        self.write("themis.json", json.dumps(dict(config or {}, version="v3.6.0")))
        if baseline is not None:
            self.write("themis-baseline.json", json.dumps(baseline))
        self.write("main.py", "x = 1\n")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.path)] + list(args), check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, rel, text):
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def remove(self, rel):
        self.git("rm", "-q", "-f", rel)

    def commit(self, message="c"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message, "--no-verify")
        return self.git("rev-parse", "HEAD")

    def stage(self, *paths):
        self.git("add", *paths)

    def run(self, *args):
        return subprocess.run([sys.executable, str(self.path / "tools" / "themis.py")] + list(args),
                              cwd=str(self.path), capture_output=True, text=True)

    def staged(self):
        return self.run("check", "--staged")

    def range(self, base, head="HEAD"):
        return self.run("check", "--range", "%s...%s" % (base, head))

    def rebaseline(self):
        return self.run("rebaseline")

    def out(self, done):
        return done.stdout + done.stderr
