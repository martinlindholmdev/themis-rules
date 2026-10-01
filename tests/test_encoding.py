"""Purpose: reproduce and guard against an independent release review's finding 1
(CI red on Windows): `_git()`/`git_root()` must decode git's output as
UTF-8 explicitly, never the platform's default text encoding, or a
non-ASCII filename comes back mangled (cp1252 silently mis-decodes UTF-8
bytes instead of raising) and the hook sees "0 files measured".
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: never touches the real git binary or locale; a fake
`subprocess.run` simulates exactly the byte-for-byte difference between
an explicit UTF-8 decode and a platform-default one.
Never change without a decision: the byte sequence this test decodes.
"""

import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("themis", ROOT / "tools" / "themis.py")
themis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(themis)

RAW_BYTES = "café.py\n".encode("utf-8")


def fake_subprocess_run(cmd, **kwargs):
    """Stands in for git: returns the same UTF-8 bytes either way, but
    decodes them the way the *caller's own kwargs* say to — exactly the
    axis finding 1 is about, with no real OS or locale involved."""
    encoding = kwargs.get("encoding")
    if kwargs.get("text") and not encoding:
        encoding = "cp1252"  # the platform-default a Windows runner hit
    text = RAW_BYTES.decode(encoding or "utf-8", errors=kwargs.get("errors", "strict"))
    return subprocess.CompletedProcess(cmd, 0, stdout=text, stderr="")


class GitDecodingTests(unittest.TestCase):
    def test_git_output_is_decoded_as_utf8_regardless_of_platform_default(self):
        with mock.patch("subprocess.run", side_effect=fake_subprocess_run):
            out = themis._git(Path("."), "ls-files")
        self.assertEqual(out, "café.py\n")

    def test_git_root_is_also_decoded_as_utf8(self):
        raw = "/repo/café\n".encode("utf-8")

        def fake(cmd, **kwargs):
            encoding = kwargs.get("encoding")
            if kwargs.get("text") and not encoding:
                encoding = "cp1252"
            text = raw.decode(encoding or "utf-8", errors=kwargs.get("errors", "strict"))
            return subprocess.CompletedProcess(cmd, 0, stdout=text, stderr="")

        with mock.patch("subprocess.run", side_effect=fake):
            out = themis.git_root()
        # compare as Path, not str: Path("/repo/café") renders with
        # backslashes on Windows, which a literal forward-slash string
        # would never match even when decoding is correct.
        self.assertEqual(out, Path("/repo/café"))


if __name__ == "__main__":
    unittest.main()
