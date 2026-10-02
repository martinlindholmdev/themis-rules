"""Purpose: exercise install.py and tools/themis.py together, in
throwaway git repos, the way an owner or an agent actually runs them:
install, commit, upgrade, uninstall, and a ranged CI-style check.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: every repo this test builds lives under a TemporaryDirectory
and is gone when the test ends; never touches this repo or its git
config; no network.
Never change without a decision: the four scenarios --range must catch
or pass, and what "uninstall restores the tree" is checked against.
"""

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from headers import PY

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.py"
THEMIS = ROOT / "tools" / "themis.py"


def run(cwd, *args, **kwargs):
    return subprocess.run([sys.executable] + list(args), cwd=str(cwd),
                           capture_output=True, text=True, **kwargs)


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(path), check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)


def commit_all(path: Path, message: str, extra_args=()) -> None:
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", message, *extra_args], check=True)


def tree_hash(path: Path) -> dict:
    out = {}
    for item in sorted(path.rglob("*")):
        if item.is_file() and ".git" not in item.parts:
            out[str(item.relative_to(path))] = hashlib.sha256(item.read_bytes()).hexdigest()
    return out


class RangeCheckTests(unittest.TestCase):
    def test_range_catches_a_secret_and_an_oversized_file_added_between_two_commits(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            init_repo(repo)
            (repo / "tools").mkdir()
            for name in ("themis.py", "themis_lang.py", "themis_scan.py"):
                (repo / "tools" / name).write_bytes((THEMIS.parent / name).read_bytes())
            (repo / "themis.json").write_text('{"version": "v3"}\n', encoding="utf-8")
            (repo / "main.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            commit_all(repo, "base")
            base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                   check=True, capture_output=True, text=True).stdout.strip()
            big = "\n".join(["def big():"] + ["    x = %d" % i for i in range(900)] + ["    return x"])
            (repo / "big.py").write_text(big + "\n", encoding="utf-8")
            secret = "sk-" + "1234567890abcdef1234"
            (repo / "main.py").write_text('API_KEY = "%s"\n' % secret, encoding="utf-8")
            commit_all(repo, "add big file and a credential", ["--no-verify"])

            result = run(repo, str(repo / "tools" / "themis.py"), "check", "--range", base + "...HEAD")
            self.assertEqual(result.returncode, 1)
            self.assertIn("over the 800-line limit", result.stdout)
            self.assertIn("looks like an OpenAI-shaped key", result.stdout)
            self.assertNotIn(secret, result.stdout)

    def test_range_notes_when_the_checker_itself_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            init_repo(repo)
            (repo / "tools").mkdir()
            for name in ("themis.py", "themis_lang.py", "themis_scan.py"):
                (repo / "tools" / name).write_bytes((THEMIS.parent / name).read_bytes())
            (repo / "themis.json").write_text('{"version": "v3"}\n', encoding="utf-8")
            (repo / "main.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            commit_all(repo, "base")
            base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                   check=True, capture_output=True, text=True).stdout.strip()
            (repo / "tools" / "themis.py").write_text(THEMIS.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            commit_all(repo, "touch the checker")

            result = run(repo, str(repo / "tools" / "themis.py"), "check", "--range", base + "...HEAD")
            self.assertIn("tools/themis.py changed; owner only", result.stdout)


class NonAsciiTests(unittest.TestCase):
    def test_a_non_ascii_filename_is_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            init_repo(repo)
            (repo / "tools").mkdir()
            for name in ("themis.py", "themis_lang.py", "themis_scan.py"):
                (repo / "tools" / name).write_bytes((THEMIS.parent / name).read_bytes())
            (repo / "themis.json").write_text('{"version": "v3"}\n', encoding="utf-8")
            (repo / "café.py").write_text("def pour():\n    return 1\n", encoding="utf-8")
            commit_all(repo, "add café.py")

            result = run(repo, str(repo / "tools" / "themis.py"), "check")
            self.assertEqual(result.returncode, 0)
            self.assertIn("pass, 1 file(s) checked", result.stdout)


class InstallLifecycleTests(unittest.TestCase):
    def _fresh_repo(self, tmp: Path) -> Path:
        repo = tmp / "repo"
        repo.mkdir()
        init_repo(repo)
        (repo / "main.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        commit_all(repo, "init")
        return repo

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._fresh_repo(Path(tmp))
            before = tree_hash(repo)
            result = run(repo, str(INSTALL), "install", "--dry-run", "--defaults")
            self.assertEqual(result.returncode, 0)
            self.assertIn("write   tools/themis.py", result.stdout)
            self.assertEqual(tree_hash(repo), before)

    def test_install_twice_is_idempotent_then_normal_and_bad_commits_behave(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._fresh_repo(Path(tmp))
            first = run(repo, str(INSTALL), "install", "--defaults", "--yes")
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            commit_all(repo, "install themis")

            second = run(repo, str(INSTALL), "install", "--defaults", "--yes")
            self.assertEqual(second.returncode, 0)
            self.assertIn("nothing to change", second.stdout)

            (repo / "util.py").write_text(PY + "def mul(a, b):\n    return a * b\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "util.py"], check=True)
            good = subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "add util.py"],
                                   cwd=str(repo), capture_output=True, text=True)
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)

            big = "\n".join(["def big():"] + ["    x = %d" % i for i in range(900)] + ["    return x"])
            (repo / "oversized.py").write_text(PY + big + "\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "oversized.py"], check=True)
            bad = subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "add oversized.py"],
                                  cwd=str(repo), capture_output=True, text=True)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("over the 800-line limit", bad.stdout + bad.stderr)
            self.assertNotIn("valid header", bad.stdout + bad.stderr)

    def test_uninstall_restores_the_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._fresh_repo(Path(tmp))
            before = tree_hash(repo)
            run(repo, str(INSTALL), "install", "--defaults", "--yes")
            uninstall = run(repo, str(INSTALL), "uninstall", "--yes")
            self.assertEqual(uninstall.returncode, 0, uninstall.stdout + uninstall.stderr)
            after = tree_hash(repo)
            self.assertEqual(after, before)


class UpgradeTests(unittest.TestCase):
    def test_upgrade_from_agent_rules_v2_lands_on_v3_3_and_is_then_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "tools").mkdir(parents=True)
            (repo / "tools" / "agent_rules.py").write_text("# old checker\n", encoding="utf-8")
            (repo / "agent-rules.json").write_text(
                '{"version": "v2", "baseline_path": "agent-rules-baseline.json", '
                '"exempt_prefixes": [], "extra_history_words": []}\n', encoding="utf-8")
            (repo / "agent-rules-baseline.json").write_text(
                '{"files": {}, "functions": {}, "history_words": {}}\n', encoding="utf-8")
            (repo / "AGENTS.md").write_text(
                "# A repo\n\n<!-- agent-rules v2 begin -->\nold rules block\n"
                "<!-- agent-rules v2 end -->\n", encoding="utf-8")
            (repo / "main.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            init_repo(repo)
            commit_all(repo, "snapshot of a v2 install")

            result = run(repo, str(INSTALL), "install", "--defaults", "--yes")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((repo / "tools" / "agent_rules.py").exists())
            self.assertFalse((repo / "agent-rules.json").exists())
            self.assertTrue((repo / "themis.json").exists())
            agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("<!-- themis v3.3 begin -->", agents)
            self.assertNotIn("agent-rules v2", agents)
            commit_all(repo, "upgrade to themis v3.3")

            again = run(repo, str(INSTALL), "install", "--defaults", "--yes")
            self.assertIn("nothing to change", again.stdout)


if __name__ == "__main__":
    unittest.main()
