"""Purpose: prove that an upgrade install changes only what the owner expects
and says what it writes: an owner-edited pre-commit hook is kept byte for
byte with the line to add printed, no workflow file is added to a repository
that has none unless --workflows asks for it, and the plan and the final
summary name every path written, the baseline included.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: every repository is a throwaway under a TemporaryDirectory; no
network; this checkout is only read.
Never change without a decision: what an upgrade may add or replace unasked.
"""

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.py"
PRE_COMMIT = "tools/hooks/pre-commit"
WORKFLOWS = (".github/workflows/themis.yml", ".github/workflows/themis-gate.yml")


class UpgradeWritesTests(unittest.TestCase):
    def repo(self, github=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name) / "repo"
        repo.mkdir()
        self.git(repo, "init", "-q")
        self.git(repo, "config", "user.email", "t@example.com")
        self.git(repo, "config", "user.name", "t")
        if github:
            self.git(repo, "remote", "add", "origin", "https://github.com/example/repo")
        (repo / "m.py").write_text("def f():\n%s    return 1\n" % "".join("    x%d = 1\n" % i for i in range(110)),
                                   encoding="utf-8")
        self.commit(repo, "base")
        return repo

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo)] + list(args), check=True, capture_output=True, text=True)

    def commit(self, repo, message):
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", message, "--no-verify")

    def install(self, repo, *args):
        return subprocess.run([sys.executable, str(INSTALL), "install", "--defaults", "--yes"] + list(args),
                              cwd=str(repo), capture_output=True, text=True)

    def make_previous_release(self, repo):
        """Turns an install of this release into one of the release before it."""
        config = json.loads((repo / "themis.json").read_text(encoding="utf-8"))
        config["version"] = "v3.5.2"
        (repo / "themis.json").write_text(json.dumps(config, indent=1) + "\n", encoding="utf-8")
        agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
        (repo / "AGENTS.md").write_text(re.sub(r"themis v[\d.]+ (begin|end)", r"themis v3.5.2 \1", agents),
                                        encoding="utf-8")

    def test_an_owner_edited_pre_commit_hook_is_kept_and_the_line_to_add_is_printed(self):
        repo = self.repo()
        done = self.install(repo)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        hook = repo / PRE_COMMIT
        edited = hook.read_text(encoding="utf-8").replace(
            'exec "$py"', 'sh tools/project-check.sh || exit 1\nexec "$py"')
        hook.write_bytes(edited.encode("utf-8"))
        self.make_previous_release(repo)
        self.commit(repo, "a v3.5.2 install with a project check in the hook")
        upgraded = self.install(repo)
        self.assertEqual(upgraded.returncode, 0, upgraded.stdout + upgraded.stderr)
        self.assertEqual(hook.read_bytes(), edited.encode("utf-8"))
        self.assertIn("%s exists and differs" % PRE_COMMIT, upgraded.stdout)
        self.assertIn("python3 tools/themis.py check --staged", upgraded.stdout)
        self.assertNotIn("update  " + PRE_COMMIT, upgraded.stdout)

    def test_an_upgrade_adds_no_workflow_file_unless_asked(self):
        repo = self.repo(github=True)
        done = self.install(repo, "--test-command", "python3 -m unittest")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        for rel in WORKFLOWS:
            (repo / rel).unlink()
        self.make_previous_release(repo)
        self.commit(repo, "a v3.5.2 install without workflows")
        upgraded = self.install(repo)
        self.assertEqual(upgraded.returncode, 0, upgraded.stdout + upgraded.stderr)
        for rel in WORKFLOWS:
            self.assertFalse((repo / rel).exists(), upgraded.stdout)
        self.assertIn("--workflows", upgraded.stdout)
        asked = self.install(repo, "--workflows")
        self.assertEqual(asked.returncode, 0, asked.stdout + asked.stderr)
        for rel in WORKFLOWS:
            self.assertTrue((repo / rel).is_file(), rel)

    def test_the_plan_and_the_summary_name_the_baseline_when_it_changes(self):
        repo = self.repo()
        done = self.install(repo)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        baseline = repo / "themis-baseline.json"
        data = json.loads(baseline.read_text(encoding="utf-8"))
        data["functions"] = {"m.py": {"f": 150}}
        baseline.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        self.make_previous_release(repo)
        self.commit(repo, "a v3.5.2 install with a high baseline entry")
        upgraded = self.install(repo)
        self.assertEqual(upgraded.returncode, 0, upgraded.stdout + upgraded.stderr)
        lines = upgraded.stdout.splitlines()
        plan_line = next((l for l in lines if l.startswith("themis: this upgrade writes")), "")
        self.assertIn("themis-baseline.json", plan_line)
        written_line = next((l for l in lines if l.startswith("themis: written")), "")
        self.assertIn("themis-baseline.json", written_line)
        self.assertEqual(json.loads(baseline.read_text(encoding="utf-8"))["functions"], {"m.py": {"f": 112}})


if __name__ == "__main__":
    unittest.main()
