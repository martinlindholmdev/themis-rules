"""Purpose: prove the generated themis-gate.yml script and the pre-push hook
do what the gate promises when run by bash: CI judges the proposed commit
under the base commit's settings and checker, a base checker older than the
gate is skipped rather than held, and a push is stopped by a failing gate
but not by a ref deletion.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: every repository is a throwaway under a TemporaryDirectory; the
script and hook are the shipped text, run with bash standing in for the
`${{ }}` expansions as test_ci_backstop does; no network.
Never change without a decision: the three `${{ }}` substitutions, which must
track whatever GATE_WORKFLOW references.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_ci_backstop import extract_pr_script, find_real_bash

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ("themis.py", "themis_lang.py", "themis_scan.py", "themis_gate.py")
UNITTEST = {"command": [sys.executable, "-m", "unittest"], "runner": "unittest", "min_tests": 3}

_spec = importlib.util.spec_from_file_location("install", ROOT / "install.py")
install = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install)


def sh(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args), check=True, capture_output=True, text=True).stdout.strip()


def suite(count):
    return "import unittest\nclass T(unittest.TestCase):\n    pass\n" + "".join(
        "    def test_%d(self): pass\n" % i for i in range(count))


class GateCiCase(unittest.TestCase):
    def setUp(self):
        self.bash = find_real_bash()
        if not self.bash:
            self.skipTest("no working bash found")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.repo = self.tmp / "repo"
        (self.repo / "tools").mkdir(parents=True)
        sh(self.repo, "init", "-q")
        sh(self.repo, "config", "user.email", "t@example.com")
        sh(self.repo, "config", "user.name", "t")

    def commit(self, message):
        sh(self.repo, "add", "-A")
        sh(self.repo, "commit", "-q", "-m", message, "--no-verify")
        return sh(self.repo, "rev-parse", "HEAD")

    def base_commit(self, tools=TOOLS):
        for name in tools:
            (self.repo / "tools" / name).write_bytes((ROOT / "tools" / name).read_bytes())
        (self.repo / "themis.json").write_text(json.dumps({"version": "v3.4", "test": UNITTEST}), encoding="utf-8")
        (self.repo / "test_sample.py").write_text(suite(3), encoding="utf-8")
        return self.commit("base")

    def run_script(self, base, head):
        runner_temp = self.tmp / "runner_temp"
        runner_temp.mkdir(exist_ok=True)
        env = {"PATH": os.environ["PATH"], "GITHUB_EVENT_NAME": "pull_request", "PR_BASE_SHA": base,
               "EVENT_BEFORE": "", "GITHUB_SHA": head, "RUNNER_TEMP": str(runner_temp)}
        return subprocess.run([self.bash, "-c", extract_pr_script(install.PLAN.GATE_WORKFLOW)],
                              cwd=str(self.repo), env=env, capture_output=True, text=True)


class GateWorkflowScript(GateCiCase):
    def test_a_proposal_that_keeps_the_tests_passes_and_one_that_deletes_them_fails(self):
        base = self.base_commit()
        (self.repo / "notes.txt").write_text("a change\n", encoding="utf-8")
        head = self.commit("keep the tests")
        done = self.run_script(base, head)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("gate PASS commit=%s" % head, done.stdout)
        (self.repo / "test_sample.py").write_text(suite(1), encoding="utf-8")
        deleted = self.run_script(base, self.commit("delete tests"))
        self.assertNotEqual(deleted.returncode, 0)
        self.assertIn("below the floor of 3", deleted.stdout)

    def test_a_base_whose_checker_has_no_gate_is_skipped_not_held(self):
        base = self.base_commit(tools=TOOLS[:3])
        (self.repo / "notes.txt").write_text("a change\n", encoding="utf-8")
        done = self.run_script(base, self.commit("a change"))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("has no gate", done.stdout)

    def test_the_repos_own_themis_workflow_is_the_generated_one(self):
        shipped = (ROOT / ".github" / "workflows" / "themis.yml").read_text(encoding="utf-8")
        self.assertEqual(shipped, install.PLAN.CI_WORKFLOW)


class PrePushHook(GateCiCase):
    def push(self, local_sha):
        hook = self.repo / "tools" / "hooks" / "pre-push"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_bytes((ROOT / "tools" / "hooks" / "pre-push").read_bytes())
        line = "refs/heads/x %s refs/heads/x %s\n" % (local_sha, "0" * 40)
        return subprocess.run([self.bash, str(hook)], cwd=str(self.repo), input=line, capture_output=True, text=True)

    def test_a_failing_gate_stops_a_push_but_a_ref_deletion_runs_nothing(self):
        self.base_commit()
        (self.repo / "test_sample.py").write_text(suite(1), encoding="utf-8")
        head = self.commit("too few tests")
        stopped = self.push(head)
        self.assertNotEqual(stopped.returncode, 0)
        self.assertIn("below the floor of 3", stopped.stdout)
        self.assertEqual(self.push("0" * 40).returncode, 0)


if __name__ == "__main__":
    unittest.main()
