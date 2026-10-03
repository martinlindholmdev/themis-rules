"""Purpose: prove the acceptance gate in real throwaway repositories: a pass
names its commit and tree, every way a run can be empty or wrong fails, the
base commit's settings and the committed tree decide, and the runner presets
read real captured output.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: every repository is a throwaway under a TemporaryDirectory with a
tiny unittest suite as the project's tests; the fixtures under
tests/fixtures/gate are real runner output (paths rewritten), never invented;
nothing touches this checkout.
Never change without a decision: the PASS line fields and the failure texts
each test asserts, which are what a reader of a CI log sees.
"""

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "gate"
TOOLS = ("themis.py", "themis_lang.py", "themis_scan.py", "themis_gate.py")

_spec = importlib.util.spec_from_file_location("themis_gate", ROOT / "tools" / "themis_gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

UNITTEST = {"command": [sys.executable, "-m", "unittest"], "runner": "unittest", "min_tests": 3}


def suite(passing: int, skipped: int = 0) -> str:
    lines = ["import unittest", "class T(unittest.TestCase):", "    pass"]
    lines += ["    def test_p%d(self): pass" % i for i in range(passing)]
    for i in range(skipped):
        lines += ["    @unittest.skip('s')", "    def test_s%d(self): pass" % i]
    return "\n".join(lines) + "\n"


def sh(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args), check=True, capture_output=True, text=True).stdout.strip()


def fake(text, status=0):
    """A command that prints `text` and exits with `status`, no suite involved."""
    return [sys.executable, "-c", "import sys; print(%r); sys.exit(%d)" % (text, status)]


class GateCase(unittest.TestCase):
    def repo(self, test=UNITTEST, passing=3, skipped=0):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name) / "repo"
        (repo / "tools").mkdir(parents=True)
        for name in TOOLS:
            (repo / "tools" / name).write_bytes((ROOT / "tools" / name).read_bytes())
        sh(repo, "init", "-q")
        sh(repo, "config", "user.email", "t@example.com")
        sh(repo, "config", "user.name", "t")
        self.write(repo, "themis.json", json.dumps(dict({"version": "v3.4", "decision_log": "DECISIONS.md"}, **({"test": test} if test else {}))))
        self.write(repo, "test_sample.py", suite(passing, skipped))
        self.commit(repo, "base")
        return repo

    def write(self, repo, rel, text):
        (repo / rel).write_text(text, encoding="utf-8")

    def commit(self, repo, message):
        sh(repo, "add", "-A")
        sh(repo, "commit", "-q", "-m", message, "--no-verify")
        return sh(repo, "rev-parse", "HEAD")

    def gate(self, repo, *args):
        return subprocess.run([sys.executable, str(repo / "tools" / "themis.py"), "gate"] + list(args),
                              cwd=str(repo), capture_output=True, text=True)

    def counting_repo(self):
        """A test command that leaves a mark in ran.log each time it runs."""
        script = ("import subprocess, sys\nopen('ran.log', 'a').write('x')\n"
                  "sys.exit(subprocess.call([sys.executable, '-m', 'unittest']))\n")
        repo = self.repo()
        self.write(repo, "run_tests.py", script)
        self.write(repo, ".gitignore", "ran.log\n")
        self.set_test(repo, command=[sys.executable, "run_tests.py"])
        return repo

    def set_test(self, repo, **changes):
        data = json.loads((repo / "themis.json").read_text(encoding="utf-8"))
        data["test"] = dict(data.get("test", UNITTEST), **changes)
        self.write(repo, "themis.json", json.dumps(data))
        return self.commit(repo, "settings")


class RunTests(GateCase):
    def test_a_pass_names_the_commit_and_tree_and_the_floor_is_inclusive(self):
        repo = self.repo()
        done = self.gate(repo)
        commit, tree = sh(repo, "rev-parse", "HEAD"), sh(repo, "rev-parse", "HEAD^{tree}")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertRegex(done.stdout, r"gate PASS commit=%s tree=%s tests=3 skipped=0 floor=3 cmd=\w+" % (commit, tree))

    def test_one_test_below_the_floor_fails(self):
        repo = self.repo()
        self.set_test(repo, min_tests=4)
        done = self.gate(repo)
        self.assertEqual(done.returncode, 1)
        self.assertIn("3 test(s) ran, below the floor of 4", done.stdout)

    def test_an_empty_suite_and_output_with_no_count_both_fail(self):
        empty = self.gate(self.repo(passing=0))
        self.assertEqual(empty.returncode, 1)
        self.assertIn("0 test(s) ran, below the floor of 3", empty.stdout)
        silent = self.gate(self.repo(dict(UNITTEST, command=fake("all is well"))))
        self.assertEqual(silent.returncode, 1)
        self.assertIn("no test count found", silent.stdout)

    def test_a_failing_exit_status_fails_even_when_the_summary_looks_green(self):
        done = self.gate(self.repo(dict(UNITTEST, command=fake("Ran 5 tests in 0.1s\n\nOK", status=1))))
        self.assertEqual(done.returncode, 1)
        self.assertIn("exited with status 1", done.stdout)
        self.assertNotIn("gate PASS", done.stdout)

    def test_skips_are_not_tests_and_the_ceiling_is_enforced(self):
        repo = self.repo(passing=3, skipped=2)
        over = self.gate(repo)
        self.assertEqual(over.returncode, 1)
        self.assertIn("2 test(s) skipped, above the ceiling of 0", over.stdout)
        self.set_test(repo, max_skipped=2)
        allowed = self.gate(repo)
        self.assertEqual(allowed.returncode, 0, allowed.stdout)
        self.assertIn("tests=3 skipped=2", allowed.stdout)

    def test_a_timeout_and_a_missing_command_fail_with_their_own_message(self):
        slow = self.gate(self.repo(dict(UNITTEST, timeout=1, command=[sys.executable, "-c", "import time; time.sleep(30)"])))
        self.assertEqual(slow.returncode, 1)
        self.assertIn("timed out after 1 seconds", slow.stdout)
        gone = self.gate(self.repo(dict(UNITTEST, command=["no-such-program-themis"])))
        self.assertEqual(gone.returncode, 1)
        self.assertIn("command not found: no-such-program-themis", gone.stdout)

    @unittest.skipIf(sys.platform == "win32", "the process-group kill is POSIX; Windows uses taskkill /T")
    def test_a_timeout_ends_the_processes_the_command_started_too(self):
        script = ("import subprocess, sys, time\n"
                  "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3); open(\"late.txt\", \"w\").write(\"x\")'])\n"
                  "time.sleep(60)\n")
        repo = self.repo(dict(UNITTEST, timeout=1, command=[sys.executable, "run_tests.py"]))
        self.write(repo, "run_tests.py", script)
        self.commit(repo, "wrapper")
        self.assertIn("timed out", self.gate(repo).stdout)
        time.sleep(4)
        self.assertFalse((repo / "late.txt").exists())

    def test_colour_codes_in_the_summary_do_not_hide_the_count(self):
        command = fake("\x1b[32mRan \x1b[1m4\x1b[0m tests in 0.0s\x1b[0m\n\nOK")
        done = self.gate(self.repo(dict(UNITTEST, command=command, min_tests=4)))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("tests=4", done.stdout)

    def test_no_test_section_is_honour_system_and_a_broken_one_fails(self):
        none = self.gate(self.repo(test=None))
        self.assertEqual(none.returncode, 0)
        self.assertIn("honour-system", none.stdout)
        broken = self.gate(self.repo(dict(UNITTEST, command="python3 -m unittest")))
        self.assertEqual(broken.returncode, 1)
        self.assertIn("test.command must be a non-empty list", broken.stdout)


class BaseCommitDecides(GateCase):
    def head_edits_settings(self):
        """A base with a real suite and floor 3; a head that deletes tests and
        points the gate at a command that always reports a pass."""
        repo = self.repo()
        base = sh(repo, "rev-parse", "HEAD")
        self.write(repo, "test_sample.py", suite(1))
        self.set_test(repo, command=fake("Ran 9 tests in 0.0s\n\nOK"), min_tests=1)
        return repo, base, sh(repo, "rev-parse", "HEAD")

    def test_a_head_that_edits_the_command_and_floor_is_judged_by_the_base(self):
        repo, base, head = self.head_edits_settings()
        done = self.gate(repo, "--range", "%s...%s" % (base, head))
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("1 test(s) ran, below the floor of 3", done.stdout)
        self.assertIn("owner only", done.stdout)

    def test_the_range_run_refuses_a_checkout_that_is_not_the_named_commit(self):
        repo, base, head = self.head_edits_settings()
        sh(repo, "checkout", "-q", base)
        done = self.gate(repo, "--range", "%s...%s" % (base, head))
        self.assertEqual(done.returncode, 1)
        self.assertIn("checked-out commit is not %s" % head, done.stdout)

    def test_a_base_with_no_config_is_skipped_not_failed(self):
        repo = self.repo()
        empty_tree = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
        done = self.gate(repo, "--range", "%s...%s" % (empty_tree, sh(repo, "rev-parse", "HEAD")))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("honour-system", done.stdout)


class CommittedTree(GateCase):
    def test_tracked_files_changed_before_the_run_stop_it_before_any_test_runs(self):
        repo = self.counting_repo()
        self.write(repo, "test_sample.py", suite(9))
        done = self.gate(repo)
        self.assertEqual(done.returncode, 1)
        self.assertIn("tracked files differ from the committed tree", done.stdout)
        sh(repo, "add", "test_sample.py")
        self.assertEqual(self.gate(repo).returncode, 1)
        self.assertFalse((repo / "ran.log").exists())

    def generating_repo(self, **changes):
        """A test command that rewrites a tracked file while it runs."""
        script = ("import subprocess, sys\nopen('generated.txt', 'a').write('x')\n"
                  "sys.exit(subprocess.call([sys.executable, '-m', 'unittest']))\n")
        repo = self.repo()
        self.write(repo, "generated.txt", "")
        self.write(repo, "run_tests.py", script)
        self.set_test(repo, command=[sys.executable, "run_tests.py"], **changes)
        return repo

    def test_a_command_that_changes_a_tracked_file_during_the_run_does_not_pass(self):
        done = self.gate(self.generating_repo())
        self.assertEqual(done.returncode, 1)
        self.assertIn("generated.txt", done.stdout)
        self.assertNotIn("gate PASS", done.stdout)

    def test_a_path_the_owner_lists_as_generated_may_change(self):
        done = self.gate(self.generating_repo(ignore_paths=["generated.txt"]))
        self.assertEqual(done.returncode, 0, done.stdout)


class LocalReceipt(GateCase):
    def test_reuse_skips_the_run_only_for_the_exact_tree_it_covered(self):
        repo = self.counting_repo()
        self.assertEqual(self.gate(repo).returncode, 0)
        again = self.gate(repo, "--reuse")
        self.assertIn("reused", again.stdout)
        self.assertEqual((repo / "ran.log").read_text(), "x")
        self.write(repo, "notes.txt", "a change\n")
        self.commit(repo, "another tree")
        third = self.gate(repo, "--reuse")
        self.assertNotIn("reused", third.stdout)
        self.assertEqual((repo / "ran.log").read_text(), "xx")

    def test_record_raises_the_floor_to_the_count_and_lower_needs_a_reason_and_logs_it(self):
        repo = self.repo()
        self.set_test(repo, min_tests=2)
        self.gate(repo, "--record")
        self.assertEqual(json.loads((repo / "themis.json").read_text())["test"]["min_tests"], 3)
        sh(repo, "checkout", "-q", "themis.json")
        self.set_test(repo, min_tests=3)
        self.assertIn("floor stays at 3", self.gate(repo, "--record").stdout)
        self.assertEqual(self.gate(repo, "--lower", "1").returncode, 2)
        done = self.gate(repo, "--lower", "1", "--reason", "two tests were exact duplicates")
        self.assertEqual(done.returncode, 0, done.stdout)
        saved = json.loads((repo / "themis.json").read_text())["test"]
        self.assertEqual((saved["min_tests"], saved["floor_reason"]), (1, "two tests were exact duplicates"))
        self.assertIn("lowered from 3 to 1: two tests were exact duplicates", (repo / "DECISIONS.md").read_text())
        self.assertEqual(self.gate(repo, "--lower", "5", "--reason", "raise").returncode, 1)


class PrePush(GateCase):
    """`gate --pre-push` reads the lines git hands a pre-push hook on stdin."""

    def pre_push(self, repo, remote_ref="refs/heads/main", remote_sha="0" * 40):
        line = "refs/heads/work %s %s %s\n" % (sh(repo, "rev-parse", "HEAD"), remote_ref, remote_sha)
        return subprocess.run([sys.executable, str(repo / "tools" / "themis.py"), "gate", "--pre-push"],
                              cwd=str(repo), input=line, capture_output=True, text=True)

    def ran(self, repo):
        path = repo / "ran.log"
        return path.read_text() if path.exists() else ""

    def docs_repo(self, docs_only):
        """A counting repo with a docs_only list and a receipt from one run."""
        repo = self.counting_repo()
        self.set_test(repo, docs_only=docs_only)
        self.assertEqual(self.gate(repo).returncode, 0)
        return repo

    def test_a_feature_branch_push_runs_nothing(self):
        repo = self.counting_repo()
        done = self.pre_push(repo, "refs/heads/feature")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.ran(repo), "")
        self.assertNotIn("gate PASS", done.stdout)

    def test_a_main_push_runs_the_gate(self):
        repo = self.counting_repo()
        done = self.pre_push(repo)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("gate PASS", done.stdout)
        self.assertEqual(self.ran(repo), "x")

    def test_a_documents_only_main_push_reuses_the_last_run(self):
        repo = self.docs_repo(["*.md"])
        self.write(repo, "README.md", "words\n")
        self.commit(repo, "docs")
        done = self.pre_push(repo)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("reused", done.stdout)
        self.assertEqual(self.ran(repo), "x")

    def test_a_listed_document_beside_an_unlisted_file_runs_the_gate(self):
        repo = self.docs_repo(["*.md"])
        self.write(repo, "README.md", "words\n")
        self.write(repo, "notes.txt", "code-adjacent\n")
        self.commit(repo, "docs and more")
        done = self.pre_push(repo)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("reused", done.stdout)
        self.assertEqual(self.ran(repo), "xx")

    def test_a_list_edited_in_the_same_change_is_ignored(self):
        repo = self.docs_repo(["*.md", "*.json"])
        data = json.loads((repo / "themis.json").read_text(encoding="utf-8"))
        data["test"]["docs_only"] = ["*.md", "*.json", "*.txt"]
        self.write(repo, "themis.json", json.dumps(data))
        self.write(repo, "notes.txt", "now listed by this very change\n")
        self.commit(repo, "widen the list")
        done = self.pre_push(repo)
        self.assertNotIn("reused", done.stdout)
        self.assertEqual(self.ran(repo), "xx")

    def test_a_raised_floor_is_judged_even_when_the_list_covers_the_config_file(self):
        repo = self.docs_repo(["*.md", "*.json"])
        self.set_test(repo, min_tests=4)
        done = self.pre_push(repo)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertNotIn("reused", done.stdout)
        self.assertIn("below the floor of 4", done.stdout)

    def test_a_receipt_written_under_other_settings_is_not_reused(self):
        repo = self.docs_repo(["*.md"])
        path = repo / sh(repo, "rev-parse", "--git-path", gate.RECEIPT)
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["settings"] = "another-floor"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        self.write(repo, "README.md", "words\n")
        self.commit(repo, "docs")
        done = self.pre_push(repo)
        self.assertNotIn("reused", done.stdout)
        self.assertEqual(self.ran(repo), "xx")

    def test_an_unlisted_submodule_update_beside_a_document_runs_the_gate(self):
        repo = self.counting_repo()
        self.set_test(repo, docs_only=["*.md"])
        sh(repo, "config", "diff.ignoreSubmodules", "all")
        sh(repo, "update-index", "--add", "--cacheinfo", "160000,%s,sub" % sh(repo, "rev-parse", "HEAD"))
        sh(repo, "commit", "-q", "-m", "a submodule", "--no-verify")
        self.assertEqual(self.gate(repo).returncode, 0)
        sh(repo, "update-index", "--cacheinfo", "160000,%s,sub" % sh(repo, "rev-parse", "HEAD"))
        self.write(repo, "README.md", "words\n")
        sh(repo, "add", "README.md")
        sh(repo, "commit", "-q", "-m", "move the submodule and a document", "--no-verify")
        done = self.pre_push(repo)
        self.assertNotIn("reused", done.stdout)
        self.assertEqual(self.ran(repo), "xx")

    def test_a_main_push_that_lowers_the_floor_is_judged_by_the_destinations_floor(self):
        repo = self.repo()
        main = sh(repo, "rev-parse", "HEAD")
        self.write(repo, "test_sample.py", suite(1))
        self.set_test(repo, min_tests=1)
        self.assertEqual(self.gate(repo).returncode, 0)
        done = self.pre_push(repo, remote_sha=main)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("below the floor of 3", done.stdout)

    def test_a_main_push_that_edits_the_command_runs_the_destinations_command(self):
        repo = self.counting_repo()
        main = sh(repo, "rev-parse", "HEAD")
        self.set_test(repo, command=fake("Ran 9 tests in 0.1s"))
        done = self.pre_push(repo, remote_sha=main)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("tests=3 ", done.stdout)
        self.assertEqual(self.ran(repo), "x")

    def test_a_destination_missing_here_is_read_from_the_remote_tracking_ref(self):
        repo = self.repo()
        sh(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.write(repo, "test_sample.py", suite(1))
        self.set_test(repo, min_tests=1)
        done = self.pre_push(repo, remote_sha="1" * 40)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("below the floor of 3", done.stdout)

    def test_a_brand_new_protected_branch_uses_heads_settings(self):
        repo = self.repo()
        self.set_test(repo, min_tests=4)
        done = self.pre_push(repo, "refs/heads/master")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("below the floor of 4", done.stdout)


class StatusWording(GateCase):
    def status(self, repo):
        return subprocess.run([sys.executable, str(repo / "tools" / "themis.py"), "status"],
                              cwd=str(repo), capture_output=True, text=True).stdout

    def test_status_reports_only_what_it_can_see(self):
        none = self.status(self.repo(test=None))
        self.assertIn("acceptance gate: not configured: tests are honour-system", none)
        self.assertIn("CI: no workflow runs themis.py", none)
        self.assertNotIn("blocking", none)
        repo = self.repo()
        self.assertIn("configured (command %s -m unittest, floor 3, max skipped 0)" % sys.executable, self.status(repo))
        self.assertIn("last local gate: none or stale", self.status(repo))
        self.gate(repo)
        self.assertIn("last local gate: tree matches HEAD, 3 tests", self.status(repo))
        self.write(repo, "notes.txt", "a change\n")
        self.commit(repo, "another tree")
        self.assertIn("last local gate: none or stale", self.status(repo))

    def test_status_does_not_claim_the_server_checks_what_it_cannot_see(self):
        repo = self.repo()
        flows = repo / ".github" / "workflows"
        flows.mkdir(parents=True)
        (flows / "themis.yml").write_text("run: python3 tools/themis.py check --range a...b\n", encoding="utf-8")
        self.assertIn("none runs the gate", self.status(repo))
        (flows / "gate.yml").write_text('run: python3 "$T/themis.py" gate --range a...b\n', encoding="utf-8")
        wired = self.status(repo)
        self.assertIn("a required check, branch protection and trigger coverage are not verified", wired)
        self.assertNotIn("none runs the gate", wired)


class Presets(unittest.TestCase):
    """Each preset reads output captured from the real runner: python 3.9.6's
    unittest, pytest 8.4.2 and cargo 1.88.0; only the working directory was
    rewritten to /work. pytest's xfailed counts as skipped, since
    xfail(run=False) reports it without running the body; unittest's expected
    failures and cargo's should_panic tests do run their bodies."""

    CASES = (
        ("unittest", "unittest_pass_skip.txt", 5, 2),
        ("unittest", "unittest_fail.txt", 8, 3),
        ("unittest", "unittest_one.txt", 1, 0),
        ("unittest", "unittest_zero.txt", 0, 0),
        ("pytest", "pytest_pass.txt", 8, 2),
        ("pytest", "pytest_q_pass_rs.txt", 8, 2),
        ("pytest", "pytest_fail.txt", 10, 2),
        ("pytest", "pytest_q_fail.txt", 10, 2),
        ("pytest", "pytest_color_fail.txt", 10, 2),
        ("cargo", "cargo_pass.txt", 5, 2),
        ("cargo", "cargo_fail.txt", 4, 1),
    )

    def test_each_preset_reads_the_counts_in_real_output(self):
        for runner, name, total, skipped in self.CASES:
            with self.subTest(name):
                cfg, problems = gate.parse_test_config({"command": ["x"], "runner": runner})
                self.assertEqual(problems, [])
                text = gate.clean_output((FIXTURES / name).read_text(encoding="utf-8"))
                ran, skips, found = gate.judge(cfg, text, 0, False)
                self.assertEqual((ran, skips), (total - skipped, skipped), found)

    def test_a_pytest_suite_whose_only_test_is_xfail_without_running_it_fails_the_floor(self):
        cfg, _ = gate.parse_test_config({"command": ["x"], "runner": "pytest"})
        text = gate.clean_output((FIXTURES / "pytest_xfail_norun.txt").read_text(encoding="utf-8"))
        ran, skipped, problems = gate.judge(cfg, text, 0, False)
        self.assertEqual((ran, skipped), (0, 1))
        self.assertIn("0 test(s) ran, below the floor of 1", problems)

    def test_pytest_output_with_no_summary_count_is_no_count(self):
        cfg, _ = gate.parse_test_config({"command": ["x"], "runner": "pytest"})
        text = gate.clean_output((FIXTURES / "pytest_none.txt").read_text(encoding="utf-8"))
        self.assertEqual(gate.judge(cfg, text, 5, False)[0], None)

    def test_settings_that_cannot_work_are_refused_not_ignored(self):
        bad = ({"command": []}, {"command": ["x"]}, {"command": ["x"], "runner": "jest"},
               {"command": ["x"], "count_pattern": "Ran \\d+"}, {"command": ["x"], "count_pattern": "(", "runner": "pytest"},
               {"command": ["x"], "count_pattern": "(\\d+) ok", "max_skipped": 1},
               {"command": ["x"], "runner": "unittest", "min_tests": 0},
               {"command": ["x"], "runner": "unittest", "ignore_paths": [""]})
        for raw in bad:
            with self.subTest(raw):
                cfg, problems = gate.parse_test_config(raw)
                self.assertIsNone(cfg)
                self.assertTrue(problems)
        cfg, _ = gate.parse_test_config({"command": ["x"], "count_pattern": "(\\d+) ok"})
        self.assertIsNone(cfg.skip)


if __name__ == "__main__":
    unittest.main()
