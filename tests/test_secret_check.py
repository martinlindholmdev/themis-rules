"""Purpose: check that secret_hits() catches a private-key block, an
OpenAI-shaped token and a long credential assignment, respects the inline
`themis: allow-secret` marker, and never echoes the matched text.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: reads only tests/fixtures/secrets.txt; writes nothing; every
line in that fixture carries the allow marker, so committing it never
trips this repo's own hook.
Never change without a decision: which fixture line proves which shape.
"""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "secrets.txt"

spec = importlib.util.spec_from_file_location("themis", ROOT / "tools" / "themis.py")
themis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(themis)

MARKER = "  themis: allow-secret"


def as_additions(strip_marker: bool):
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    out = []
    for number, line in enumerate(lines, start=1):
        text = line.replace(MARKER, "") if strip_marker else line
        out.append((str(FIXTURE), number, text))
    return out


class SecretCheckTests(unittest.TestCase):
    def test_marked_fixture_lines_are_all_allowed(self):
        self.assertEqual(themis.secret_hits(as_additions(strip_marker=False)), [])

    def test_same_lines_without_the_marker_are_caught(self):
        hits = themis.secret_hits(as_additions(strip_marker=True))
        # line 2 (short password) never matches; the other three do
        self.assertEqual(len(hits), 3)

    def test_matched_secret_text_is_never_echoed(self):
        hits = themis.secret_hits(as_additions(strip_marker=True))
        joined = " ".join(hits)
        self.assertNotIn("sk-1234567890abcdef1234", joined)  # themis: allow-secret
        self.assertNotIn("this-one-is-allowed-1234567890", joined)


if __name__ == "__main__":
    unittest.main()
