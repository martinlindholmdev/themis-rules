"""Purpose: check that themis.py's measuring catches an oversized
function, a history-word comment, and a clean file, across two languages.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: reads only the fixtures in tests/fixtures/; writes nothing.
Never change without a decision: which fixture proves which rule.
"""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

spec = importlib.util.spec_from_file_location("themis", ROOT / "tools" / "themis.py")
themis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(themis)

CONFIG = themis.load_config(ROOT)
PATTERN = themis.history_pattern(CONFIG)
EMPTY_BASELINE = {"files": {}, "functions": {}, "history_words": {}}


def measure(name):
    path = FIXTURES / name
    return themis.measure_file(str(path), path.read_text(encoding="utf-8"), PATTERN)


class MeasuringTests(unittest.TestCase):
    def test_clean_python_file_has_no_problems(self):
        found = themis.Findings()
        themis.check_file(measure("clean.py"), EMPTY_BASELINE, CONFIG, found)
        self.assertEqual(found.problems, [])

    def test_oversized_function_is_a_problem(self):
        found = themis.Findings()
        themis.check_file(measure("big_function.py"), EMPTY_BASELINE, CONFIG, found)
        self.assertTrue(any("oversized" in p and "over the 100-line limit" in p for p in found.problems))

    def test_history_word_in_a_javascript_comment_is_a_problem(self):
        found = themis.Findings()
        themis.check_file(measure("history.js"), EMPTY_BASELINE, CONFIG, found)
        self.assertTrue(any("read as history" in p for p in found.problems))

    def test_baseline_already_at_todays_size_is_not_a_problem(self):
        big = measure("big_function.py")
        baseline = {"files": {}, "functions": {big.path: dict(big.functions)}, "history_words": {}}
        found = themis.Findings()
        themis.check_file(big, baseline, CONFIG, found)
        self.assertEqual(found.problems, [])


if __name__ == "__main__":
    unittest.main()
