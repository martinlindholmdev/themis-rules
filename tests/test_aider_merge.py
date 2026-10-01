"""Purpose: reproduce and guard against Fable's release-review finding 7
and re-check must-fix 3: the Aider adapter must add AGENTS.md to an
existing `read:` key without ever touching the owner's own entries — not
by appending a second `read:` key (YAML keeps only the last of two
duplicates, silently replacing the owner's list), and not by sharing a
line with the owner's values (uninstall strips whole lines carrying the
themis marker, so a flow list's single line was destroying everything
the owner had on it).
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: pure string functions, no filesystem or git involved.
Never change without a decision: which `read:` shapes can be edited
safely (bare scalar, block list) versus which cannot (flow list).
"""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("install", ROOT / "install.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


class AiderReadMergeTests(unittest.TestCase):
    def test_a_bare_scalar_read_survives_install_then_uninstall(self):
        original = "read: CONVENTIONS.md\n"
        merged = install._merge_aider_read(original)
        self.assertIn("CONVENTIONS.md", merged)
        self.assertIn("AGENTS.md", merged)
        self.assertEqual(merged.count("read:"), 1)
        restored = install._strip_marked_lines(merged, "# themis")
        self.assertIn("CONVENTIONS.md", restored)
        self.assertNotIn("AGENTS.md", restored)

    def test_a_block_list_read_survives_install_then_uninstall(self):
        original = "read:\n  - CONVENTIONS.md\n  - STYLE.md\n"
        merged = install._merge_aider_read(original)
        self.assertIn("CONVENTIONS.md", merged)
        self.assertIn("STYLE.md", merged)
        self.assertIn("AGENTS.md", merged)
        self.assertEqual(merged.count("read:"), 1)
        restored = install._strip_marked_lines(merged, "# themis")
        self.assertIn("CONVENTIONS.md", restored)
        self.assertIn("STYLE.md", restored)
        self.assertNotIn("AGENTS.md", restored)

    def test_a_flow_list_read_is_left_untouched_not_merged(self):
        """The regression: read: [CONVENTIONS.md, AGENTS.md]  # themis put
        the owner's CONVENTIONS.md on the same line as the marker, so
        uninstall's line-strip deleted the owner's entry along with it."""
        original = "read: [CONVENTIONS.md, STYLE.md]\n"
        self.assertIsNone(install._merge_aider_read(original))


if __name__ == "__main__":
    unittest.main()
