#!/usr/bin/env python3
"""Refuses a change that leaves agent-written code harder to read than
today, or that commits a likely secret.
Purpose: measure recognised source files against the size and
history-comment rules in RULES.md, require rule 2's header on new files,
scan a diff for credential shapes, and report whether enforcement is on.
Entry points: `check` with no flag checks the whole tree; `check --staged`
checks staged files, the staged diff and a baseline that only shrinks
(what the pre-commit hook runs); `check --range A...B` checks the tree at
commit B and scans the two-dot diff A..B for secrets, against the config
and baseline at A (what the CI backstop runs); `status` reports what is
wired up; `rebaseline` lowers the baseline to today's sizes and refuses,
writing nothing, if that would raise a number or add an entry; `gate` runs
the project's own tests as an acceptance gate (see themis_gate.py).
Invariants: standard library only, python3 3.9+, no network access;
writes nothing except the baseline file, and only under `rebaseline`;
every repo-specific value comes from `themis.json`, read fresh each run;
"0 files measured" fails loudly; this script and its three siblings are never
counted; a size or function limit may shrink, never grow; a matched
secret is never printed, only its file, line and shape; git always runs
with quotepath off, so non-ASCII filenames are measured; `--staged`
enforces the config already on HEAD and the baseline already staged (or,
failing that, on HEAD), never an unstaged edit on disk, so editing either
in the same commit does nothing; `--range` does the same against A; the
header check reads only files added relative to that base, under its
config, and is skipped with a note when the base has no themis.json.
Never change without a decision: the two hard limits, the marker text,
the themis.json field names, and the secret pattern list — the four tools
files are vendored byte-for-byte; themis_lang.py, themis_scan.py and
themis_gate.py must sit beside this file or the run ends at once with one line.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import importlib.util
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Dict, List, Optional, Tuple

SCRIPT_VERSION = "v3.4"

FILE_MAX_LINES = 800
FUNCTION_MAX_LINES = 100

CONFIG_NAME = "themis.json"
MARKER = re.compile(r"<!--\s*themis\s+(v\d+(?:\.\d+)*)\s+begin\s*-->")

#: the vendored tools files; excluded from every measured set.
SELF_PATHS = ("tools/themis.py", "tools/themis_lang.py", "tools/themis_scan.py", "tools/themis_gate.py")


def _load_sibling(name: str):
    """Loads a file beside this one by path, never through sys.path, and
    never leaves bytecode in the repo being checked."""
    sys.dont_write_bytecode = True
    path = Path(__file__).resolve().parent / (name + ".py")
    if not path.is_file():
        raise ImportError("tools/%s.py is missing beside themis.py; restore it or reinstall Themis" % name)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    lang = _load_sibling("themis_lang")
    gate = _load_sibling("themis_gate")
except ImportError as exc:
    print("themis: cannot run: %s" % exc)
    sys.exit(1)
history_hits = lang.history_hits
hooks_dir = gate.hooks_dir
hook_status = gate.hook_status
_git = gate.git

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

def _with_defaults(data: dict) -> dict:
    data.setdefault("version", None)
    data.setdefault("baseline_path", "themis-baseline.json")
    data.setdefault("exempt_prefixes", [])
    data.setdefault("header_exempt_prefixes", [])
    data.setdefault("extra_history_words", [])
    data.setdefault("extra_extensions", [])
    data.setdefault("decision_log", "the decision log")
    for key in ("limits", "exempt_files"):
        if not isinstance(data.setdefault(key, {}), dict):
            data[key] = {}
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
    return path in config.get("exempt_files", ()) or any(path.startswith(p) for p in config["exempt_prefixes"])

def recognised_extensions(config: dict) -> List[str]:
    return sorted(set(LANGUAGES) | set(lang.EXTENSIONS) | set(config["extra_extensions"]))

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
                  if Path(p).suffix in exts and not is_exempt(p, config) and p not in SELF_PATHS)

def staged_files(root: Path, config: dict) -> List[str]:
    exts = recognised_extensions(config)
    listed = _git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines()
    return sorted(p for p in listed
                  if Path(p).suffix in exts and not is_exempt(p, config) and p not in SELF_PATHS)

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
        self.notes: List[str] = []
        self.history: List[Tuple[int, str]] = []
        self.test_spans: List[Tuple[int, int]] = []
        self.file_limit, self.function_limit = FILE_MAX_LINES, FUNCTION_MAX_LINES

    @property
    def test_lines(self) -> int:
        return sum(b - a + 1 for a, b in self.test_spans)

    @property
    def counted(self) -> int:
        """Lines counted against the file limit: a Rust test module's lines are not."""
        return self.lines - self.test_lines

    @property
    def is_lang(self) -> bool:
        return Path(self.path).suffix in lang.EXTENSIONS

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

def measure_file(path: str, text: str, pattern: "re.Pattern[str]", limits: Optional[dict] = None) -> Measure:
    measure = Measure(path)
    measure.lines = len(text.splitlines())
    ext = Path(path).suffix
    measure.file_limit, measure.function_limit = lang.clamp_limits(limits, ext, FILE_MAX_LINES, FUNCTION_MAX_LINES)
    style = LANGUAGES.get(ext)
    if measure.is_lang:
        measure.functions, notes, measure.test_spans, found = lang.analyse(text, ext, measure.function_limit)
        measure.notes = ["%s: %s" % (path, n) for n in notes]
    elif style is None:
        measure.function_gap = "%s: not measured (unknown extension)" % ext
        return measure
    else:
        is_python = style[2] == "python"
        found = lang.python_comments(text) if is_python else lang.legacy_comments(text, style)
        if is_python:
            measure.functions, gap = python_functions(text)
            if gap:
                measure.function_gap = "%s: %s" % (path, gap)
        else:
            measure.function_gap = "%s: function length not measured for %s" % (path, ext)
    measure.history = history_hits(found, pattern)
    return measure

class Findings:
    def __init__(self) -> None:
        self.problems: List[str] = []
        self.notes: List[str] = []
        self.generated: List[str] = []

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
    section = data.setdefault("lang", {})
    section.setdefault("functions", {})
    section.setdefault("history_words", {})
    return data

def check_file(measure: Measure, baseline: dict, config: dict, found: Findings) -> None:
    path = measure.path
    old = baseline.get("lang", {}) if measure.is_lang else baseline
    allowed = max(measure.file_limit, baseline["files"].get(path, 0))
    if measure.counted > allowed:
        size = "%d lines" % measure.lines
        if measure.test_lines:
            size += " (%d production + %d test)" % (measure.counted, measure.test_lines)
        found.problems.append("%s: %s, over the %d-line limit. Split it; do not raise the baseline."
                               % (path, size, measure.file_limit))
    for first, last in measure.test_spans:
        if last - first + 1 > measure.file_limit:
            found.problems.append("%s: the test module at lines %d-%d is %d lines, over the %d-line limit. "
                                   "Split it." % (path, first, last, last - first + 1, measure.file_limit))
    functions = old.get("functions", {}).get(path, {})
    for name, size in sorted(measure.functions.items()):
        allowed = max(measure.function_limit, functions.get(name, 0))
        if size > allowed:
            found.problems.append("%s: function %s is %d lines, over the %d-line limit. Split it; "
                                   "do not raise the baseline." % (path, name, size, measure.function_limit))
    allowed_history = old.get("history_words", {}).get(path, 0)
    if len(measure.history) > allowed_history:
        examples = ", ".join("line %d %r" % hit for hit in measure.history[:3])
        found.problems.append("%s: %d comment line(s) read as history (baseline %d), e.g. %s. Say what "
                               "the code does now; move the story to %s."
                               % (path, len(measure.history), allowed_history, examples, config["decision_log"]))
    found.notes += measure.notes
    if measure.function_gap:
        found.notes.append(measure.function_gap)

def _generated_skip(root: Path, path: str, text: str, base_ref: str, found: Findings) -> bool:
    """A generated-file marker exempts a file only if its version at the
    base commit carried one; the secret scan never looks at this."""
    if lang.generated(text) is None:
        return False
    try:
        base_text: Optional[str] = read(root, path, base_ref)
    except subprocess.CalledProcessError:
        base_text = None
    marker, honoured = lang.generated_honoured(text, base_text)
    if marker is not None:
        found.generated += [path] if honoured else []
        found.notes.append("%s: %s" % (path, "treated as generated (%s)" % marker if honoured
                                       else "generated marker not honoured: new in this change"))
    return honoured

def header_style(path: str):
    """The comment syntax a header is read in; None for YAML and for a
    file with no comment syntax."""
    ext = Path(path).suffix
    return None if ext in (".yaml", ".yml") else LANGUAGES.get(ext) or (_SLASH if ext in lang.EXTENSIONS else None)

def header_report(root: Path, rev: str, diff_args: Tuple[str, ...], ref: Optional[str],
                  untracked: bool = False) -> Tuple[List[str], List[str]]:
    """(notes, problems) for rule 2 on the files added relative to `rev`
    (a rename is not an addition), under the config committed at `rev`, so
    a same-change edit of it does nothing. `untracked` adds the working
    tree's untracked files (plain `check`)."""
    base = load_config_from_rev(root, rev)
    if base is None:
        return ["header check skipped: no %s at %s" % (CONFIG_NAME, rev)], []
    added = _git(root, "diff", *diff_args, "-M", "--name-only", "--diff-filter=A").splitlines()
    if untracked:
        added += _git(root, "ls-files", "-o", "--exclude-standard").splitlines()
    problems = []
    for path in sorted(set(added)):
        style = header_style(path)
        if (style is None or is_exempt(path, base) or path in SELF_PATHS
                or any(path.startswith(p) for p in base["header_exempt_prefixes"])
                or (ref is None and not (root / path).is_file())):
            continue
        why = lang.header_problem(read(root, path, ref), Path(path).suffix, style)
        if why:
            problems.append("%s: new file has no valid header (%s). Open it with a comment or docstring of at "
                            "most %d lines whose lines start with %s, each followed by a colon and real text; "
                            "see rule 2." % (path, why, lang.HEADER_MAX_LINES, ", ".join(lang.HEADER_LABELS)))
    return [], problems

def run_checks(root: Path, paths: List[str], ref: Optional[str], baseline: dict, config: dict,
               base_ref: str = "HEAD") -> Tuple[Findings, List[Measure]]:
    found = Findings()
    pattern = history_pattern(config)
    measures = []
    for path in paths:
        text = read(root, path, ref)
        if _generated_skip(root, path, text, base_ref, found):
            continue
        measures.append(measure_file(path, text, pattern, config.get("limits")))
        check_file(measures[-1], baseline, config, found)
    return found, measures

def fresh_baseline(measures: List[Measure]) -> dict:
    files = {m.path: m.counted for m in measures if m.counted > m.file_limit}
    tables: Dict[bool, Dict[str, Dict[str, int]]] = {False: {}, True: {}}
    history: Dict[bool, Dict[str, int]] = {False: {}, True: {}}
    for m in measures:
        over = {n: s for n, s in m.functions.items() if s > m.function_limit}
        if over:
            tables[m.is_lang][m.path] = dict(sorted(over.items()))
        if m.history:
            history[m.is_lang][m.path] = len(m.history)
    owner_note = "Only this repo's owner changes this file, with a decision-log line naming why."
    return {"_owner": owner_note, "files": dict(sorted(files.items())),
            "functions": dict(sorted(tables[False].items())), "history_words": dict(sorted(history[False].items())),
            "lang": {"functions": dict(sorted(tables[True].items())),
                     "history_words": dict(sorted(history[True].items()))}}

def _committed_baseline_text(root: Path, config: dict) -> Optional[str]:
    """The baseline as committed (HEAD), else the one on disk, else None:
    what rebaseline must never raise a number above."""
    try:
        return read(root, config["baseline_path"], "HEAD")
    except subprocess.CalledProcessError:
        pass
    try:
        return safe_rel_path(root, config["baseline_path"]).read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, PathEscapesRepo):
        return None

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

def lang_problems(root: Path, config: dict, rev: str, head_text: str, new_text: str) -> List[str]:
    """New or raised `lang` entries must be backed by the base commit's own
    version of the file, measured with the code running now."""
    pattern = history_pattern(config)

    def base_measure(path: str):
        try:
            return lang.measure_text(read(root, path, rev), Path(path).suffix, pattern)
        except subprocess.CalledProcessError:
            return None
    return lang.lang_violations(head_text, new_text, base_measure)

def baseline_problems(root: Path, config: dict, rev: str, new_ref: str, diff_args: Tuple[str, ...]) -> List[str]:
    if config["baseline_path"] not in changed_paths(root, *diff_args):
        return []
    new_text = read(root, config["baseline_path"], new_ref)
    try:
        head_text = read(root, config["baseline_path"], rev)
        violations = baseline_ratchet_violations(head_text, new_text)
    except subprocess.CalledProcessError:
        head_text, violations = "{}", []  # nothing committed at rev: this change creates it
    violations += lang_problems(root, config, rev, head_text, new_text)
    if not violations:
        return []
    return ["%s: the baseline only goes down; split the file instead (%s)"
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
    for line in gate.status_lines(root, config.get("test")):
        print("  " + line)
    print("  python: %d.%d" % (sys.version_info[0], sys.version_info[1]))
    print("  files measured: %d" % len(paths))
    print("  extensions not function-measured: %s" % (", ".join(unmeasured) if unmeasured else "none seen"))
    print("  extensions seen but not measured at all: %s" % (", ".join(unseen) if unseen else "none"))
    print("  generated files treated as such: %s" % (", ".join(found.generated) or "none"))
    for path, reason in sorted(config.get("exempt_files", {}).items()):
        print("  exempt file (size, function and history checks only): %s: %s" % (path, reason))
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
    notes, headers = header_report(root, "HEAD", ("HEAD",), None, untracked=True)
    return _report(found.notes + notes, found.problems + headers, "themis: pass, %d file(s) checked" % len(paths))

def _self_change_note(root: Path, diff_args: Tuple[str, ...]) -> List[str]:
    changed = changed_paths(root, *diff_args)
    return ["%s changed; owner only — a PR's own copy is never what CI "
            "checks it with, but review this by hand too" % p for p in SELF_PATHS if p in changed]

def run_staged(root: Path, config: dict) -> int:
    config, config_changed = enforcement_config(root, config, "HEAD", ("--cached",))
    notes: List[str] = list(_self_change_note(root, ("--cached",)))
    if config_changed:
        notes.append("%s changed; owner only — this commit is still checked "
                      "against the version already on HEAD" % CONFIG_NAME)
    blocking = secret_problems(root, "--cached") + baseline_problems(root, config, "HEAD", ":", ("--cached",))
    header_notes, headers = header_report(root, "HEAD", ("--cached",), ":")
    blocking += headers
    paths = staged_files(root, config)
    if paths:
        baseline = load_baseline_staged(root, config)
        found, _ = run_checks(root, paths, ":", baseline, config, "HEAD")
        notes += found.notes + header_notes
        blocking += found.problems
    elif not blocking:
        for note in header_notes:
            print("note: " + note)
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
    found, _ = run_checks(root, paths, b, baseline, config, a)
    header_notes, headers = header_report(root, a, (span,), b)
    notes += found.notes + header_notes
    blocking += found.problems + headers
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
    sub.add_parser("rebaseline", help="lower the baseline to today's sizes; never raises a number")
    gate.add_arguments(sub.add_parser("gate", help="run the project's tests and enforce the acceptance floor"))
    args = parser.parse_args(argv)
    root = git_root()
    config = load_config(root)
    if args.command == "status":
        return print_status(root, config)
    if args.command == "gate":
        return gate.run(root, args, safe_rel_path)
    if args.command == "rebaseline":
        print("themis: rebaseline only lowers the baseline: it drops entries for files that shrank "
              "under a limit or were deleted, and refuses to raise any number.")
        paths = tree_files(root, config)
        baseline = load_baseline(root, config)
        _, measures = run_checks(root, paths, None, baseline, config)
        fresh = fresh_baseline(measures)
        committed = _committed_baseline_text(root, config)
        if committed is not None:
            raised = baseline_ratchet_violations(committed, json.dumps(fresh))
            raised += lang_problems(root, config, "HEAD", committed, json.dumps(fresh))
            if raised:
                print("themis: refusing — rebaseline would raise the baseline, which only goes down. "
                      "Split the file instead:")
                for line in raised:
                    print("  " + line)
                return 1
        try:
            write_baseline(root, config, fresh)
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
