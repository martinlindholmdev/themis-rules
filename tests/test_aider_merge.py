"""Purpose: reproduce and guard against Fable's release-review finding 7:
the Aider adapter must merge AGENTS.md into an existing `read:` key, not
append a second one — YAML keeps only the last of two duplicate keys, so
appending used to silently replace the owner's own `read` list.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: pure string function, no filesystem or git involved.
Never change without a decision: the three `read:` shapes covered.
"""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("install", ROOT / "install.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


class AiderReadMergeTests(unittest.TestCase):
    def test_a_bare_scalar_read_keeps_the_owners_file(self):
        merged = install._merge_aider_read("read: CONVENTIONS.md\n")
        self.assertIn("CONVENTIONS.md", merged)
        self.assertIn("AGENTS.md", merged)
        self.assertEqual(merged.count("read:"), 1)

    def test_a_flow_list_read_keeps_the_owners_files(self):
        merged = install._merge_aider_read("read: [CONVENTIONS.md, STYLE.md]\n")
        self.assertIn("CONVENTIONS.md", merged)
        self.assertIn("STYLE.md", merged)
        self.assertIn("AGENTS.md", merged)
        self.assertEqual(merged.count("read:"), 1)

    def test_a_block_list_read_keeps_the_owners_files(self):
        merged = install._merge_aider_read("read:\n  - CONVENTIONS.md\n  - STYLE.md\n")
        self.assertIn("CONVENTIONS.md", merged)
        self.assertIn("STYLE.md", merged)
        self.assertIn("AGENTS.md", merged)
        self.assertEqual(merged.count("read:"), 1)


if __name__ == "__main__":
    unittest.main()
