"""Purpose: prove that adding the optional themis_review.py cannot break an
existing installation: a gate workflow written by an earlier release, which
copies only the four older checker files, still passes `gate` and
`gate --range` under a new base checker; a base commit without the optional
file still passes the CI check; an upgrade install adds the file and its
workflow loop; and a repository with no new keys sees no new output.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: every repository is a throwaway; the old workflow text is the
current template with the new file name removed from its copy loop, checked
to be the four-name loop; scripts run under bash as test_gate_ci does.
Never change without a decision: the four-name loop, which is what every
earlier release's themis-gate.yml contains.
"""

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from test_ci_backstop import extract_pr_script
from test_gate_ci import GateCiCase, install

from review_repo import TOOLS

ROOT = Path(__file__).resolve().parents[1]
OLD_LOOP = "for f in themis.py themis_lang.py themis_scan.py themis_gate.py; do"


def old_workflow(template):
    text = template.replace(" themis_review.py", "")
    assert OLD_LOOP in text
    return text


class OlderWorkflowsKeepWorking(GateCiCase):
    def run_workflow(self, workflow, base, head):
        runner_temp = self.tmp / "runner_temp"
        runner_temp.mkdir(exist_ok=True)
        env = {"PATH": os.environ["PATH"], "GITHUB_EVENT_NAME": "pull_request", "EVENT_BEFORE": "",
               "GITHUB_SHA": head, "RUNNER_TEMP": str(runner_temp), "PR_BASE_SHA": base}
        return subprocess.run([self.bash, "-c", extract_pr_script(workflow)], cwd=str(self.repo), env=env,
                              capture_output=True, text=True)

    def test_an_older_gate_workflow_passes_under_a_new_base_checker_without_the_optional_file(self):
        self.base_commit(tools=TOOLS)
        config = json.loads((self.repo / "themis.json").read_text(encoding="utf-8"))
        config.update({"docs": {"caps": {"AGENTS.md": 5}}, "tamper": {"mode": "block"}})
        (self.repo / "themis.json").write_text(json.dumps(config), encoding="utf-8")
        base = self.commit("a base that turns the optional features on")
        (self.repo / "notes.txt").write_text("a change\n", encoding="utf-8")
        head = self.commit("a change")
        done = self.run_workflow(old_workflow(install.PLAN.GATE_WORKFLOW), base, head)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("gate PASS commit=%s" % head, done.stdout)
        plain = subprocess.run([sys.executable, str(self.repo / "tools" / "themis.py"), "gate"],
                               cwd=str(self.repo), capture_output=True, text=True)
        self.assertEqual(plain.returncode, 0, plain.stdout + plain.stderr)
        self.assertFalse((self.repo / "tools" / "themis_review.py").exists())

    def test_a_base_without_the_optional_file_passes_the_ci_check_for_the_upgrade_that_adds_it(self):
        base = self.base_commit(tools=TOOLS)
        (self.repo / "tools" / "themis_review.py").write_bytes((ROOT / "tools" / "themis_review.py").read_bytes())
        head = self.commit("add the optional file")
        for workflow in (old_workflow(install.PLAN.CI_WORKFLOW), install.PLAN.CI_WORKFLOW):
            done = self.run_workflow(workflow, base, head)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertIn("themis: pass", done.stdout)
            self.assertNotIn("optional checks unavailable", done.stdout + done.stderr)

    def test_an_upgrade_adds_the_optional_file_and_its_loop_and_a_repo_with_no_new_keys_sees_nothing_new(self):
        sh = lambda *a: subprocess.run(["git", "-C", str(self.repo)] + list(a), check=True,
                                       capture_output=True, text=True)
        (self.repo / "m.py").write_text("x = 1\n", encoding="utf-8")
        sh("remote", "add", "origin", "https://github.com/example/repo")
        self.commit("base")
        run = lambda *a: subprocess.run([sys.executable, str(ROOT / "install.py"), "install", "--defaults", "--yes"]
                                        + list(a), cwd=str(self.repo), capture_output=True, text=True)
        self.assertEqual(run("--test-command", "python3 -m unittest").returncode, 0)
        (self.repo / "tools" / "themis_review.py").unlink()
        for rel in (".github/workflows/themis.yml", ".github/workflows/themis-gate.yml"):
            path = self.repo / rel
            path.write_text(old_workflow(path.read_text(encoding="utf-8")), encoding="utf-8")
        gate_before = (self.repo / ".github/workflows/themis-gate.yml").read_text(encoding="utf-8")
        agents = (self.repo / "AGENTS.md").read_text(encoding="utf-8")
        (self.repo / "AGENTS.md").write_text(re.sub(r"themis v[\d.]+ (begin|end)", r"themis v3.5.4 \1", agents),
                                             encoding="utf-8")
        config = json.loads((self.repo / "themis.json").read_text(encoding="utf-8"))
        config["version"] = "v3.5.4"
        (self.repo / "themis.json").write_text(json.dumps(config), encoding="utf-8")
        self.commit("a v3.5.4 install")
        upgraded = run()
        self.assertEqual(upgraded.returncode, 0, upgraded.stdout + upgraded.stderr)
        self.assertTrue((self.repo / "tools" / "themis_review.py").is_file())
        self.assertIn("themis_review.py; do", (self.repo / ".github/workflows/themis.yml").read_text(encoding="utf-8"))
        self.assertEqual((self.repo / ".github/workflows/themis-gate.yml").read_text(encoding="utf-8"), gate_before)
        self.commit("the upgrade")
        (self.repo / "m.py").write_text("x = 2\n", encoding="utf-8")
        sh("add", "m.py")
        quiet = subprocess.run([sys.executable, str(self.repo / "tools" / "themis.py"), "check", "--staged"],
                               cwd=str(self.repo), capture_output=True, text=True)
        self.assertEqual(quiet.returncode, 0, quiet.stdout + quiet.stderr)
        for word in ("tripwire", "docs", "unavailable", "literal"):
            self.assertNotIn(word, quiet.stdout + quiet.stderr)


if __name__ == "__main__":
    unittest.main()
