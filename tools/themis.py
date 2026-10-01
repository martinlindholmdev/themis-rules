#!/usr/bin/env python3
"""Refuses a change that leaves agent-written code harder to read than
today, or that commits a likely secret.
Purpose: measure recognised source files against the size and
history-comment rules in RULES.md, scan a diff for credential shapes, and
report whether enforcement is actually on.
Entry points: `check` with no flag checks the whole tree; `check --staged`
checks staged files, the staged diff and a baseline that only shrinks
(what the pre-commit hook runs); `check --range A...B` runs the same
whole-tree check at commit B and scans the direct (two-dot) diff A..B for
secrets, comparing the config and baseline against A instead of HEAD (what the CI
backstop runs); `status` reports what is wired up; `rebaseline` rewrites
the baseline (owner only).
Invariants: standard library only, python3 3.9+, no network access;
writes nothing except the baseline file, and only under `rebaseline`;
every repo-specific value comes from `themis.json`, read fresh each run;
"0 files measured" fails loudly; this script's own vendored copy is never
counted; a size or function limit may shrink, never grow; a matched
secret is never printed, only its file, line and shape; git always runs
with quotepath off, so non-ASCII filenames are measured; `--staged`
enforces the config already on HEAD and the baseline already staged (or,
failing that, on HEAD) — never an unstaged edit on disk — so editing
either in the same commit does nothing; `--range A...B` does the same
against A.
Never change without a decision: the two hard limits, the marker text,
the themis.json field names, and the secret pattern list — this script is
vendored byte-for-byte into every repo that installs it.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import subprocess
import sys
import tokenize
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Dict, List, Optional, Tuple

SCRIPT_VERSION = "v3"

FILE_MAX_LINES = 800
FUNCTION_MAX_LINES = 100

CONFIG_NAME = "themis.json"
MARKER = re.compile(r"<!--\s*themis\s+(v\d+)\s+begin\s*-->")

#: this script's own vendored path/name; excluded from every measured set.
SELF_PATH = "tools/themis.py"
SELF_NAME = "themis.py"

#: extension -> (line-comment prefix, block-comment (start, end), "python" if measurable)
_HASH = ("#", None, None)
_SLASH = ("//", ("/*", "*/"), None)
LANGUAGES: Dict[str, Tuple[Optional[str], Optional[Tuple[str, str]], Optional[str]]] = {
    ".py": ("#", None, "python"), ".pyi": ("#", None, "python"),
    **{e: _HASH for e in (".sh", ".bash", ".zsh", ".rb", ".pl", ".yaml", ".yml")},
    **{e: _SLASH for e in (
        ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".kt", ".c", ".h",
        ".cpp", ".cc", ".hpp", ".cs", ".swift", ".rs", ".m", ".mm", ".php")},
    ".lua": ("--", None, None),
    ".sql": ("--", ("/*", "*/"), None),
}

#: words that narrate history instead of present behaviour (extended per repo via extra_history_words)
HISTORY_WORDS = re.compile(
    r"\b\d{4}-\d{2}(-\d{2})?\b|\bused to\b|\bpreviously\b|\breview of\b"
    r"|\breviewer\b|\bthis session\b|DO NOT MERGE",
    re.IGNORECASE,
)
_PRESENT_PASSIVE = re.compile(r"\b(is|are|be|been|being|get|gets)\s+$", re.IGNORECASE)

#: a likely credential in a diff (not extendable from themis.json on purpose)
SECRET_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("a private key block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("an Anthropic-shaped key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}\b")),
    ("an OpenAI-shaped key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("a Stripe key", re.compile(r"\b[sr]k_(live|test)_[A-Za-z0-9]{10,}\b")),
    ("a GitHub token", re.compile(r"\b(ghp|gho|github_pat)_[A-Za-z0-9_]{16,}\b")),
    ("a Slack token", re.compile(r"\bxox[bpas]-[A-Za-z0-9-]{10,}\b")),
    ("an AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("a Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("a bearer token", re.compile(
        r'(?i)Authorization["\']?\s*:\s*["\']?Bearer\s+[A-Za-z0-9._-]{20,}')),
    ("a credential assignment", re.compile(
        r'(?i)\b\w*(?:password|secret|token|api_key)\w*\b["\']?\s*[:=]\s*'
        r'["\']?(?=[^\s"\']*\d)[^\s"\']{16,}')),
]
ALLOW_MARKER = "themis: allow-secret"

#: git always writes UTF-8; decoding with the platform default (cp1252 on
#: a plain Windows console) silently mangles a non-ASCII filename instead
#: of raising, so every git call below decodes as UTF-8 explicitly.
def git_root() -> Path:
    cmd = ["git", "rev-parse", "--show-toplevel"]
    out = subprocess.run(cmd, check=True, capture_output=True, encoding="utf-8", errors="replace").stdout
    return Path(out.strip())

def _git(root: Path, *args: str) -> str:
    cmd = ["git", "-c", "core.quotepath=off", "-C", str(root)] + list(args)
    return subprocess.run(cmd, check=True, capture_output=True, encoding="utf-8", errors="replace").stdout

def _with_defaults(data: dict) -> dict:
    data.setdefault("version", None)
    data.setdefault("baseline_path", "themis-baseline.json")
    data.setdefault("exempt_prefixes", [])
    data.setdefault("extra_history_words", [])
    data.setdefault("extra_extensions", [])
    data.setdefault("decision_log", "the decision log")
    return data

def load_config(root: Path) -> dict:
    path = root / CONFIG_NAME
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return _with_defaults(data)

def load_config_from_rev(root: Path, rev: str) -> Optional[dict]:
    try:
        text = _git(root, "show", "%s:%s" % (rev, CONFIG_NAME))
    except subprocess.CalledProcessError:
        return None
    try:
        return _with_defaults(json.loads(text))
    except json.JSONDecodeError:
        return None

def changed_paths(root: Path, *diff_args: str) -> List[str]:
    return _git(root, "diff", *diff_args, "--name-only", "--diff-filter=ACMR").splitlines()

def enforcement_config(root: Path, config: dict, rev: str, diff_args: Tuple[str, ...]) -> Tuple[dict, bool]:
    """A same-commit/range edit of themis.json must not change what is
    enforced, so enforcement uses the config already committed at `rev`."""
    rev_config = load_config_from_rev(root, rev)
    if rev_config is None:
        return config, False
    return rev_config, CONFIG_NAME in changed_paths(root, *diff_args)

def history_pattern(config: dict) -> "re.Pattern[str]":
    extra = [re.escape(w) for w in config["extra_history_words"]]
    if not extra:
        return HISTORY_WORDS
    return re.compile(HISTORY_WORDS.pattern + "|" + "|".join(extra), re.IGNORECASE)

def is_exempt(path: str, config: dict) -> bool:
    return any(path.startswith(p) for p in config["exempt_prefixes"])
def recognised_extensions(config: dict) -> List[str]:
    return sorted(set(LANGUAGES) | set(config["extra_extensions"]))

def tree_files(root: Path, config: dict, ref: Optional[str] = None) -> List[str]:
    """Recognised source files at `ref` (a commit), or the working tree
    plus untracked files when ref is None."""
    exts = recognised_extensions(config)
    if ref is None:
        listed = _git(root, "ls-files", "-co", "--exclude-standard").splitlines()
        listed = [p for p in listed if (root / p).is_file()]
    else:
        listed = _git(root, "ls-tree", "-r", "--name-only", ref).splitlines()
    return sorted(p for p in set(listed)
                  if Path(p).suffix in exts and not is_exempt(p, config) and p != SELF_PATH)

def staged_files(root: Path, config: dict) -> List[str]:
    exts = recognised_extensions(config)
    listed = _git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines()
    return sorted(p for p in listed
                  if Path(p).suffix in exts and not is_exempt(p, config) and p != SELF_PATH)

def seen_extensions(root: Path, config: dict) -> List[str]:
    """Names why a Vue/Dart-only repo measured nothing, instead of
    reading as quietly clean: extensions present but unrecognised."""
    exts = set(recognised_extensions(config))
    listed = _git(root, "ls-files", "-co", "--exclude-standard").splitlines()
    present = {Path(p).suffix for p in listed if Path(p).suffix and (root / p).is_file()}
    return sorted(e for e in present - exts if e)

def read(root: Path, path: str, ref: Optional[str]) -> str:
    """None reads the working tree; ":" the staged index; else a revision."""
    if ref is None:
        return (root / path).read_text(encoding="utf-8", errors="replace")
    prefix = ":" if ref == ":" else ref + ":"
    return _git(root, "show", prefix + path)

class Measure:
    def __init__(self, path: str) -> None:
        self.path = path
        self.lines = 0
        self.functions: Dict[str, int] = {}
        self.function_gap: Optional[str] = None
        self.history: List[Tuple[int, str]] = []

def _find_unescaped(work: str, token: str) -> int:
    """Like str.find, but a hit right after ':' ('//' in 'https://') isn't one."""
    start = 0
    while True:
        idx = work.find(token, start)
        if idx <= 0 or work[idx - 1] != ":":
            return idx
        start = idx + len(token)

def comments(text: str, style: Tuple[Optional[str], Optional[Tuple[str, str]], object]) -> Dict[int, str]:
    """Line number -> comment text (not string-aware, but good enough to
    catch history words). Python files use python_comments() instead."""
    line_prefix, block, _ = style
    found: Dict[int, str] = {}
    in_block = False
    for number, line in enumerate(text.splitlines(), start=1):
        work = line
        if in_block:
            end = work.find(block[1])
            found[number] = work if end == -1 else work[:end]
            if end == -1:
                continue
            work, in_block = work[end + len(block[1]):], False
        line_idx = _find_unescaped(work, line_prefix) if line_prefix else -1
        block_idx = work.find(block[0]) if block else -1
        if line_idx == -1 and block_idx == -1:
            continue
        if block_idx == -1 or (line_idx != -1 and line_idx < block_idx):
            found[number] = found.get(number, "") + work[line_idx + len(line_prefix):]
            continue
        end = work.find(block[1], block_idx + len(block[0]))
        if end == -1:
            found[number] = found.get(number, "") + work[block_idx + len(block[0]):]
            in_block = True
        else:
            found[number] = found.get(number, "") + work[block_idx + len(block[0]):end]
    return found

def python_comments(text: str) -> Dict[int, str]:
    """Via the tokenizer, so a '#' inside a string is never a false
    comment; falls back to the generic scan if the file does not parse."""
    found: Dict[int, str] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                found[tok.start[0]] = found.get(tok.start[0], "") + tok.string.lstrip("#")
        return found
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return comments(text, LANGUAGES[".py"])

def history_hits(found: Dict[int, str], pattern: "re.Pattern[str]") -> List[Tuple[int, str]]:
    hits = []
    for number in sorted(found):
        line = found[number]
        for match in pattern.finditer(line):
            word = match.group()
            if word.lower() == "used to" and _PRESENT_PASSIVE.search(line[:match.start()]):
                continue
            hits.append((number, word))
            break
    return hits

def python_functions(text: str) -> Tuple[Dict[str, int], Optional[str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return {}, "python3 %d.%d cannot parse it (%s)" % (sys.version_info[0], sys.version_info[1], exc.msg)
    seen: Dict[str, int] = {}
    sizes: Dict[str, int] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                seen[child.name] = seen.get(child.name, 0) + 1
                key = prefix + child.name
                if seen[child.name] > 1:
                    key += "#%d" % seen[child.name]
                sizes[key] = child.end_lineno - child.lineno + 1
                visit(child, key + ".")
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")
            else:
                visit(child, prefix)

    visit(tree, "")
    return sizes, None

def measure_file(path: str, text: str, pattern: "re.Pattern[str]") -> Measure:
    measure = Measure(path)
    measure.lines = len(text.splitlines())
    style = LANGUAGES.get(Path(path).suffix)
    if style is None:
        measure.function_gap = "%s: not measured (unknown extension)" % Path(path).suffix
        return measure
    is_python = style[2] == "python"
    found = python_comments(text) if is_python else comments(text, style)
    measure.history = history_hits(found, pattern)
    if is_python:
        measure.functions, gap = python_functions(text)
        if gap:
            measure.function_gap = "%s: %s" % (path, gap)
    else:
        measure.function_gap = "%s: function length not measured for %s" % (path, Path(path).suffix)
    return measure

class Findings:
    def __init__(self) -> None:
        self.problems: List[str] = []
        self.notes: List[str] = []

class PathEscapesRepo(ValueError):
    pass

def safe_rel_path(root: Path, rel: str) -> Path:
    """Confines an owner/agent-controlled repo-relative path (today: only
    themis.json's baseline_path) to the repo: no control character (a
    newline could turn a printed error into a second, executable line if
    pasted — so this is never echoed back when it is the problem), no
    absolute path, no '..', and no symlink component anywhere, leaf or
    parent — even one that would resolve back inside the repo, since a
    write through it still lands on a different real file than named."""
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in rel):
        raise PathEscapesRepo("a control character is not allowed in a path")
    candidate = Path(rel)
    # rooted under either convention: on Windows "/etc/passwd" has no
    # drive, so Path.is_absolute() is False, yet root / it escapes the repo
    if candidate.is_absolute() or PurePosixPath(rel).is_absolute() or PureWindowsPath(rel).anchor:
        raise PathEscapesRepo("%s: an absolute path is not allowed" % rel)
    if ".." in candidate.parts:
        raise PathEscapesRepo("%s: '..' is not allowed" % rel)
    current = root
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            raise PathEscapesRepo("%s: a symlink component is not allowed" % rel)
    return current

def load_baseline(root: Path, config: dict, ref: Optional[str] = None) -> dict:
    try:
        if ref is None:
            text = safe_rel_path(root, config["baseline_path"]).read_text(encoding="utf-8", errors="replace")
        else:
            text = read(root, config["baseline_path"], ref)
    except (FileNotFoundError, subprocess.CalledProcessError, PathEscapesRepo):
        return {"files": {}, "functions": {}, "history_words": {}}
    return _parsed_baseline(text)

def load_baseline_staged(root: Path, config: dict) -> dict:
    """check --staged must ratchet against what is actually staged (or,
    failing that, committed) — never an unstaged edit on disk, or
    `rebaseline` without `git add` would silently widen the baseline."""
    for ref in (":", "HEAD"):
        try:
            return _parsed_baseline(read(root, config["baseline_path"], ref))
        except subprocess.CalledProcessError:
            continue
    return {"files": {}, "functions": {}, "history_words": {}}

def _parsed_baseline(text: str) -> dict:
    data = json.loads(text)
    data.setdefault("files", {})
    data.setdefault("functions", {})
    data.setdefault("history_words", {})
    return data

def check_file(measure: Measure, baseline: dict, config: dict, found: Findings) -> None:
    path = measure.path
    allowed = max(FILE_MAX_LINES, baseline["files"].get(path, 0))
    if measure.lines > allowed:
        found.problems.append("%s: %d lines, over the %d-line limit. Split it; do not raise the baseline."
                               % (path, measure.lines, FILE_MAX_LINES))
    functions = baseline["functions"].get(path, {})
    for name, size in sorted(measure.functions.items()):
        allowed = max(FUNCTION_MAX_LINES, functions.get(name, 0))
        if size > allowed:
            found.problems.append("%s: function %s is %d lines, over the %d-line limit. Split it; "
                                   "do not raise the baseline." % (path, name, size, FUNCTION_MAX_LINES))
    allowed_history = baseline["history_words"].get(path, 0)
    if len(measure.history) > allowed_history:
        examples = ", ".join("line %d %r" % hit for hit in measure.history[:3])
        found.problems.append("%s: %d comment line(s) read as history (baseline %d), e.g. %s. Say what "
                               "the code does now; move the story to %s."
                               % (path, len(measure.history), allowed_history, examples, config["decision_log"]))
    if measure.function_gap:
        found.notes.append(measure.function_gap)

def run_checks(root: Path, paths: List[str], ref: Optional[str], baseline: dict, config: dict) -> Tuple[Findings, List[Measure]]:
    found = Findings()
    pattern = history_pattern(config)
    measures = [measure_file(p, read(root, p, ref), pattern) for p in paths]
    for measure in measures:
        check_file(measure, baseline, config, found)
    return found, measures

def fresh_baseline(measures: List[Measure]) -> dict:
    files = {m.path: m.lines for m in measures if m.lines > FILE_MAX_LINES}
    functions: Dict[str, Dict[str, int]] = {}
    for m in measures:
        over = {n: s for n, s in m.functions.items() if s > FUNCTION_MAX_LINES}
        if over:
            functions[m.path] = dict(sorted(over.items()))
    history = {m.path: len(m.history) for m in measures if m.history}
    owner_note = "Only this repo's owner changes this file, with a decision-log line naming why."
    return {"_owner": owner_note, "files": dict(sorted(files.items())),
            "functions": dict(sorted(functions.items())), "history_words": dict(sorted(history.items()))}

def write_baseline(root: Path, config: dict, data: dict) -> None:
    path = safe_rel_path(root, config["baseline_path"])
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

def baseline_ratchet_violations(head_text: str, new_text: str) -> List[str]:
    """A number that went up, or an entry that is new, is a violation —
    the baseline only ever goes down. Pure function: no git, easy to test."""
    try:
        head = json.loads(head_text)
    except json.JSONDecodeError:
        head = {}
    try:
        new = json.loads(new_text)
    except json.JSONDecodeError:
        return ["proposed baseline is not valid JSON"]
    problems = []
    for section in ("files", "history_words"):
        old_section = head.get(section, {})
        for path, value in new.get(section, {}).items():
            old = old_section.get(path)
            if old is None:
                problems.append("%s.%s: new entry (%s)" % (section, path, value))
            elif isinstance(value, (int, float)) and value > old:
                problems.append("%s.%s: raised from %s to %s" % (section, path, old, value))
    old_functions = head.get("functions", {})
    for path, funcs in new.get("functions", {}).items():
        old_funcs = old_functions.get(path, {})
        for name, size in funcs.items():
            old_size = old_funcs.get(name)
            if old_size is None:
                problems.append("functions %s/%s: new entry (%s)" % (path, name, size))
            elif size > old_size:
                problems.append("functions %s/%s: raised from %s to %s" % (path, name, old_size, size))
    return problems

def baseline_problems(root: Path, config: dict, rev: str, new_ref: str, diff_args: Tuple[str, ...]) -> List[str]:
    if config["baseline_path"] not in changed_paths(root, *diff_args):
        return []
    new_text = read(root, config["baseline_path"], new_ref)
    try:
        head_text = read(root, config["baseline_path"], rev)
    except subprocess.CalledProcessError:
        return []  # nothing committed yet at rev: this change is creating it
    violations = baseline_ratchet_violations(head_text, new_text)
    if not violations:
        return []
    return ["%s: the baseline only goes down; ask the owner (%s)"
            % (config["baseline_path"], "; ".join(violations))]

def diff_additions(root: Path, *diff_args: str) -> List[Tuple[str, int, str]]:
    """An added line whose own content is "++ something" is rendered by
    git as "+++ something" — identical to a real file-header line — so a
    header is only ever recognised outside a hunk (`in_hunk`, reset by
    the unambiguous "diff --git" boundary git puts before every file);
    inside a hunk, that same text is correctly an addition, not a path."""
    out = _git(root, "diff", *diff_args, "-U0", "--no-color", "--diff-filter=ACMR")
    additions: List[Tuple[str, int, str]] = []
    path: Optional[str] = None
    next_line = 1
    in_hunk = False
    for line in out.splitlines():
        if line.startswith("diff --git "):
            path, in_hunk = None, False
            continue
        if not in_hunk and line.startswith("+++ "):
            header = line[4:]
            path = None if header == "/dev/null" else header[2:]
            continue
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            next_line = int(match.group(1)) if match else 1
            in_hunk = True
            continue
        if in_hunk and line.startswith("+"):
            if path is not None:
                additions.append((path, next_line, line[1:]))
            next_line += 1
    return additions

def secret_hits(additions: List[Tuple[str, int, str]]) -> List[str]:
    """(path, line, text) tuples in; never echoes the matched text."""
    problems = []
    for path, line_no, text in additions:
        if ALLOW_MARKER in text:
            continue
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                problems.append("%s:%d: looks like %s. Remove it, or add `%s` on that line "
                                 "if this is a false positive." % (path, line_no, label, ALLOW_MARKER))
                break
    return problems

def secret_problems(root: Path, *diff_args: str) -> List[str]:
    return secret_hits(diff_additions(root, *diff_args))

def installed_version(root: Path) -> Optional[str]:
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = root / name
        if path.exists():
            match = MARKER.search(path.read_text(encoding="utf-8", errors="replace"))
            if match:
                return match.group(1)
    return None

def hooks_dir(root: Path) -> Tuple[Path, str]:
    """core.hooksPath if set, else --git-path hooks (safe under worktrees
    and submodules, where .git is a file, not a dir)."""
    try:
        configured = _git(root, "config", "--get", "core.hooksPath").strip()
    except subprocess.CalledProcessError:
        configured = ""
    if configured:
        path = Path(configured)
        return (path if path.is_absolute() else root / path), "core.hooksPath=%s" % configured
    git_path = _git(root, "rev-parse", "--git-path", "hooks").strip()
    return root / git_path, "core.hooksPath not set (default %s)" % git_path

def hook_status(root: Path) -> str:
    """Every place a hook manager can hide its real hook, so a husky- or
    lefthook-generated .git/hooks/pre-commit is never mistaken for off —
    but naming themis.py in the manager's own file is not enough: the
    manager must actually be installed in this clone (its shim present
    at the git-resolved hooks path), or no commit ever runs it."""
    managers = (
        ("husky (.husky/pre-commit)", root / ".husky" / "pre-commit", "npx husky"),
        ("lefthook (lefthook.yml)", root / "lefthook.yml", "lefthook install"),
        ("lefthook (lefthook.yaml)", root / "lefthook.yaml", "lefthook install"),
        ("pre-commit framework (.pre-commit-config.yaml)", root / ".pre-commit-config.yaml", "pre-commit install"),
    )
    hooks_path, location = hooks_dir(root)
    hook_path = hooks_path / "pre-commit"
    installed = hook_path.is_file()
    for label, path, install_cmd in managers:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if SELF_NAME not in text:
            return "%s found but does not call %s — off" % (label, SELF_NAME)
        if not installed:
            return "%s calls %s, but it is not installed in this clone (run `%s`) — off" % (label, SELF_NAME, install_cmd)
        return "%s — on" % label
    if not installed:
        return "%s; no pre-commit file there — the hook will not run" % location
    text = hook_path.read_text(encoding="utf-8", errors="replace")
    if SELF_NAME in text:
        return "%s; pre-commit calls %s — on" % (location, SELF_NAME)
    return "%s; a pre-commit file is there but does not call %s — off, foreign hook kept" % (location, SELF_NAME)

def print_status(root: Path, config: dict) -> int:
    paths = tree_files(root, config)
    baseline = load_baseline(root, config)
    found, measures = run_checks(root, paths, None, baseline, config)
    unmeasured = sorted({Path(n.path).suffix for n in measures if n.function_gap})
    unseen = seen_extensions(root, config)
    print("themis status")
    print("  installed in this repo (AGENTS.md/CLAUDE.md marker): %s" % (installed_version(root) or "not found"))
    print("  script version: %s" % SCRIPT_VERSION)
    print("  repo config (themis.json) version: %s" % (config["version"] or "unknown"))
    if config["version"] and config["version"] != SCRIPT_VERSION:
        print("  versions differ: themis.json says %s, this script is %s — re-run the install"
              % (config["version"], SCRIPT_VERSION))
    print("  hook: %s" % hook_status(root))
    print("  python: %d.%d" % (sys.version_info[0], sys.version_info[1]))
    print("  files measured: %d" % len(paths))
    print("  extensions not function-measured: %s" % (", ".join(unmeasured) if unmeasured else "none seen"))
    print("  extensions seen but not measured at all: %s" % (", ".join(unseen) if unseen else "none"))
    if not paths:
        print("themis: FAIL, 0 files measured — check themis.json's extra_extensions "
              "and exempt_prefixes, or confirm this repo really has no recognised source files")
        return 1
    if found.problems:
        for problem in found.problems:
            print("  " + problem)
        print("themis: FAIL, %d problem(s)" % len(found.problems))
        return 1
    print("themis: clean")
    return 0

def _report(notes: List[str], blocking: List[str], ok_message: str) -> int:
    for note in notes:
        print("note: " + note)
    for problem in blocking:
        print(problem)
    if blocking:
        print("themis: FAIL, %d problem(s)" % len(blocking))
        return 1
    print(ok_message)
    return 0

def run_tree(root: Path, config: dict) -> int:
    paths = tree_files(root, config)
    if not paths:
        print("themis: FAIL, 0 files measured — check themis.json's "
              "extra_extensions and exempt_prefixes")
        return 1
    baseline = load_baseline(root, config)
    found, _ = run_checks(root, paths, None, baseline, config)
    return _report(found.notes, found.problems, "themis: pass, %d file(s) checked" % len(paths))

def _self_change_note(root: Path, diff_args: Tuple[str, ...]) -> List[str]:
    if SELF_PATH in changed_paths(root, *diff_args):
        return ["%s changed; owner only — a PR's own copy is never what CI "
                 "checks it with, but review this by hand too" % SELF_PATH]
    return []

def run_staged(root: Path, config: dict) -> int:
    config, config_changed = enforcement_config(root, config, "HEAD", ("--cached",))
    notes: List[str] = list(_self_change_note(root, ("--cached",)))
    if config_changed:
        notes.append("%s changed; owner only — this commit is still checked "
                      "against the version already on HEAD" % CONFIG_NAME)
    blocking = secret_problems(root, "--cached") + baseline_problems(root, config, "HEAD", ":", ("--cached",))
    paths = staged_files(root, config)
    if paths:
        baseline = load_baseline_staged(root, config)
        found, _ = run_checks(root, paths, ":", baseline, config)
        notes += found.notes
        blocking += found.problems
    elif not blocking:
        print("themis: 0 staged source files; nothing to check")
        return 0
    return _report(notes, blocking, "themis: pass, %d file(s) checked" % len(paths))

def run_range(root: Path, config: dict, range_arg: str) -> int:
    if "..." not in range_arg:
        print("themis: --range needs the form A...B (e.g. origin/main...HEAD)")
        return 2
    a, b = range_arg.split("...", 1)
    # a direct two-dot diff, not three-dot/merge-base: A is sometimes a
    # raw tree (CI's empty-tree fallback for a branch with no earlier
    # commit), and merge-base requires two commits.
    span = a + ".." + b
    config, config_changed = enforcement_config(root, config, a, (span,))
    notes: List[str] = list(_self_change_note(root, (span,)))
    if config_changed:
        notes.append("%s changed between %s and %s; owner only — this range is "
                      "still checked against the version at %s" % (CONFIG_NAME, a, b, a))
    blocking = secret_problems(root, span) + baseline_problems(root, config, a, b, (span,))
    paths = tree_files(root, config, ref=b)
    if not paths:
        print("themis: FAIL, 0 files measured at %s" % b)
        return 1
    baseline = load_baseline(root, config, ref=b)
    found, _ = run_checks(root, paths, b, baseline, config)
    notes += found.notes
    blocking += found.problems
    return _report(notes, blocking, "themis: pass, %d file(s) checked at %s" % (len(paths), b))

def main(argv: Optional[List[str]] = None) -> int:
    # a path this process cannot even print (an unmappable console code
    # page) must not crash the hook outright — replace, don't raise.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="themis.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check", help="check the whole tree, staged files, or a commit range")
    group = p_check.add_mutually_exclusive_group()
    group.add_argument("--staged", action="store_true", help="check staged files, diff and baseline")
    group.add_argument("--range", metavar="A...B", help="check the tree at B; scan the two-dot diff A..B for secrets")
    sub.add_parser("status", help="report what is installed and wired up")
    sub.add_parser("rebaseline", help="owner only: rewrite the baseline from today's tree")
    args = parser.parse_args(argv)
    root = git_root()
    config = load_config(root)
    if args.command == "status":
        return print_status(root, config)
    if args.command == "rebaseline":
        print("themis: rebaseline is for this repo's owner only; it rewrites "
              "the baseline to today's sizes and never raises a number on its own.")
        paths = tree_files(root, config)
        baseline = load_baseline(root, config)
        _, measures = run_checks(root, paths, None, baseline, config)
        try:
            write_baseline(root, config, fresh_baseline(measures))
        except PathEscapesRepo as exc:
            print("themis: refusing to write the baseline — %s" % exc)
            return 1
        print("themis: baseline written to %s" % config["baseline_path"])
        return 0
    if args.range:
        return run_range(root, config, args.range)
    if args.staged:
        return run_staged(root, config)
    return run_tree(root, config)

if __name__ == "__main__":
    sys.exit(main())
