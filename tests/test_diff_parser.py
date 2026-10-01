"""Purpose: reproduce and guard against GPT-6 Astra's re-check finding
[5]: an added line whose own content is "++ something" is rendered by
git as "+++ something" — identical to a real unified-diff file-header
line — so the old parser mistook it for one, corrupting the path
attached to every addition that followed (and, in a multi-file diff,
could suppress scanning a later file entirely).
Entry points: run by `python3 -m unittest discover -s tests`.
Invariants: builds a throwaway git repo under a TemporaryDirectory.
Never change without a decision: the "diff --git" boundary is what
resets hunk state, not line count or position.
"""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("themis", ROOT / "tools" / "themis.py")
themis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(themis)


def init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)


def commit_all(root: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", message, "--no-verify"], check=True)
    return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                           check=True, capture_output=True, text=True).stdout.strip()


class DiffAdditionsHunkStateTests(unittest.TestCase):
    def test_a_fake_header_line_does_not_corrupt_the_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            (root / "a.py").write_text("x = 1\n", encoding="utf-8")
            base = commit_all(root, "base")
            secret = "sk-" + "1234567890abcdef1234"
            (root / "a.py").write_text('x = 1\n++ fake header line\nAPI_KEY = "%s"\n' % secret, encoding="utf-8")
            head = commit_all(root, "inject a +++ -shaped line, then a real secret")
            additions = themis.diff_additions(root, base + ".." + head)
            self.assertEqual(len(additions), 2)
            self.assertTrue(all(path == "a.py" for path, _, _ in additions))

    def test_a_fake_header_does_not_suppress_a_later_files_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            (root / "a.py").write_text("x = 1\n", encoding="utf-8")
            (root / "b.py").write_text("y = 1\n", encoding="utf-8")
            base = commit_all(root, "base")
            secret = "sk-" + "1234567890abcdef1234"
            (root / "a.py").write_text("x = 1\n++ fake header line\n", encoding="utf-8")
            (root / "b.py").write_text('y = 1\nAPI_KEY = "%s"\n' % secret, encoding="utf-8")
            head = commit_all(root, "fake header in one file, a real secret in the next")
            hits = themis.secret_hits(themis.diff_additions(root, base + ".." + head))
            self.assertTrue(any("b.py" in h for h in hits))
            self.assertNotIn(secret, " ".join(hits))


if __name__ == "__main__":
    unittest.main()
