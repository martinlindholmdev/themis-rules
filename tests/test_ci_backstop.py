"""Purpose: reproduce and guard against Fable's release-review finding 4:
the CI backstop must run the BASE commit's own copy of tools/themis.py on
a pull request, never the PR's — otherwise a PR that rewrites the
checker to always pass checks itself and gets away with it.
Entry points: run by `python3 -m unittest discover -s tests`. Actually
executes install.py's CI_WORKFLOW bash script (the exact text that ships
to GitHub Actions) via `bash -c`, standing in for the `${{ }}` expansions
with real shell variables.
Invariants: builds a throwaway git repo under a TemporaryDirectory;
requires `bash` and `git` on PATH (present on every GitHub runner and on
this Mac).
Never change without a decision: the three `${{ }}` substitutions below
must track whatever CI_WORKFLOW actually references.
"""

import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("install", ROOT / "install.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


def extract_pr_script(workflow_text: str) -> str:
    """Pulls the `run: |` block out of CI_WORKFLOW and rewrites GitHub's
    `${{ }}` expressions as shell variables this test sets directly."""
    block = workflow_text.split("run: |\n", 1)[1]
    lines = block.splitlines()
    indent = len(lines[0]) - len(lines[0].lstrip(" "))
    dedented = "\n".join(l[indent:] if l.startswith(" " * indent) else l for l in lines)
    dedented = re.sub(r"\$\{\{\s*github\.event_name\s*\}\}", "$GITHUB_EVENT_NAME", dedented)
    dedented = re.sub(r"\$\{\{\s*github\.event\.pull_request\.base\.sha\s*\}\}", "$PR_BASE_SHA", dedented)
    dedented = re.sub(r"\$\{\{\s*github\.event\.before\s*\}\}", "$EVENT_BEFORE", dedented)
    dedented = re.sub(r"\$\{\{\s*github\.sha\s*\}\}", "$GITHUB_SHA", dedented)
    return dedented


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo)] + list(args), check=True, capture_output=True, text=True)


class CiBackstopTests(unittest.TestCase):
    def test_a_pr_that_neuters_tools_themis_py_is_still_caught(self):
        script = extract_pr_script(install.CI_WORKFLOW)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            runner_temp = Path(tmp) / "runner_temp"
            runner_temp.mkdir()
            git(repo, "init", "-q")
            git(repo, "config", "user.email", "t@example.com")
            git(repo, "config", "user.name", "t")

            (repo / "tools").mkdir()
            (repo / "tools" / "themis.py").write_bytes((ROOT / "tools" / "themis.py").read_bytes())
            (repo / "themis.json").write_text('{"version": "v3"}\n', encoding="utf-8")
            (repo / "main.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "base")
            base_sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                       check=True, capture_output=True, text=True).stdout.strip()

            # the PR: a neutered checker that always passes, plus a real secret
            (repo / "tools" / "themis.py").write_text(
                'import sys\nprint("themis: pass, 0 file(s) checked")\nsys.exit(0)\n', encoding="utf-8")
            secret = "sk-" + "1234567890abcdef1234"
            (repo / "main.py").write_text('API_KEY = "%s"\n' % secret, encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "neuter the checker and add a key", "--no-verify")
            head_sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                       check=True, capture_output=True, text=True).stdout.strip()

            env = {
                "PATH": __import__("os").environ["PATH"],
                "GITHUB_EVENT_NAME": "pull_request",
                "PR_BASE_SHA": base_sha,
                "EVENT_BEFORE": "",
                "GITHUB_SHA": head_sha,
                "RUNNER_TEMP": str(runner_temp),
            }
            result = subprocess.run(["bash", "-c", script], cwd=str(repo), env=env,
                                     capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("looks like an OpenAI-shaped key", result.stdout)
            self.assertNotIn(secret, result.stdout)

    def test_a_push_with_a_secret_is_also_caught(self):
        """Astra's hardening note: push ran a whole-tree check with no
        secret scan at all; a secret pushed straight to a branch (no PR)
        must still be caught, using the pre-push commit as the base."""
        script = extract_pr_script(install.CI_WORKFLOW)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            runner_temp = Path(tmp) / "runner_temp"
            runner_temp.mkdir()
            git(repo, "init", "-q")
            git(repo, "config", "user.email", "t@example.com")
            git(repo, "config", "user.name", "t")
            (repo / "tools").mkdir()
            (repo / "tools" / "themis.py").write_bytes((ROOT / "tools" / "themis.py").read_bytes())
            (repo / "themis.json").write_text('{"version": "v3"}\n', encoding="utf-8")
            (repo / "main.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "base")
            before_sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                         check=True, capture_output=True, text=True).stdout.strip()

            secret = "sk-" + "1234567890abcdef1234"
            (repo / "main.py").write_text('API_KEY = "%s"\n' % secret, encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "push a key straight to the branch", "--no-verify")
            head_sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                       check=True, capture_output=True, text=True).stdout.strip()

            env = {
                "PATH": __import__("os").environ["PATH"],
                "GITHUB_EVENT_NAME": "push",
                "PR_BASE_SHA": "",
                "EVENT_BEFORE": before_sha,
                "GITHUB_SHA": head_sha,
                "RUNNER_TEMP": str(runner_temp),
            }
            result = subprocess.run(["bash", "-c", script], cwd=str(repo), env=env,
                                     capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("looks like an OpenAI-shaped key", result.stdout)
            self.assertNotIn(secret, result.stdout)


if __name__ == "__main__":
    unittest.main()
