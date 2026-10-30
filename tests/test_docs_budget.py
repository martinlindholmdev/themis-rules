"""Purpose: prove the documentation budget the way an owner would notice it:
an instruction document over its cap, a total over its cap and a dead local
link each refuse a change; the vendored rules block is not counted; and an
existing repository can adopt the budget with its debt recorded but cannot
record new debt as old or grow beside its own record.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: every repository is a throwaway; each case is judged both by the
hook's `check --staged` and by CI's `check --range`, which must agree; no
case depends on the checkout's own documents.
Never change without a decision: the cap, total, link and adoption rules in
docs/checks.md that these cases pin.
"""

import json
import tempfile
import unittest

from review_repo import Repo, TOOLS

LINES = lambda n, word="line": "".join("%s %d\n" % (word, i) for i in range(n))
BLOCK = "<!-- themis v3.6.0 begin -->\n" + LINES(50, "rule") + "<!-- themis v3.6.0 end -->\n"
CAPS = {"docs": {"caps": {"AGENTS.md": 10}, "total": 600}}
LINKS = {"docs": {"caps": {"AGENTS.md": 10}, "total": 600, "check_links": True}}

# name, config, files at the base, files after the change, removed after, ok, phrase
ROWS = [
    ("under the cap", CAPS, {}, {"AGENTS.md": LINES(9)}, [], True, ""),
    ("over the cap", CAPS, {}, {"AGENTS.md": LINES(12)}, [], False, "12 counted lines"),
    ("the vendored rules block is not counted", CAPS, {}, {"AGENTS.md": LINES(5) + BLOCK}, [], True, ""),
    ("an imported file counts toward the total",
     {"docs": {"caps": {"CLAUDE.md": 100}, "total": 25}}, {},
     {"CLAUDE.md": "@docs/big.md\n", "docs/big.md": LINES(30)}, [], False, "in all"),
    ("no docs key is silent", {}, {}, {"AGENTS.md": LINES(900)}, [], True, ""),
    ("a dead file link", LINKS, {}, {"AGENTS.md": "[x](missing.md)\n"}, [], False, "dead local link"),
    ("a dead directory link", LINKS, {}, {"AGENTS.md": "[x](nowhere/)\n"}, [], False, "dead local link"),
    ("a live file and a live directory link", LINKS, {"docs/a.md": "a\n"},
     {"AGENTS.md": "[x](docs/a.md#top) [y](docs/) ![i](docs/a.md?v=1)\n"}, [], True, ""),
    ("a link in a fence or code span is ignored", LINKS, {},
     {"AGENTS.md": "```\n[x](missing.md)\n```\n`[y](gone.md)`\n"}, [], True, ""),
    ("external and fragment-only links are ignored", LINKS, {},
     {"AGENTS.md": "[a](https://example.com/x) [b](mailto:a@example.com) [c](#top)\n"}, [], True, ""),
    ("a link to a file deleted in the same change", LINKS, {"docs/a.md": "a\n", "AGENTS.md": "[x](docs/a.md)\n"},
     {}, ["docs/a.md"], False, "dead local link"),
]


class DocsBudget(unittest.TestCase):
    def repo(self, config, baseline=None, tools=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Repo(tmp.name, config, baseline=baseline, **({"tools": tools} if tools else {}))

    def test_caps_totals_and_dead_links_judge_a_change_by_hook_and_by_ci(self):
        for name, config, base_files, files, removed, ok, phrase in ROWS:
            with self.subTest(name):
                repo = self.repo(config)
                for rel, text in base_files.items():
                    repo.write(rel, text)
                base = repo.commit("base")
                for rel, text in files.items():
                    repo.write(rel, text)
                for rel in removed:
                    repo.remove(rel)
                repo.git("add", "-A")
                staged = repo.staged()
                repo.commit("change")
                ranged = repo.range(base)
                for done in (staged, ranged):
                    self.assertEqual(done.returncode, 0 if ok else 1, repo.out(done))
                    self.assertIn(phrase, repo.out(done))

    def adoption_repo(self):
        repo = self.repo({})
        repo.write("AGENTS.md", LINES(40))
        repo.write("README.md", "[a](gone.md) [b](also-gone.md)\n")
        repo.commit("base")
        self.assertEqual(repo.rebaseline().returncode, 0)
        base = repo.commit("baseline")
        config = {"docs": {"caps": {"AGENTS.md": 30}, "total": 600, "check_links": True}, "version": "v3.6.0"}
        repo.write("themis.json", json.dumps(config))
        return repo, base

    def judged(self, repo, base, ok, phrase=""):
        """The change in the index, then committed, is judged the same by hook and CI."""
        repo.git("add", "-A")
        staged = repo.staged()
        repo.commit("change")
        for done in (staged, repo.range(base)):
            self.assertEqual(done.returncode, 0 if ok else 1, repo.out(done))
            self.assertIn(phrase, repo.out(done))

    def test_adoption_records_old_debt_refuses_new_debt_and_fails_closed_without_the_review_file(self):
        self.adopt_with_debt_recorded()
        self.refuse_debt_recorded_as_old()
        self.lower_and_fail_closed()

    def adopt_with_debt_recorded(self):
        repo, base = self.adoption_repo()
        seeded = repo.rebaseline()
        self.assertEqual(seeded.returncode, 0, repo.out(seeded))
        self.assertIn("lines AGENTS.md 40", seeded.stdout)
        self.assertIn("dead_links README.md 2", seeded.stdout)
        self.judged(repo, base, True)
        repo.write("README.md", "[a](gone.md) [b](also-gone.md) [c](third.md)\n")
        repo.git("add", "-A")
        grown_link = repo.staged()
        self.assertEqual(grown_link.returncode, 1, repo.out(grown_link))
        self.assertIn("3 dead local link(s) (baseline allows 2)", repo.out(grown_link))
        repo.git("reset", "-q", "--hard")
        repo.write("AGENTS.md", LINES(41))
        repo.git("add", "-A")
        grown_doc = repo.staged()
        self.assertEqual(grown_doc.returncode, 1, repo.out(grown_doc))
        self.assertIn("41 counted lines, over the cap of 40", repo.out(grown_doc))

    def refuse_debt_recorded_as_old(self):
        for name, section, entry, files, phrase in (
                ("a document grown beside its entry", None, None, {"AGENTS.md": LINES(45)}, "below the 45"),
                ("a dead link added beside its entry", None, None,
                 {"README.md": "[a](x) [b](y) [c](z)\n"}, "below the 3"),
                ("an entry above what the base measures", "lines", ("AGENTS.md", 50), {}, "above the 40"),
                ("an entry for a path the base does not have", "dead_links", ("NEW.md", 1),
                 {"NEW.md": "[a](nope)\n"}, "does not have")):
            with self.subTest(name):
                repo, base = self.adoption_repo()
                self.assertEqual(repo.rebaseline().returncode, 0)
                if section:
                    path = repo.path / "themis-baseline.json"
                    data = json.loads(path.read_text(encoding="utf-8"))
                    data["docs"][section][entry[0]] = entry[1]
                    path.write_text(json.dumps(data), encoding="utf-8")
                for rel, text in files.items():
                    repo.write(rel, text)
                self.judged(repo, base, False, phrase)

    def lower_and_fail_closed(self):
        repo, base = self.adoption_repo()
        self.assertEqual(repo.rebaseline().returncode, 0)
        self.judged(repo, base, True)
        after = repo.git("rev-parse", "HEAD")
        repo.write("AGENTS.md", LINES(35))
        path = repo.path / "themis-baseline.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["docs"]["lines"]["AGENTS.md"] = 35
        path.write_text(json.dumps(data), encoding="utf-8")
        self.judged(repo, after, True)
        bare, bare_base = self.adoption_repo()
        (bare.path / "tools" / "themis_review.py").unlink()
        self.assertEqual(bare.rebaseline().returncode, 1)
        bare.write("themis-baseline.json", json.dumps({"files": {}, "docs": {"lines": {"AGENTS.md": 40}}}))
        bare.git("add", "-A")
        done = bare.staged()
        self.assertEqual(done.returncode, 1, bare.out(done))
        self.assertIn("tools/themis_review.py not found", bare.out(done))


if __name__ == "__main__":
    unittest.main()
