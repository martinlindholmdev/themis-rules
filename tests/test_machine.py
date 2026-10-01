"""Purpose: check the machine-part writer against a fake HOME — the table
only writes into a config folder that exists, confirms on a TTY, never
duplicates the pointer on a second run, and respects Windsurf's cap.
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: HOME is monkeypatched to a TemporaryDirectory; never touches
the real $HOME; `install.py`'s own module is loaded once and reused.
Never change without a decision: which three agents this test simulates.
"""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("install", ROOT / "install.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


class MachineTableTests(unittest.TestCase):
    def test_table_paths_are_built_from_the_given_home(self):
        # some CI runners set XDG_CONFIG_HOME themselves; this test is
        # about the HOME-relative default, so it must not inherit that.
        env = dict(os.environ)
        env.pop("XDG_CONFIG_HOME", None)
        with mock.patch.dict("os.environ", env, clear=True):
            home = Path("/fake/home")
            table = dict((name, path) for name, _, path in install.machine_table(home))
        self.assertEqual(table["Claude Code"], home / ".claude" / "rules" / "themis.md")
        self.assertEqual(table["Goose"], home / ".config" / "goose" / ".goosehints")

    def test_only_agents_whose_config_folder_exists_are_offered(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir()
            present = [name for name, config_dir, _ in install.machine_table(home) if config_dir.is_dir()]
            self.assertEqual(present, ["Claude Code"])

    def test_xdg_config_home_is_honoured_for_config_paths(self):
        home = Path("/fake/home")
        with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": "/custom/config"}):
            table = dict((name, path) for name, _, path in install.machine_table(home))
        self.assertEqual(table["Goose"], Path("/custom/config/goose/.goosehints"))
        self.assertEqual(table["Amp"], Path("/custom/config/amp/AGENTS.md"))

    def test_zed_on_windows_uses_appdata_not_dot_config(self):
        home = Path("/fake/home")
        with mock.patch.dict("os.environ", {"APPDATA": "C:\\Users\\t\\AppData\\Roaming"}), \
             mock.patch("sys.platform", "win32"):
            table = dict((name, path) for name, _, path in install.machine_table(home))
        self.assertEqual(table["Zed"], Path("C:\\Users\\t\\AppData\\Roaming") / "Zed" / "AGENTS.md")


class WriteMachineFileTests(unittest.TestCase):
    def test_confirmed_write_creates_the_pointer_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rules" / "themis.md"
            with mock.patch("builtins.input", return_value="y"):
                message = install.write_machine_file("Claude Code", path, interactive=True)
            self.assertIn("written", message)
            self.assertIn(install.POINTER_BEGIN, path.read_text(encoding="utf-8"))

    def test_a_second_write_does_not_duplicate_the_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "AGENTS.md"
            with mock.patch("builtins.input", return_value="y"):
                install.write_machine_file("Codex", path, interactive=True)
                message = install.write_machine_file("Codex", path, interactive=True)
            self.assertIn("already set up", message)
            self.assertEqual(path.read_text(encoding="utf-8").count(install.POINTER_BEGIN), 1)

    def test_existing_file_is_backed_up_before_appending(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "GEMINI.md"
            path.write_text("# my own notes\n", encoding="utf-8")
            with mock.patch("builtins.input", return_value="y"):
                install.write_machine_file("Gemini", path, interactive=True)
            backup = Path(str(path) + ".themis-backup")
            self.assertEqual(backup.read_text(encoding="utf-8"), "# my own notes\n")

    def test_declining_leaves_the_file_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "AGENTS.md"
            with mock.patch("builtins.input", return_value="n"):
                message = install.write_machine_file("Amp", path, interactive=True)
            self.assertIn("skipped", message)
            self.assertFalse(path.exists())

    def test_non_interactive_only_prints_the_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "AGENTS.md"
            message = install.write_machine_file("Zed", path, interactive=False)
            self.assertIn("no TTY", message)
            self.assertFalse(path.exists())

    def test_windsurf_cap_is_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "global_rules.md"
            path.write_text("x" * 5990, encoding="utf-8")
            message = install.write_machine_file("Windsurf", path, interactive=True)
            self.assertIn("skipped", message)

    def test_a_symlinked_dotfile_is_rejected_before_prompting(self):
        """Astra's re-check 'also': a symlinked dotfile was treated as
        absent (current=None), skipping the backup, then written through —
        it must be rejected outright, before any prompt."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            sentinel = tmp / "sentinel.md"
            sentinel.write_text("DO NOT TOUCH\n", encoding="utf-8")
            path = tmp / "AGENTS.md"
            path.symlink_to(sentinel)
            with mock.patch("builtins.input", side_effect=AssertionError("must not prompt")):
                message = install.write_machine_file("Codex", path, interactive=True)
            self.assertIn("symlink", message)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "DO NOT TOUCH\n")


if __name__ == "__main__":
    unittest.main()
