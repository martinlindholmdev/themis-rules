"""Purpose: prove the test-tamper tripwire the way an owner would notice it:
a deleted test file, a dropped table row, an added skip and a removed test are
listed, a lossless rewrite into a table is not blocked, no literal value ever
reaches the output, and the modes, the owner's allow list and a missing
optional file behave as documented.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: every repository is a throwaway; each case is judged by both the
hook's `check --staged` and CI's `check --range`, which must agree; a
credential-shaped string removed from a test is looked for in the full
captured output of both.
Never change without a decision: which finding kinds block in block mode and
the promise that a literal is reported by place and count, never by value.
"""

import json
import tempfile
import unittest

from review_repo import Repo, TOOLS

SECRET = "sk-" + "abcdef0123456789abcdQX"


def many(n):
    body = "".join('    def test_%d(self):\n        self.assertEqual(conv("in%d"), "out%d")\n' % (i, i, i)
                   for i in range(n))
    return "import unittest\n\n\nclass T(unittest.TestCase):\n" + body


def tabular(rows):
    cases = "".join('    ("%s", "%s"),\n' % row for row in rows)
    return ("import unittest\n\nCASES = [\n" + cases + "]\n\n\nclass T(unittest.TestCase):\n"
            "    def test_all(self):\n        for src, want in CASES:\n"
            "            self.assertEqual(conv(src), want)\n")


def two(first, second):
    """Two tests, each one assertion over a (string, number) pair."""
    return ("import unittest\n\n\nclass T(unittest.TestCase):\n"
            "    def test_a(self):\n        self.assertEqual(f(%s), %s)\n"
            "    def test_b(self):\n        self.assertEqual(g(%s), %s)\n" % (first + second))


A = "tests/test_a.py"
ALPHA = ('"alpha"', "11")
BETA = ('"beta"', "22")
MOVED = "    def test_m(self):\n        self.assertEqual(h('zeta'), 77)\n"
HEAD = "import unittest\n\n\nclass T(unittest.TestCase):\n"
IGNORED = HEAD + ('    def test_a(self):\n        self.assertEqual(f("alpha"), 11)\n'
                  '    def test_b(self):\n        """Explains why b matters."""\n        self.assertEqual(g(""), 1)\n'
                  '        self.assertIsNone(h(0))\n')
CREDENTIAL = 'import os\n\nKEY = "%s"\n\n\ndef test_login():\n    assert login(KEY) == 31\n' % SECRET
FIXED = 'import os\n\nKEY = os.environ["KEY"]\n\n\ndef test_login():\n    assert login(KEY) == 31\n'

# name, mode, files at the base, files after the change (None deletes), whether
# block mode fails, phrases the output holds, phrases it does not
ROWS = [
    ("a deleted test file", "note", {A: many(2)}, {A: None}, False, ["note: tests/test_a.py: test file deleted"], []),
    ("a deleted test file in block mode", "block", {A: many(2)}, {A: None}, True, ["test file deleted"], []),
    ("a removed function whose literals die", "block", {A: two(ALPHA, BETA)}, {A: two(ALPHA, ALPHA)},
     True, ["literal(s) of the base version occur in no changed test file"], []),
    ("a removed function whose literals live on elsewhere", "block", {A: two(ALPHA, ALPHA)},
     {A: two(ALPHA, ALPHA).split("    def test_b")[0]}, False,
     ["1 test function(s) removed: T.test_b", "assertions fell from 2 to 1"], ["literal(s)"]),
    ("49 functions rewritten as a table keeping every case", "block", {A: many(49)},
     {A: tabular([("in%d" % i, "out%d" % i) for i in range(49)])}, False,
     ["49 test function(s) removed", "assertions fell from 49 to 1"], ["literal(s)"]),
    ("a row dropped from an already tabular test", "block", {A: tabular([("p", "q"), ("r", "s"), ("t", "u")])},
     {A: tabular([("p", "q"), ("t", "u")])}, True, ["2 literal(s)"], []),
    ("a dropped row whose literals all survive is the documented miss", "block",
     {A: tabular([("a", "x"), ("b", "y"), ("a", "y")])}, {A: tabular([("a", "x"), ("b", "y")])}, False, [],
     ["note:", "literal(s)"]),
    ("a removed function with only ignored constants and a docstring", "block", {A: IGNORED},
     {A: IGNORED.split("    def test_b")[0]}, False, ["1 test function(s) removed"], ["literal(s)"]),
    ("a skip added", "block", {A: many(1)}, {A: many(1).replace("    def test_0", '    @unittest.skip("later")\n    def test_0')},
     True, ["1 skip, xfail or ignore marker(s) added"], []),
    ("assertEqual changed to assertTrue", "block", {A: two(ALPHA, BETA)},
     {A: two(ALPHA, BETA).replace("assertEqual(g(\"beta\"), 22)", "assertTrue(g(\"beta\"))")}, True,
     ["1 literal(s)"], []),
    ("a function moved unchanged to another file", "block",
     {A: HEAD + MOVED + two(ALPHA, ALPHA).split("class T(unittest.TestCase):\n")[1], "tests/test_b.py": "import unittest\n"},
     {A: two(ALPHA, ALPHA), "tests/test_b.py": HEAD + MOVED}, False, ["assertions fell"], ["removed", "literal(s)"]),
    ("a file that is not a test", "block", {"lib.py": 'X = "k"\nY = 99\n'}, {"lib.py": None}, False, [], ["note:", "literal"]),
    ("more than ten findings are capped", "note", {"tests/test_f%d.py" % i: many(1) for i in range(12)},
     {"tests/test_f%d.py" % i: None for i in range(12)}, False, ["and 2 more tripwire note(s)"], []),
    ("a credential removed from a test, note mode", "note", {A: CREDENTIAL}, {A: FIXED}, False, ["literal(s)"], []),
    ("a credential removed from a test, block mode", "block", {A: CREDENTIAL}, {A: FIXED}, True, ["literal(s)"], []),
]


class Tamper(unittest.TestCase):
    def repo(self, config=None, tools=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Repo(tmp.name, config, **({"tools": tools} if tools else {}))

    def judge(self, repo, base_files, changes, ok, phrases=(), absent=()):
        """Both the hook and CI judge the change the same way."""
        for rel, text in base_files.items():
            repo.write(rel, text)
        base = repo.commit("base")
        for rel, text in changes.items():
            repo.remove(rel) if text is None else repo.write(rel, text)
        repo.git("add", "-A")
        staged = repo.staged()
        repo.commit("change")
        outputs = []
        for done in (staged, repo.range(base)):
            self.assertEqual(done.returncode, 0 if ok else 1, repo.out(done))
            for phrase in phrases:
                self.assertIn(phrase, repo.out(done))
            for phrase in absent:
                self.assertNotIn(phrase, repo.out(done))
            outputs.append(repo.out(done))
        return outputs

    def test_the_tripwire_lists_what_a_change_removed_and_never_prints_a_value(self):
        for name, mode, base_files, changes, fails, phrases, absent in ROWS:
            with self.subTest(name):
                repo = self.repo({"tamper": {"mode": mode}})
                outputs = self.judge(repo, base_files, changes, not (fails and mode == "block"), phrases, absent)
                if "credential" in name:
                    for out in outputs:
                        windows = [SECRET[i:i + 8] for i in range(len(SECRET) - 7)]
                        self.assertFalse([w for w in windows if w in out], out)
                if "capped" in name:
                    self.assertEqual(sum(1 for line in outputs[0].splitlines() if line.startswith("note: tests/")), 10)

    def test_modes_the_owners_allow_list_and_a_missing_optional_file(self):
        delete = {A: None}
        base = {A: many(2)}
        quiet = ["tripwire", "test file deleted"]
        self.judge(self.repo({}), base, delete, True, ["note: tests/test_a.py: test file deleted"])
        self.judge(self.repo({"tamper": {"mode": "off"}}), base, delete, True, [], quiet)
        self.judge(self.repo({"tamper": {"mode": "block", "allow": [A]}}), base, delete, True, [], quiet)
        self.judge(self.repo({"tamper": {"mode": "block", "allow": [A + "::test_b"]}}), {A: two(ALPHA, BETA)},
                   {A: two(ALPHA, ALPHA).split("    def test_b")[0]}, True, [], ["literal(s)", "removed"])
        edits = self.repo({"tamper": {"mode": "block"}})
        edits.write("themis.json", json.dumps({"tamper": {"mode": "block"}, "version": "v3.6.0"}))
        allow_now = {A: None, "themis.json": json.dumps({"tamper": {"mode": "block", "allow": [A]}})}
        self.judge(edits, base, allow_now, False, ["test file deleted"])
        self.judge(self.repo({"tamper": {"mode": "loud"}}), base, delete, False, ["tamper.mode must be"])
        gone = ["tools/themis_review.py not found"]
        self.judge(self.repo({"tamper": {"mode": "block"}}, tools=TOOLS), base, delete, False, gone)
        self.judge(self.repo({}, tools=TOOLS), base, delete, True, [], gone + ["tripwire"])


if __name__ == "__main__":
    unittest.main()
