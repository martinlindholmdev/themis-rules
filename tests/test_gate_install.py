"""Purpose: prove what install does for the acceptance gate: nothing unless the
owner sets a test command, the right files when they do, and never an
overwrite of the gate workflow the owner has added their toolchain to, on a
reinstall, an upgrade or an uninstall.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: every repository is a throwaway under a TemporaryDirectory with a
GitHub-looking remote URL and no network; this checkout is only read.
Never change without a decision: the one-time write of themis-gate.yml and
the key names install writes into themis.json.
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
GATE_YML = ".github/workflows/themis-gate.yml"
CUSTOM_STEP = "      - run: echo owner toolchain step\n"


class GateInstallCase(unittest.TestCase):
    def repo(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name) / "repo"
        repo.mkdir()
        self.git(repo, "init", "-q")
        self.git(repo, "config", "user.email", "t@example.com")
        self.git(repo, "config", "user.name", "t")
        self.git(repo, "remote", "add", "origin", "https://github.com/example/repo")
        (repo / "main.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", "init", "--no-verify")
        return repo

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo)] + list(args), check=True, capture_output=True, text=True)

    def install(self, repo, *args, command="install"):
        return subprocess.run([sys.executable, str(INSTALL), command, "--yes"] + list(args)
                              + (["--defaults"] if command == "install" else []),
                              cwd=str(repo), capture_output=True, text=True)

    def config(self, repo):
        return json.loads((repo / "themis.json").read_text(encoding="utf-8"))


class WhatInstallWrites(GateInstallCase):
    def test_without_a_test_command_nothing_about_the_gate_is_written(self):
        repo = self.repo()
        done = self.install(repo)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("test", self.config(repo))
        self.assertFalse((repo / GATE_YML).exists() or (repo / "tools/hooks/pre-push").exists())
        self.assertTrue((repo / "tools/themis_gate.py").is_file())
        self.assertIn("honour-system", done.stdout)

    def test_a_test_command_writes_the_config_the_workflow_and_the_pre_push_hook(self):
        repo = self.repo()
        done = self.install(repo, "--test-command", "python3 -m pytest -q")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.config(repo)["test"], {"command": ["python3", "-m", "pytest", "-q"],
                                                       "runner": "pytest", "min_tests": 1, "max_skipped": 0})
        gate_ci = (repo / GATE_YML).read_text(encoding="utf-8")
        self.assertIn("name: themis-gate", gate_ci)
        self.assertIn('themis.py" gate --range', gate_ci)
        self.assertTrue((repo / "tools/hooks/pre-push").stat().st_mode & 0o100)
        self.assertEqual(self.git(repo, "config", "core.hooksPath").stdout.strip(), "tools/hooks")
        self.assertIn("gate --record", done.stdout)

    def test_a_shell_operator_or_an_unknown_runner_is_refused_before_anything_is_written(self):
        repo = self.repo()
        shell = self.install(repo, "--test-command", "make && make test")
        self.assertEqual(shell.returncode, 1)
        self.assertIn("not through a shell", shell.stdout)
        unknown = self.install(repo, "--test-command", "make check")
        self.assertEqual(unknown.returncode, 1)
        self.assertIn("pass --test-runner", unknown.stdout)
        self.assertFalse((repo / "themis.json").exists())

    def test_uninstall_removes_the_untouched_gate_files_and_keeps_an_edited_workflow(self):
        repo = self.repo()
        self.install(repo, "--test-command", "python3 -m unittest")
        gone = self.install(repo, command="uninstall")
        self.assertEqual(gone.returncode, 0, gone.stdout + gone.stderr)
        self.assertFalse((repo / GATE_YML).exists() or (repo / "tools/hooks/pre-push").exists())
        self.install(repo, "--test-command", "python3 -m unittest")
        path = repo / GATE_YML
        path.write_text(path.read_text(encoding="utf-8") + CUSTOM_STEP, encoding="utf-8")
        kept = self.install(repo, command="uninstall")
        self.assertTrue(path.is_file())
        self.assertIn("left", kept.stdout)


class OwnerSetupSurvives(GateInstallCase):
    def customized_repo(self):
        repo = self.repo()
        self.install(repo, "--test-command", "python3 -m unittest")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", "install", "--no-verify")
        path = repo / GATE_YML
        path.write_text(path.read_text(encoding="utf-8").replace(
            "      # Add the steps", CUSTOM_STEP + "      # Add the steps"), encoding="utf-8")
        return repo, path.read_text(encoding="utf-8")

    def test_a_reinstall_leaves_the_owners_toolchain_steps_and_prints_the_difference(self):
        repo, custom = self.customized_repo()
        done = self.install(repo, "--test-command", "python3 -m unittest discover -s tests")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((repo / GATE_YML).read_text(encoding="utf-8"), custom)
        self.assertIn("left as it is", done.stdout)
        self.assertIn("+" + CUSTOM_STEP.rstrip("\n"), done.stdout)

    def test_a_reinstall_never_replaces_an_owner_edited_pre_push_hook(self):
        repo, _ = self.customized_repo()
        hook = repo / "tools/hooks/pre-push"
        edited = hook.read_text(encoding="utf-8") + "echo owner-check\n"
        hook.write_text(edited, encoding="utf-8")
        done = self.install(repo, "--test-command", "python3 -m unittest")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(hook.read_text(encoding="utf-8"), edited)
        self.assertIn("left as it is", done.stdout)
        hook.unlink()
        self.install(repo)
        self.assertIn("gate --reuse", hook.read_text(encoding="utf-8"))

    def test_an_upgrade_from_the_previous_release_leaves_them_too(self):
        repo, custom = self.customized_repo()
        config = self.config(repo)
        config["version"] = "v3.3"
        (repo / "themis.json").write_text(json.dumps(config), encoding="utf-8")
        agents = re.sub(r"themis v[\d.]+ (begin|end)", r"themis v3.3 \1", (repo / "AGENTS.md").read_text(encoding="utf-8"))
        (repo / "AGENTS.md").write_text(agents, encoding="utf-8")
        for name in ("themis_gate.py", "themis.py"):
            (repo / "tools" / name).unlink()
        done = self.install(repo)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((repo / GATE_YML).read_text(encoding="utf-8"), custom)
        self.assertEqual(self.config(repo)["test"]["command"], ["python3", "-m", "unittest"])
        self.assertTrue((repo / "tools/themis_gate.py").is_file())


if __name__ == "__main__":
    unittest.main()
