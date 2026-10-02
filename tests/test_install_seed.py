"""Purpose: check that install and upgrade seed the baseline for the
seven-language paths from HEAD's committed content only, lower and never
raise the older entries, vendor all three tools files and replace an older
CI workflow, and that the install commit passes the hook it installs.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: every repo is a throwaway under a TemporaryDirectory; no
network; this repo's checkout is only read.
Never change without a decision: what is seeded and what is refused.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.py"
TOOLS = ("themis.py", "themis_lang.py", "themis_scan.py", "themis_gate.py")


def long_ts(name="big", lines=120):
    return "export function %s() {\n%s}\n" % (name, "".join("  step%d();\n" % i for i in range(lines)))


def long_rust(name="big", lines=120):
    return "fn %s() {\n%s}\n" % (name, "".join("    step%d();\n" % i for i in range(lines)))


def long_py(name="f", lines=110):
    return "def %s():\n%s    return 1\n" % (name, "".join("    x%d = 1\n" % i for i in range(lines)))


class SeedTests(unittest.TestCase):
    def repo(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "repo"
        path.mkdir()
        self.git(path, "init", "-q")
        self.git(path, "config", "user.email", "t@example.com")
        self.git(path, "config", "user.name", "t")
        return path

    def git(self, repo, *args, check=True):
        return subprocess.run(["git", "-C", str(repo)] + list(args), check=check,
                              capture_output=True, text=True)

    def commit(self, repo, message, verify=False):
        self.git(repo, "add", "-A")
        return self.git(repo, "commit", "-q", "-m", message, *([] if verify else ["--no-verify"]), check=verify)

    def install(self, repo, *args):
        return subprocess.run([sys.executable, str(INSTALL), "install", "--defaults"] + list(args),
                              cwd=str(repo), capture_output=True, text=True)

    def check(self, repo):
        return subprocess.run([sys.executable, str(repo / "tools" / "themis.py"), "check"],
                              cwd=str(repo), capture_output=True, text=True)

    def baseline(self, repo):
        return json.loads((repo / "themis-baseline.json").read_text(encoding="utf-8"))

    def test_a_fresh_install_seeds_committed_long_functions_and_the_commit_passes(self):
        repo = self.repo()
        (repo / "a.ts").write_text(long_ts(), encoding="utf-8")
        (repo / "lib.rs").write_text(long_rust(), encoding="utf-8")
        self.commit(repo, "base")
        dry = self.install(repo, "--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        for name in TOOLS:
            self.assertIn("write   tools/%s" % name, dry.stdout)
        self.assertIn("identical to Themis v3.5", dry.stdout)
        self.assertIn("gitleaks", dry.stdout)
        self.assertIn("--agents aider", dry.stdout)
        done = self.install(repo, "--yes")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        lang = self.baseline(repo)["lang"]["functions"]
        self.assertEqual(sorted(lang), ["a.ts", "lib.rs"])
        self.assertEqual(lang["a.ts"], {"big": 122})
        committed = self.commit(repo, "install themis", verify=True)
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        self.assertEqual(self.check(repo).returncode, 0)
        self.assertEqual(list(repo.rglob("__pycache__")), [])

    def test_a_long_function_only_in_the_working_tree_is_not_seeded(self):
        repo = self.repo()
        (repo / "main.py").write_text("x = 1\n", encoding="utf-8")
        self.commit(repo, "base")
        (repo / "later.ts").write_text(long_ts("later"), encoding="utf-8")
        dry = self.install(repo, "--dry-run")
        self.assertIn("not seeded", dry.stdout)
        self.assertIn("later.ts: later", dry.stdout)
        self.install(repo, "--yes")
        self.assertEqual(self.baseline(repo)["lang"]["functions"], {})

    def test_an_upgrade_from_v3_seeds_lowers_and_never_raises(self):
        repo = self.repo()
        (repo / "a.ts").write_text(long_ts(), encoding="utf-8")
        (repo / "m.py").write_text(long_py("f", 110), encoding="utf-8")
        old_block = (ROOT / "RULES.md").read_text(encoding="utf-8").replace("v3.5", "v3")
        (repo / "AGENTS.md").write_text(old_block, encoding="utf-8")
        (repo / "themis.json").write_text(json.dumps({"version": "v3", "decision_log": "DECISIONS.md"}), encoding="utf-8")
        (repo / "themis-baseline.json").write_text(json.dumps({
            "files": {}, "functions": {"m.py": {"f": 150, "gone": 130}}, "history_words": {"a.ts": 3}}),
            encoding="utf-8")
        (repo / "tools").mkdir()
        (repo / "tools" / "themis.py").write_text("# the v3 checker\n", encoding="utf-8")
        self.commit(repo, "a v3 install")
        dry = self.install(repo, "--dry-run")
        self.assertIn("upgrading Themis v3 to v3.5", dry.stdout)
        done = self.install(repo, "--yes")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Upgrade Themis to v3.5", done.stdout)
        baseline = self.baseline(repo)
        self.assertEqual(baseline["functions"], {"m.py": {"f": 112}})
        self.assertEqual(baseline["history_words"], {})
        self.assertEqual(baseline["lang"]["functions"], {"a.ts": {"big": 122}})
        committed = self.commit(repo, "upgrade", verify=True)
        self.assertEqual(committed.returncode, 0, committed.stdout + committed.stderr)
        self.assertEqual(self.check(repo).returncode, 0)

    def test_an_upgrade_from_v3_1_replaces_the_rules_block_with_the_new_rule_7(self):
        repo = self.repo()
        rules = (ROOT / "RULES.md").read_text(encoding="utf-8")
        new_rule = "delete only what a read shows is a true duplicate"
        new_text = ("keep what catches\n   them, and delete only what a read shows is a true duplicate:\n"
                    "   catching the same bug is not proof. A planted bug nothing catches\n"
                    "   is a missing test, unless a read shows the change cannot alter what\n"
                    "   the owner would notice.\n")
        self.assertIn(new_text, rules)
        old_block = rules.replace(new_text, "keep what catches them.\n").replace("v3.5", "v3.1")
        self.assertNotIn(new_rule, old_block)
        (repo / "AGENTS.md").write_text(old_block, encoding="utf-8")
        (repo / "themis.json").write_text(json.dumps({"version": "v3.1", "decision_log": "DECISIONS.md"}), encoding="utf-8")
        (repo / "tools").mkdir()
        for name in TOOLS:
            (repo / "tools" / name).write_text("# the v3.1 checker\n", encoding="utf-8")
        (repo / "main.py").write_text("x = 1\n", encoding="utf-8")
        self.commit(repo, "a v3.1 install")
        dry = self.install(repo, "--dry-run")
        self.assertIn("upgrading Themis v3.1 to v3.5", dry.stdout)
        done = self.install(repo, "--yes")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("Upgrade Themis to v3.5", done.stdout)
        agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("<!-- themis v3.5 begin -->", agents)
        self.assertNotIn("v3.1", agents)
        self.assertIn(new_rule, agents)
        self.assertEqual(json.loads((repo / "themis.json").read_text(encoding="utf-8"))["version"], "v3.5")

    def test_an_upgrade_replaces_the_v3_workflow_and_says_so(self):
        repo = self.repo()
        self.git(repo, "remote", "add", "origin", "https://github.com/example/repo")
        workflow = repo / ".github" / "workflows"
        workflow.mkdir(parents=True)
        (workflow / "themis.yml").write_text('run: python3 "$RUNNER_TEMP/themis_base.py" check\n', encoding="utf-8")
        (repo / "main.py").write_text("x = 1\n", encoding="utf-8")
        self.commit(repo, "base")
        dry = self.install(repo, "--dry-run")
        self.assertIn("update  .github/workflows/themis.yml", dry.stdout)
        self.assertIn("replacing .github/workflows/themis.yml", dry.stdout)


if __name__ == "__main__":
    unittest.main()
