"""Purpose: check rule 2's header the way an owner would notice it: a new
source file without the four labelled fields is refused by the hook, plain
`check` and the CI range check, while existing files, renamed files and
files exempted before the change are left alone.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: every repo is a throwaway under a TemporaryDirectory with the
three tools files copied in; refusal lines never echo file text; this
repo's own checkout is only read.
Never change without a decision: which files count as new, and that the
base commit's themis.json, not the change's own, decides the exemptions.
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from headers import HASH, PY, SLASH

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
TOOLS = ("themis.py", "themis_lang.py", "themis_scan.py", "themis_gate.py")
INSTALL = ROOT / "install.py"
FIELDS = ["Purpose: guard the door.", "Entry points: open().", "Invariants: none.",
          "Never change without a decision: the name."]

spec = importlib.util.spec_from_file_location("themis", ROOT / "tools" / "themis.py")
themis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(themis)


def problem(text, ext):
    return themis.lang.header_problem(text, ext, themis.header_style("f" + ext))


def doc(lines):
    return '"""' + "\n".join(lines) + '\n"""\nimport os\n'


def comments(prefix, lines):
    return "".join("%s %s\n" % (prefix, line) for line in lines) + "code\n"


def block(lines):
    return "/*\n" + "".join(" * %s\n" % line for line in lines) + " */\ncode\n"


class ShapeTests(unittest.TestCase):
    def test_what_passes_and_what_is_refused_in_each_syntax(self):
        licence = "# Copyright the authors, MIT.\n\n"
        cases = [
            ("a full docstring", ".py", doc(FIELDS), True),
            ("a one-line docstring", ".py", '"""Does a thing."""\nimport os\n', False),
            ("# lines after a shebang and a coding line", ".py",
             "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n" + comments("#", FIELDS), True),
            ("labels in mixed case", ".py", doc([FIELDS[0].lower(), FIELDS[1].upper(), "invariants: none.",
                                                 "never CHANGE without A decision: the name."]), True),
            ("an empty label", ".py", doc(FIELDS[:1] + ["Entry points:"] + FIELDS[2:]), False),
            ("a TODO label", ".py", doc(["Purpose: TODO"] + FIELDS[1:]), False),
            ("a TBD label", ".py", doc(["Purpose: tbd later"] + FIELDS[1:]), False),
            ("a label without a colon", ".py", doc(["Purpose guard"] + FIELDS[1:]), False),
            ("a licence block apart from the header", ".py", licence + comments("#", FIELDS), True),
            ("a 30-line licence block apart from the header", ".py",
             "".join("# licence line %d\n" % i for i in range(30)) + "\n" + comments("#", FIELDS), True),
            ("a header that starts after code", ".py", "import os\n" + comments("#", FIELDS), False),
            ("a docstring made of one string literal in a variable", ".py",
             "x = '''\n" + "\n".join("# " + f for f in FIELDS) + "\n'''\n", False),
            ("a poor docstring after a good # block", ".py", comments("#", FIELDS) + '"""One line."""\n', True),
            ("an empty file", ".py", "\n\n", True),
            ("// lines", ".go", comments("//", FIELDS), True),
            ("/// lines", ".rs", comments("///", FIELDS), True),
            ("//! lines", ".rs", comments("//!", FIELDS), True),
            ("a /* */ block", ".c", block(FIELDS), True),
            ("a /** */ block all on one line", ".ts", "/** " + " ".join(FIELDS) + " */\ncode\n", False),
            ("-- lines", ".sql", comments("--", FIELDS), True),
            ("-- lines in Lua", ".lua", comments("--", FIELDS), True),
            ("# lines in a shell script", ".sh", "#!/bin/sh\n" + comments("#", FIELDS), True),
            ("a PHP opening tag then a block", ".php", "<?php\n" + block(FIELDS), True),
            ("a PHP block without an opening tag", ".php", block(FIELDS), True),
            ("a Rust licence with a nested comment, then a header", ".rs",
             "/* licence\n/* nested note */\nstill licence\n*/\n" + block(FIELDS), True),
            ("the same licence in C, where nesting does not exist", ".c",
             "/* licence\n/* nested note */\nstill licence\n*/\n" + block(FIELDS), False),
            ("a header after a licence closer on the same line", ".c",
             "/* MIT licence */ /*\n" + "\n".join(FIELDS) + "\n*/\nint x;\n", True),
            ("a // header after a licence closer on the same line", ".go",
             "/* MIT licence */ // " + FIELDS[0] + "\n" + comments("//", FIELDS[1:]), True),
            ("code after a block's closer", ".c",
             "/* MIT licence */ int y;\n" + block(FIELDS), False),
            ("a string literal that looks like a header", ".js",
             'const s = "// Purpose: guard the door.";\n' + comments("//", FIELDS[1:]), False),
            ("a header after a licence block", ".rs", "// MIT licence text\n\n" + comments("//", FIELDS), True),
        ]
        for name, ext, text, ok in cases:
            with self.subTest(name):
                self.assertEqual(problem(text, ext) is None, ok, problem(text, ext))

    def test_a_header_may_be_29_lines_and_not_30(self):
        filler = ["filler words here"]
        for name, ext, make, lines in (
                ("docstring", ".py", lambda n: doc(FIELDS + filler * n), 24),
                ("// run", ".go", lambda n: comments("//", FIELDS + filler * n), 25),
                ("/* */ block", ".c", lambda n: block(FIELDS + filler * n), 23),
                ("nested /* */ block", ".rs", lambda n: block(FIELDS + ["/* nested note */"] + filler * n), 22)):
            with self.subTest(name):
                self.assertIsNone(problem(make(lines), ext))
                self.assertIn("limit is 29", problem(make(lines + 1), ext))

    def test_unsupported_files_are_outside_the_check(self):
        for name in ("a.yml", "a.yaml", "data.json", "notes.txt", "a.vue"):
            with self.subTest(name):
                self.assertIsNone(themis.header_style(name))


class Repo:
    def __init__(self, tmp, config=None, commit=True):
        self.path = Path(tmp) / "repo"
        (self.path / "tools").mkdir(parents=True)
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        for name in TOOLS:
            (self.path / "tools" / name).write_bytes((ROOT / "tools" / name).read_bytes())
        self.write("themis.json", json.dumps(dict(config or {}, version="v3.3")))
        self.write("main.py", "x = 1\n")
        if commit:
            self.commit("base")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.path)] + list(args), check=True,
                              capture_output=True, text=True)

    def write(self, rel, text):
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self, message="c"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message, "--no-verify")

    def check(self, *args):
        result = subprocess.run([sys.executable, str(self.path / "tools" / "themis.py"), "check"] + list(args),
                                cwd=str(self.path), capture_output=True, text=True)
        return result.returncode, result.stdout + result.stderr

    def staged(self):
        return self.check("--staged")

    def head(self):
        return self.git("rev-parse", "HEAD").stdout.strip()


class GitTests(unittest.TestCase):
    def repo(self, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Repo(tmp.name, **kwargs)

    def test_the_hook_refuses_a_new_file_and_says_what_is_missing_without_echoing_it(self):
        repo = self.repo()
        for name, text in (("util.py", '"""Purpose: guard the door.\nSECRETWORD."""\nx = 1\n'),
                           ("gen.go", "// Code generated by hand. DO NOT EDIT.\npackage gen\n")):
            with self.subTest(name):
                repo.write(name, text)
                repo.git("add", name)
                code, out = repo.staged()
                self.assertEqual(code, 1, out)
                self.assertIn("%s: new file has no valid header" % name, out)
                self.assertNotIn("SECRETWORD", out)
                self.assertEqual(out.count("%s: new file has no valid header" % name), 1, out)
                repo.git("reset", "-q", name)
        repo.write("util.py", '"""Purpose: guard the door.\nSECRETWORD."""\nx = 1\n')
        repo.git("add", "util.py")
        self.assertIn("missing Entry points, Invariants, Never change without a decision", repo.staged()[1])

    def test_a_new_file_with_a_header_passes_and_old_and_renamed_files_are_not_flagged(self):
        repo = self.repo()
        repo.write("ok.py", PY + "x = 1\n")
        repo.git("add", "ok.py")
        self.assertEqual(repo.staged()[0], 0, repo.staged()[1])
        repo.git("mv", "main.py", "renamed.py")
        repo.git("add", "renamed.py")
        code, out = repo.staged()
        self.assertEqual(code, 0, out)
        repo.commit()
        repo.write("renamed.py", "x = 3\n")
        repo.git("add", "renamed.py")
        self.assertEqual(repo.staged()[0], 0)
        self.assertEqual(repo.check()[0], 0)

    def test_plain_check_reads_the_working_tree_and_counts_untracked_files_as_new(self):
        repo = self.repo()
        repo.write("late.py", "x = 1\n")
        code, out = repo.check()
        self.assertEqual(code, 1, out)
        self.assertIn("late.py: new file has no valid header", out)
        repo.git("add", "late.py")
        repo.write("late.py", HASH + "x = 1\n")
        self.assertEqual(repo.staged()[0], 1)
        self.assertEqual(repo.check()[0], 0, repo.check()[1])
        repo.write("main.py", "x = 5\n")
        self.assertEqual(repo.check()[0], 0)

    def test_without_a_base_config_the_check_is_skipped_with_one_note(self):
        fresh = self.repo(commit=False)
        fresh.write("new.py", "x = 1\n")
        fresh.git("add", "-A")
        code, out = fresh.staged()
        self.assertEqual((code, "header check skipped" in out), (0, True), out)
        only_tools = self.repo(commit=False)
        only_tools.git("add", "themis.json", "tools")
        code, out = only_tools.staged()
        self.assertEqual(code, 0, out)
        self.assertIn("header check skipped", out)
        self.assertIn("0 staged source files", out)
        no_config = self.repo(commit=False)
        no_config.git("add", "main.py")
        no_config.git("commit", "-q", "-m", "plain", "--no-verify")
        no_config.write("new.py", "x = 1\n")
        no_config.git("add", "-A")
        code, out = no_config.staged()
        self.assertEqual(code, 0, out)
        self.assertIn("header check skipped", out)

    def test_only_an_exemption_already_committed_at_the_base_takes_effect(self):
        repo = self.repo()
        repo.write("themis.json", json.dumps({"version": "v3.3", "header_exempt_prefixes": ["gen/"]}))
        repo.write("gen/x.py", "x = 1\n")
        repo.git("add", "themis.json", "gen/x.py")
        code, out = repo.staged()
        self.assertEqual(code, 1, out)
        self.assertIn("gen/x.py: new file has no valid header", out)
        self.assertEqual(repo.check()[0], 1)
        base = repo.head()
        repo.commit("exemption and file together")
        code, out = repo.check("--range", base + "..." + repo.head())
        self.assertEqual(code, 1, out)
        self.assertIn("gen/x.py", out)
        exempted = self.repo(config={"header_exempt_prefixes": ["gen/"]})
        exempted.write("gen/x.py", "x = 1\n")
        exempted.git("add", "gen/x.py")
        self.assertEqual(exempted.staged()[0], 0)
        self.assertEqual(exempted.check()[0], 0)
        measured = self.repo(config={"exempt_prefixes": ["vendor/"], "exempt_files": {"odd.py": "imported"}})
        measured.write("vendor/y.py", "x = 1\n")
        measured.write("odd.py", "x = 1\n")
        measured.git("add", "vendor/y.py", "odd.py")
        self.assertEqual(measured.staged()[0], 0, measured.staged()[1])
        switched_off = self.repo(config={"header_exempt_prefixes": [""]})
        switched_off.write("any.py", "x = 1\n")
        switched_off.git("add", "any.py")
        self.assertEqual(switched_off.staged()[0], 0)

    def test_the_range_check_refuses_a_file_added_between_two_commits(self):
        repo = self.repo()
        base = repo.head()
        repo.write("added.py", "x = 1\n")
        repo.write("good.py", PY + "x = 1\n")
        repo.commit("add two")
        code, out = repo.check("--range", base + "..." + repo.head())
        self.assertEqual(code, 1, out)
        self.assertIn("added.py: new file has no valid header", out)
        self.assertNotIn("good.py", out)
        repo.git("rm", "-q", "added.py")
        repo.commit("remove it")
        self.assertEqual(repo.check("--range", base + "..." + repo.head())[0], 0)


class UpgradeTests(unittest.TestCase):
    def test_an_upgrade_keeps_owner_config_and_grandfathers_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Repo(tmp, commit=False)
            old = {"version": "v3.2", "decision_log": "DECISIONS.md", "exempt_prefixes": ["vendor/"],
                   "limits": {".ts": {"file": 500}}, "header_exempt_prefixes": ["gen/"]}
            repo.write("themis.json", json.dumps(old))
            rules = (ROOT / "RULES.md").read_text(encoding="utf-8").replace("v3.4", "v3.2")
            repo.write("AGENTS.md", rules)
            repo.commit("a v3.2 install")
            done = subprocess.run([sys.executable, str(INSTALL), "install", "--defaults", "--yes"],
                                  cwd=str(repo.path), capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            config = json.loads((repo.path / "themis.json").read_text(encoding="utf-8"))
            self.assertEqual(config["version"], "v3.4")
            for key in ("exempt_prefixes", "limits", "header_exempt_prefixes"):
                self.assertEqual(config[key], old[key])
            repo.commit("upgrade")
            repo.write("main.py", "x = 2\n")
            repo.git("add", "main.py")
            self.assertEqual(repo.staged()[0], 0)
            repo.write("fresh.py", "x = 1\n")
            repo.git("add", "fresh.py")
            self.assertEqual(repo.staged()[0], 1)


if __name__ == "__main__":
    unittest.main()
