"""Plan-building and primitives for install.py: what to write, replace or
remove in a target repo for install/uninstall/machine, and the mechanics
(path safety, the Change/apply/print machinery, THEMIS) they all share.
Entry points: install.py imports this module and calls build_install_plan,
plan_remove_*, machine_table and write_machine_file — never run directly.
Invariants: same as install.py's — no network access, never executes code
from the target repo, every write goes through safe_path.
Never change without a decision: the adapter table, the machine-path
table, and the marker text (must match tools/themis.py's MARKER); the
gate workflow and the pre-push hook are written once and never overwritten.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Dict, List, Optional, Set, Tuple

HERE = Path(__file__).resolve().parent
POINTER_URL = "https://github.com/martinlindholmdev/themis-rules"

def load_themis():
    spec = importlib.util.spec_from_file_location("themis", HERE / "tools" / "themis.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def _load_sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

THEMIS = load_themis()
GATE = _load_sibling("install_gate")
BadTestSetting = GATE.BadTestSetting
CI_WORKFLOW = GATE.CI_WORKFLOW
GATE_WORKFLOW = GATE.GATE_WORKFLOW
GATE_WORKFLOW_REL = ".github/workflows/themis-gate.yml"
PRE_PUSH_REL = "tools/hooks/pre-push"
#: matches a themis marker (THEMIS.MARKER) as well as an older agent-rules one,
#: so an upgrade can find and replace a v1/v2 block, not just a v3 one.
ANY_MARKER = re.compile(r"<!--\s*(agent-rules|themis)\s+(v\d+(?:\.\d+)*)\s+begin\s*-->")

def read_text(root: Path, rel: str) -> Optional[str]:
    """A tracked file that is itself a symlink — or sits under a
    symlinked directory, anywhere between root and the file — is never
    read: its target may be outside the repo, and its content must never
    be shown in a diff, copied into another file, or treated as this
    repo's own text before (or instead of) a real, validated write."""
    current = root
    for part in Path(rel).parts:
        current = current / part
        if current.is_symlink():
            return None
    return current.read_text(encoding="utf-8", errors="replace") if current.exists() else None

class PathEscapesRepo(ValueError):
    pass

def safe_path(root: Path, rel: str) -> Path:
    """The one check every planned write, delete or chmod goes through:
    no control character (a newline in a path can turn a printed "# this
    failed" comment into a second, unprefixed, executable line if
    pasted), no absolute path, no '..' component, and no symlink
    component at all — leaf or parent — even one that resolves back
    inside the repo: a write through tools/themis.py -> ../README.md
    still lands on README.md, not themis.py, so resolving the final
    location is not enough. Reads nothing, writes nothing; raises
    PathEscapesRepo — and never echoes `rel` itself when it is the
    control character that is the problem, since the exception's own
    message could then just as easily be pasted and run."""
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
    return root / rel

class Change:
    """One file this install/uninstall writes, replaces or removes.
    new=None (with old set) deletes; old=None (with new set) is a new
    file. git_config=(key, value) is a `git config` write instead of a
    file write — rel is then only a display label. trusted=True skips
    the containment re-check in apply_plan for the one legitimate case
    `rel` is allowed to point outside root: the hooks directory git
    itself names for a worktree or submodule (never set from user input)."""

    def __init__(self, rel: str, old: Optional[str], new: Optional[str], executable: bool = False,
                 git_config: Optional[Tuple[str, str]] = None, trusted: bool = False) -> None:
        self.rel = rel
        self.old = old
        self.new = new
        self.executable = executable
        self.git_config = git_config
        self.trusted = trusted

#: files whose content is always byte-identical to this kit's own copy;
#: a new one is proven by hash instead of scrolling ~600 lines of diff
#: past the owner.
TOOL_FILES = tuple("tools/" + name for name in GATE.TOOL_NAMES)
VENDORED_FILES = TOOL_FILES + ("tools/hooks/pre-commit", PRE_PUSH_REL, ".github/workflows/themis.yml",
                               GATE_WORKFLOW_REL)

def _redact_secrets(diff_lines: List[str]) -> List[str]:
    """A diff of a config file an owner already has (.aider.conf.yml, a
    hand-edited hook) can carry a real credential on a line we never
    touched but that still falls inside the default 3-line context —
    never print one, in a diff or anywhere else."""
    out = []
    for line in diff_lines:
        body = line[1:] if line[:1] in ("+", "-") else line
        label = next((label for label, pattern in THEMIS.SECRET_PATTERNS if pattern.search(body)), None)
        out.append(line if label is None else "%s[redacted: looks like %s]\n" % (line[:1], label))
    return out

def print_plan(changes: List[Change]) -> None:
    for change in changes:
        if change.git_config:
            print("git config  " + shlex.join(change.git_config))
            continue
        if change.new is None:
            print("remove  %s" % change.rel)
            continue
        if change.old is None:
            if change.rel in VENDORED_FILES:
                # fixed, byte-identical content: a hash proves it, instead
                # of scrolling a ~600-line diff past the owner.
                lines = change.new.count("\n") or 1
                digest = hashlib.sha256(change.new.encode("utf-8")).hexdigest()
                print("write   %s (%d line%s, identical to Themis %s, sha256 %s)"
                      % (change.rel, lines, "" if lines == 1 else "s", THEMIS.SCRIPT_VERSION, digest))
            else:
                # everything else this install creates (the AGENTS.md
                # block, themis.json, CLAUDE.md, the fresh baseline) is
                # repo-specific and short — shown in full, as promised.
                print("write   %s" % change.rel)
                print(change.new if change.new.endswith("\n") else change.new + "\n")
            continue
        print("update  %s" % change.rel)
        old_lines = change.old.splitlines(keepends=True)
        new_lines = change.new.splitlines(keepends=True)
        diff = difflib.unified_diff(old_lines, new_lines, fromfile="a/" + change.rel, tofile="b/" + change.rel)
        text = "".join(_redact_secrets(list(diff)))
        if text:
            print(text if text.endswith("\n") else text + "\n")

def apply_plan(root: Path, changes: List[Change]) -> Tuple[List[str], Set[str]]:
    """Writes every change; returns one note per change it could not make
    (a read-only .git under a sandbox) instead of raising, plus the set of
    `rel`s that failed — so the commit instructions never tell the owner
    to `git add` something that was never actually written."""
    failures: List[str] = []
    failed_rels: Set[str] = set()
    for change in changes:
        try:
            if change.git_config:
                key, value = change.git_config
                subprocess.run(["git", "-C", str(root), "config", key, value],
                                check=True, capture_output=True, encoding="utf-8", errors="replace")
                continue
            path = (root / change.rel) if change.trusted else safe_path(root, change.rel)
            if change.new is None:
                if path.exists() or path.is_symlink():
                    path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(change.new, encoding="utf-8")
            if change.executable:
                path.chmod(path.stat().st_mode | 0o111)
        except (OSError, PathEscapesRepo) as exc:
            label = change.rel if not change.git_config else "git config %s %s" % change.git_config
            failures.append("could not write %s (%s); run it by hand" % (label, exc))
            if not change.git_config:
                failed_rels.add(change.rel)
    return failures, failed_rels

def git_remote_is_github(root: Path) -> bool:
    try:
        url = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                              check=True, capture_output=True, encoding="utf-8", errors="replace").stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return "github.com" in url.lower()

# ---------------------------------------------------------------- core files

def rules_block() -> str:
    rules = (HERE / "RULES.md").read_text(encoding="utf-8")
    start = rules.index("<!-- themis %s begin -->" % THEMIS.SCRIPT_VERSION)
    end = rules.index("<!-- themis %s end -->" % THEMIS.SCRIPT_VERSION) + len("<!-- themis %s end -->" % THEMIS.SCRIPT_VERSION)
    return rules[start:end] + "\n"

def plan_core_files(root: Path, notes: Optional[List[str]] = None, test: Optional[dict] = None) -> List[Change]:
    changes = []
    notes = [] if notes is None else notes
    for rel in TOOL_FILES:
        source, current = (HERE / rel).read_text(encoding="utf-8"), read_text(root, rel)
        if current != source:
            changes.append(Change(rel, current, source))
    if (root / "tools" / "agent_rules.py").exists():
        changes.append(Change("tools/agent_rules.py", read_text(root, "tools/agent_rules.py"), None))

    src_hook = (HERE / "tools" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    cur_hook = read_text(root, "tools/hooks/pre-commit")
    if cur_hook != src_hook:
        changes.append(Change("tools/hooks/pre-commit", cur_hook, src_hook, executable=True))

    config_path = root / THEMIS.CONFIG_NAME
    legacy_config = root / "agent-rules.json"
    legacy_config_text = read_text(root, "agent-rules.json")
    data = json.loads(legacy_config_text) if legacy_config_text is not None else {}
    config_text = read_text(root, THEMIS.CONFIG_NAME)
    if config_text is not None:
        data = json.loads(config_text)
    if data.get("baseline_path") in (None, "agent-rules-baseline.json"):
        data["baseline_path"] = "themis-baseline.json"
    # validated now, at plan-build time, before anything else in this
    # function is even considered — an unsafe baseline_path must refuse
    # the whole install, not fail partway through applying it with
    # themis.json and AGENTS.md already written.
    safe_path(root, data["baseline_path"])
    data.setdefault("exempt_prefixes", [])
    data.setdefault("header_exempt_prefixes", [])
    data.setdefault("extra_history_words", [])
    data.setdefault("extra_extensions", [])
    data.setdefault("decision_log", "DECISIONS.md")
    if test is not None:
        data["test"] = test
    previous = data.get("version")
    data["version"] = THEMIS.SCRIPT_VERSION
    new_config = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    if config_text != new_config:
        changes.append(Change(THEMIS.CONFIG_NAME, config_text, new_config))
    if legacy_config.exists():
        changes.append(Change("agent-rules.json", legacy_config_text, None))

    legacy_baseline = root / "agent-rules-baseline.json"
    new_baseline = root / data["baseline_path"]
    legacy_baseline_text = read_text(root, "agent-rules-baseline.json")
    current_text = read_text(root, data["baseline_path"])
    if legacy_baseline_text is not None and legacy_baseline != new_baseline and not new_baseline.exists():
        changes.append(Change(data["baseline_path"], None, seeded_baseline(root, data, legacy_baseline_text, notes)))
        changes.append(Change("agent-rules-baseline.json", legacy_baseline_text, None))
    elif not legacy_baseline.exists() and not new_baseline.exists():
        # a brand-new install: shown in the plan like everything else,
        # never a silent write after the owner has already said yes.
        changes.append(Change(data["baseline_path"], None, seeded_baseline(root, data, None, notes)))
    elif current_text is not None and previous != THEMIS.SCRIPT_VERSION:
        seeded = seeded_baseline(root, data, current_text, notes)
        if seeded != current_text:
            changes.append(Change(data["baseline_path"], current_text, seeded))
    return changes

EMPTY_BASELINE = {"files": {}, "functions": {}, "history_words": {}}

def _measures(root: Path, config: dict, ref: Optional[str], seven: bool) -> list:
    """Measures of the tree at `ref` (None: the working tree, untracked
    files included), for the seven-language paths or for all the others."""
    try:
        paths = THEMIS.tree_files(root, config, ref=ref)
    except subprocess.CalledProcessError:
        return []  # no commit yet: nothing is committed to seed from
    paths = [p for p in paths if (Path(p).suffix in THEMIS.lang.EXTENSIONS) == seven]
    return THEMIS.run_checks(root, paths, ref, EMPTY_BASELINE, config)[1]

def _lowered(old: dict, new: dict) -> dict:
    """The entries of `old` that `new` still has, each at the lower number."""
    out: dict = {}
    for key, value in old.items():
        if key in new:
            kept = _lowered(value, new[key]) if isinstance(value, dict) else min(value, new[key])
            if kept != {}:
                out[key] = kept
    return out

def seeded_baseline(root: Path, config: dict, existing: Optional[str], notes: List[str]) -> str:
    """The baseline an install or upgrade writes. The seven-language
    section comes from HEAD's committed content only; the other sections
    come from the working tree, and an existing baseline is only lowered:
    its entries for the seven-language paths are dropped, the rest never
    rise."""
    head = _measures(root, config, "HEAD", True)
    fresh = THEMIS.fresh_baseline(_measures(root, config, None, False) + head)
    result = fresh
    if existing is not None:
        try:
            old = json.loads(existing)
        except json.JSONDecodeError:
            return existing
        result = dict(old)
        for section in ("files", "functions", "history_words"):
            result[section] = _lowered(old.get(section, {}), fresh[section])
        result["lang"] = fresh["lang"]
    seeded = {(m.path, n): s for m in head for n, s in m.functions.items()}
    pending = sorted("%s: %s" % (m.path, n) for m in _measures(root, config, None, True)
                     for n, s in m.functions.items()
                     if s > m.function_limit and seeded.get((m.path, n), 0) < s)
    if pending:
        notes.append("not seeded, because they are not in HEAD's committed content: %s%s; "
                     "commit or split them" % (", ".join(pending[:5]), " ..." if len(pending) > 5 else ""))
    return json.dumps(result, indent=1, ensure_ascii=False) + "\n"

def _replace_block(text: str, family: str, old_version: str, block: str) -> str:
    """Replaces an agent-rules v1/v2 (or an older themis) marked block in
    place, keeping unrelated content before and after it."""
    begin_marker = "<!-- %s %s begin -->" % (family, old_version)
    end_marker = "<!-- %s %s end -->" % (family, old_version)
    start = text.index(begin_marker)
    stop = text.index(end_marker) + len(end_marker)
    if text[stop:stop + 1] == "\n":
        stop += 1
    return text[:start] + block + text[stop:]

# ---------------------------------------------------------- standing permissions

#: (key, prompt, default, is_yes_no) — the fourth field normalises a y/n/yes/no
#: reply instead of storing it raw; the third question is free text.
PERMISSION_QUESTIONS = (
    ("libraries", "Add libraries without asking? [y/N] ", "no", True),
    ("live", "Is anything here live for real people or data? [Y/n] ", "yes", True),
    ("reviewer", "Which other model reviews plans and changes? ", "ask the owner later", False),
)
INTRO = ("Themis checks file/function size, comment style and secrets on every commit.\n"
         "It will write the files below into this repo; nothing is written until you say yes.")

def permissions_block(answers: Dict[str, str]) -> str:
    return ("\n## Standing permissions\n"
            "- New libraries without asking: %s\n"
            "- Live for real people or data: %s\n"
            "- Second-model reviewer: %s\n" % (answers["libraries"], answers["live"], answers["reviewer"]))

class Cancelled(Exception):
    """Raised on Ctrl-D/EOF at a question; caught once, at the top of install."""

def confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        print()
        return False

def _normalise_yes_no(reply, default: str) -> str:
    stripped = str(reply).strip()
    if not stripped:
        return default
    lowered = stripped.lower()
    if lowered in ("y", "yes"):
        return "yes"
    if lowered in ("n", "no"):
        return "no"
    return stripped  # an unrecognised reply is kept verbatim rather than guessed at

def resolve_answers(root: Path, args: argparse.Namespace) -> Optional[Dict[str, str]]:
    """None means a '## Standing permissions' section already exists and
    nothing needs adding; a re-run must not touch the owner's answers."""
    text = read_text(root, "AGENTS.md") or ""
    if "## Standing permissions" in text:
        return None
    if args.answers:
        data = json.loads(Path(args.answers).read_text(encoding="utf-8"))
        answers = {}
        for key, _, default, is_yes_no in PERMISSION_QUESTIONS:
            reply = data.get(key, default)
            answers[key] = _normalise_yes_no(reply, default) if is_yes_no else (str(reply).strip() or default)
        return answers
    if args.defaults or not sys.stdin.isatty():
        return {key: default for key, _, default, _ in PERMISSION_QUESTIONS}
    print("\n" + INTRO)
    answers = {}
    for key, prompt, default, is_yes_no in PERMISSION_QUESTIONS:
        try:
            reply = input(prompt)
        except EOFError:
            print()
            raise Cancelled()
        answers[key] = _normalise_yes_no(reply, default) if is_yes_no else (reply.strip() or default)
    return answers

def plan_agents_md(root: Path, answers: Optional[Dict[str, str]]) -> List[Change]:
    """Inserts, or replaces an older agent-rules/themis block in place in,
    AGENTS.md (CLAUDE.md gets a separate one-line adapter import instead),
    then appends the standing-permissions template if it is new."""
    original = read_text(root, "AGENTS.md")
    text = original
    match = ANY_MARKER.search(text) if text else None
    if match and not (match.group(1) == "themis" and match.group(2) == THEMIS.SCRIPT_VERSION):
        text = _replace_block(text, match.group(1), match.group(2), rules_block())
    elif not match:
        block = rules_block()
        text = (text or "") + ("\n" if text and not text.endswith("\n") else "") + block
    if answers is not None:
        text = (text or "") + permissions_block(answers)
    if text == original:
        return []
    return [Change("AGENTS.md", original, text)]

# ----------------------------------------------------------------- the hook

def _drop_legacy_calls(text: str) -> str:
    """Strips a pre-Themis `agent_rules.py` call line so an upgrade never
    leaves a hook that still runs the file plan_core_files just deleted."""
    kept = [line for line in text.splitlines() if "agent_rules.py" not in line]
    return "\n".join(kept) + ("\n" if text.endswith("\n") else "")

CALL_LINE = "python3 tools/themis.py check --staged"
LEFTHOOK_BLOCK = "pre-commit:\n  commands:\n    themis:\n      run: %s\n" % CALL_LINE
PRECOMMIT_BLOCK = ("-   repo: local\n    hooks:\n    -   id: themis\n        name: themis\n"
                    "        entry: %s\n        language: system\n        pass_filenames: false\n" % CALL_LINE)

def plan_hook(root: Path) -> Tuple[List[Change], List[str]]:
    """Wires the hook the documented way for whichever manager is present,
    or stops with exact instructions rather than editing a generated
    file. Never touches .husky/_, a lefthook/pre-commit-config section it
    cannot parse safely, or anything already calling themis.py."""
    notes: List[str] = []
    if (root / ".husky").is_dir():
        original = read_text(root, ".husky/pre-commit")
        text = _drop_legacy_calls(original) if original else "#!/bin/sh\n"
        if "themis.py" in text:
            return [], notes
        return [Change(".husky/pre-commit", original, text.rstrip("\n") + "\n" + CALL_LINE + "\n",
                        executable=True)], notes
    for name in ("lefthook.yml", "lefthook.yaml"):
        original = read_text(root, name)
        if original is not None:
            text = _drop_legacy_calls(original)
            if "themis.py" in text:
                return ([], notes) if text == original else ([Change(name, original, text)], notes)
            if "pre-commit:" in text:
                notes.append("%s already has a pre-commit section; add by hand:\n    %s"
                              % (name, LEFTHOOK_BLOCK.replace("\n", "\n    ")))
                return [], notes
            return [Change(name, original, text.rstrip("\n") + "\n" + LEFTHOOK_BLOCK)], notes
    original = read_text(root, ".pre-commit-config.yaml")
    if original is not None:
        text = _drop_legacy_calls(original)
        if "themis.py" in text:
            return ([], notes) if text == original else ([Change(".pre-commit-config.yaml", original, text)], notes)
        # appending a list item only extends "repos:" when it is the LAST
        # top-level key — a trailing "ci:" mapping would otherwise swallow
        # our entry and produce invalid YAML.
        if _last_top_level_key(text) != "repos":
            notes.append(".pre-commit-config.yaml: repos: isn't the last top-level key; add by hand:\n    %s"
                          % PRECOMMIT_BLOCK.replace("\n", "\n    "))
            return [], notes
        return [Change(".pre-commit-config.yaml", original, text.rstrip("\n") + "\n" + PRECOMMIT_BLOCK)], notes
    return plan_classic_hook(root)

def _last_top_level_key(text: str) -> Optional[str]:
    keys = re.findall(r"^([A-Za-z_][\w-]*):", text, re.MULTILINE)
    return keys[-1] if keys else None

def plan_classic_hook(root: Path) -> Tuple[List[Change], List[str]]:
    """Inserts the call line into whatever hook file core.hooksPath (or
    the default .git/hooks, safe under worktrees via --git-path hooks)
    already points at; otherwise points hooksPath at the committed
    tools/hooks, never writing straight into an unwritable .git. An
    explicitly configured core.hooksPath outside the repo is refused —
    the *default*, git's own --git-path hooks, is trusted even when it
    legitimately resolves outside root for a worktree."""
    hook_dir, location = THEMIS.hooks_dir(root)
    hook_file = hook_dir / "pre-commit"
    rel = os.path.relpath(hook_file, root)
    configured = location.startswith("core.hooksPath=")
    if configured:
        try:
            safe_path(root, rel)
        except PathEscapesRepo:
            return [], ["%s points outside this repo; set it to a path inside the repo by hand" % location]
    if rel == os.path.join("tools", "hooks", "pre-commit"):
        return [], []  # plan_core_files already keeps our own vendored copy current
    # the default (unconfigured) case is trusted to resolve outside root
    # for a worktree or submodule only because git's own --git-path hooks
    # computed it — restricted here to paths that are actually under a
    # .git directory, never a blanket trust of "whatever git returned".
    trusted = not configured and ".git" in hook_dir.parts
    if hook_file.is_file():
        original = hook_file.read_text(encoding="utf-8", errors="replace")
        text = _drop_legacy_calls(original)
        if "themis.py" in text:
            if text == original:
                return [], []
            return [Change(rel, original, text, executable=True, trusted=trusted)], []
        lines = text.splitlines(keepends=True)
        # right after the shebang: inserting before the first exit/exec
        # line can land inside a conditional, running only sometimes
        # instead of on every commit.
        insert_at = 1 if lines and lines[0].startswith("#!") else 0
        new_lines = lines[:insert_at] + [CALL_LINE + " || exit 1\n"] + lines[insert_at:]
        return [Change(rel, original, "".join(new_lines), executable=True, trusted=trusted)], []
    if configured:
        return [Change(rel, None, "#!/bin/sh\n%s || exit 1\n" % CALL_LINE, executable=True)], []
    return [Change("core.hooksPath", None, None, git_config=("core.hooksPath", "tools/hooks"))], []

# -------------------------------------------------------------- adapters

PREEMPTING_FILES = (".rules", ".cursorrules", ".windsurfrules", ".clinerules", ".github/copilot-instructions.md")

def _merge_aider_read(text: str) -> Optional[str]:
    """Adds AGENTS.md to .aider.conf.yml's existing `read:` key as its own
    new, clearly marked line — never by appending a second `read:` key
    (YAML keeps only the last of two duplicates, silently replacing the
    owner's list) and never onto the same line as the owner's own entries
    (uninstall strips whole lines carrying the themis marker, so sharing
    a line with the owner's values would delete those values too).
    Returns None when the existing value is a flow list (`read: [a, b]`)
    — the only shape with no line of its own to add safely; the caller
    prints the instruction instead of touching the file."""
    match = re.search(r"^read:[ \t]*(.*)$", text, re.MULTILINE)
    if not match:
        return text.rstrip("\n") + "\nread:  # themis\n  - AGENTS.md  # themis\n"
    inline = match.group(1).strip()
    start, end = match.start(), match.end()
    if inline.startswith("[") and inline.endswith("]"):
        return None
    if not inline:
        return text[:end] + "\n  - AGENTS.md  # themis" + text[end:]
    return text[:start] + "read:\n  - %s\n  - AGENTS.md  # themis" % inline + text[end:]

AIDER_FILE = ".aider.conf.yml"
AIDER_NEW = "read: AGENTS.md  # themis\ngit-commit-verify: true  # themis\n"


def aider_in_use(root: Path) -> bool:
    """Aider leaves these behind; its presence means the owner uses it."""
    if any((root / n).exists() for n in (AIDER_FILE, ".aider.chat.history.md", ".aider.input.history")):
        return True
    if any(root.glob(".aider.tags.cache*")):
        return True
    ignore = read_text(root, ".gitignore") or ""
    return any(line.strip().rstrip("/") == ".aider" or line.strip().startswith(".aider")
               for line in ignore.splitlines())


def plan_adapters(root: Path, agents: Tuple[str, ...] = ()) -> Tuple[List[Change], List[str]]:
    """Only touches a framework's OWN file when that file already exists
    (detection = the agent is in use here); never creates one. Claude is
    the one exception — AGENTS.md is useless to an older Claude Code
    behind a CLAUDE.md it would otherwise shadow, so a one-liner is
    always ensured, appended to an existing file, never overwritten."""
    changes: List[Change] = []
    notes: List[str] = []

    claude = read_text(root, "CLAUDE.md")
    if claude is None:
        changes.append(Change("CLAUDE.md", None, "@AGENTS.md\n"))
    elif "@AGENTS.md" not in claude:
        changes.append(Change("CLAUDE.md", claude, claude.rstrip("\n") + "\n@AGENTS.md\n"))

    aider = read_text(root, AIDER_FILE)
    if (root / AIDER_FILE).is_symlink():
        notes.append(".aider.conf.yml is a symlink, so it is left untouched; Aider commits skip git "
                     "hooks unless the file it points to sets git-commit-verify: true")
    elif aider is None and ("aider" in agents or aider_in_use(root)):
        # Aider's auto-commit runs `git commit --no-verify` unless this
        # file says otherwise, so without it the hook never runs there.
        changes.append(Change(AIDER_FILE, None, AIDER_NEW))
    elif aider is not None:
        if re.search(r"^git-commit-verify:\s*false\b", aider, re.MULTILINE | re.IGNORECASE):
            notes.append(".aider.conf.yml sets git-commit-verify: false (your choice, left as is); "
                         "Aider commits will skip the Themis hook")
        if "AGENTS.md" not in aider:
            new_aider = _merge_aider_read(aider)
            if new_aider is None:
                notes.append(".aider.conf.yml's read: is a flow list ([a, b]); add AGENTS.md to it "
                             "by hand — editing that line is not safe to undo cleanly on uninstall")
            else:
                if "git-commit-verify" not in new_aider:
                    new_aider = new_aider.rstrip("\n") + "\ngit-commit-verify: true  # themis\n"
                changes.append(Change(AIDER_FILE, aider, new_aider))

    gemini = read_text(root, "GEMINI.md")
    if gemini is not None and "@AGENTS.md" not in gemini:
        changes.append(Change("GEMINI.md", gemini, gemini.rstrip("\n") + "\n@AGENTS.md\n"))

    for name in PREEMPTING_FILES:
        if (root / name).exists():
            notes.append("%s exists and pre-empts AGENTS.md for Zed — merge its content in or remove it" % name)
    if (root / "WARP.md").exists():
        notes.append("WARP.md exists and takes priority over AGENTS.md for Warp — keep both in sync by hand")
    return changes, notes

# ------------------------------------------------------------- CI backstop

def plan_ci_workflow(root: Path) -> List[Change]:
    if not git_remote_is_github(root):
        return []
    current = read_text(root, ".github/workflows/themis.yml")
    if current == CI_WORKFLOW:
        return []
    return [Change(".github/workflows/themis.yml", current, CI_WORKFLOW)]

def plan_gate_workflow(root: Path, has_test: bool) -> Tuple[List[Change], List[str]]:
    """themis-gate.yml is written once, when a test command is set and a
    GitHub remote exists. An existing file is the owner's, with toolchain
    steps in it: it is never replaced, and a difference from this release's
    template is only printed."""
    if not has_test or not git_remote_is_github(root):
        return [], []
    current = read_text(root, GATE_WORKFLOW_REL)
    if current is None:
        return [Change(GATE_WORKFLOW_REL, None, GATE_WORKFLOW)], []
    if current == GATE_WORKFLOW:
        return [], []
    diff = "".join(_redact_secrets(GATE.workflow_difference(GATE_WORKFLOW_REL, current, GATE_WORKFLOW)
                                   .splitlines(keepends=True)))
    return [], ["%s differs from this release's template and was left as it is (your toolchain steps "
                "live there); the difference:\n%s" % (GATE_WORKFLOW_REL, diff)]

def _hooks_path_is_ours(root: Path, hook_changes: List[Change]) -> bool:
    if any(c.git_config == ("core.hooksPath", "tools/hooks") for c in hook_changes):
        return True
    path, location = THEMIS.hooks_dir(root)
    return location.startswith("core.hooksPath=") and path.resolve() == (root / "tools" / "hooks").resolve()

def plan_pre_push(root: Path, has_test: bool, hook_changes: List[Change]) -> Tuple[List[Change], List[str]]:
    """The pre-push hook that runs the gate, written when a test command is
    set and git is going to read tools/hooks; any other hook setup gets the
    line to add by hand instead of an adapter."""
    if not has_test:
        return [], []
    if not _hooks_path_is_ours(root, hook_changes):
        return [], ["pre-push: git does not read tools/hooks here (a hook manager or an existing hook is in "
                    "charge); add `python3 tools/themis.py gate --reuse` to your pre-push by hand"]
    source = (HERE / PRE_PUSH_REL).read_text(encoding="utf-8")
    current = read_text(root, PRE_PUSH_REL)
    return ([] if current == source else [Change(PRE_PUSH_REL, current, source, executable=True)]), []

def planned_test_section(root: Path, args: argparse.Namespace) -> Optional[dict]:
    """The "test" section the repository will have after this install: the
    existing one untouched, or one built from --test-command. None means no
    gate; the key is never seeded unasked."""
    text = read_text(root, THEMIS.CONFIG_NAME)
    existing = (json.loads(text) if text else {}).get("test")
    command = getattr(args, "test_command", None)
    if not command:
        return existing if isinstance(existing, dict) else None
    return GATE.merged_test(existing, GATE.parse_test_command(command), getattr(args, "test_runner", None),
                            THEMIS.gate)

# --------------------------------------------------------------- install

def build_install_plan(root: Path, args: argparse.Namespace) -> Tuple[List[Change], List[str]]:
    notes: List[str] = []
    previous = THEMIS.installed_version(root) or THEMIS.load_config(root)["version"]
    if previous and previous != THEMIS.SCRIPT_VERSION:
        notes.append("upgrading Themis %s to %s" % (previous, THEMIS.SCRIPT_VERSION))
    test = planned_test_section(root, args)
    changes = plan_core_files(root, notes, test)
    answers = resolve_answers(root, args)
    changes += plan_agents_md(root, answers)
    hook_changes, hook_notes = plan_hook(root)
    changes += hook_changes
    notes += hook_notes
    push_changes, push_notes = plan_pre_push(root, test is not None, hook_changes)
    changes += push_changes
    notes += push_notes
    agents = tuple(a.strip().lower() for a in (getattr(args, "agents", None) or "").split(","))
    adapter_changes, adapter_notes = plan_adapters(root, agents)
    changes += adapter_changes
    notes += adapter_notes
    ci_changes = plan_ci_workflow(root)
    changes += ci_changes
    if any(c.old is not None for c in ci_changes):
        notes.append("replacing .github/workflows/themis.yml: CI now takes all four checker files from the base commit")
    gate_changes, gate_notes = plan_gate_workflow(root, test is not None)
    changes += gate_changes
    notes += gate_notes
    if test is None:
        notes += _test_command_note(root)
    elif any(c.rel == THEMIS.CONFIG_NAME for c in changes):
        notes.append("the test floor starts at 1; after the first green run, `python3 tools/themis.py gate "
                     "--record` raises it to the number of tests that ran")
    notes.append("gitleaks is the complementary secret scanner: Themis's secret check covers common key shapes only")
    if "aider" not in agents and not aider_in_use(root):
        notes.append("If you use Aider, re-run with --agents aider")
    return changes, notes

def _test_command_note(root: Path) -> List[str]:
    suggestion = GATE.suggest_command(os.listdir(root))
    hint = " (from file names only, nothing was run: --test-command \"%s\")" % suggestion if suggestion else ""
    return ["no test command is set, so tests are honour-system here; set one with install --test-command%s" % hint]

def run_verified_status(root: Path) -> None:
    """Byte-compares the copy against our source, then calls the already
    loaded, trusted THEMIS module directly — never a subprocess running
    the copy, which would put the target's own tools/ on sys.path ahead
    of the standard library."""
    for rel in TOOL_FILES:
        copied = root / rel
        if not copied.is_file() or copied.read_bytes() != (HERE / rel).read_bytes():
            print("themis: %s was not written as expected; not running it" % rel)
            return
    THEMIS.print_status(root, THEMIS.load_config(root))

def print_commit_instructions(root: Path, changes: List[Change], message: str,
                               extra: Tuple[str, ...] = (), exclude: Set[str] = frozenset()) -> None:
    """git refuses `git add` on a path under any .git directory — not
    because it is "outside the repo" (a worktree's shared hook file is
    very much part of the repo), but because nothing under .git is
    tracked content at all, worktree or not. That file is named
    separately, with accurate wording, never handed to this repo's
    `git add`. `exclude` drops a change that failed to apply — never tell
    the owner to add something that was never written. Every printed
    command is shlex-quoted, and every comment line is `#`-prefixed on
    its own physical line: a path carrying a newline (control characters
    are refused earlier, by safe_path, but this is the last line of
    defence) must never turn into a second, unprefixed, executable line
    if the whole block is pasted into a shell."""
    all_rel = sorted(({c.rel for c in changes if not c.git_config} | set(extra)) - set(exclude))
    paths, untracked = [], []
    for rel in all_rel:
        if ".git" in Path(rel).parts or Path(rel).is_absolute() or rel.startswith(".."):
            untracked.append(rel)
        else:
            paths.append(rel)
    if not paths and not untracked:
        return
    print("\nNothing here was committed. When you're ready:")
    if paths:
        print("  " + shlex.join(["git", "add", "--"] + paths))
        print("  " + shlex.join(["git", "commit", "-m", message]))
    for rel in untracked:
        note = ("%s is inside a .git directory and isn't tracked by git — nothing to "
                "commit there; repeat this step by hand in every other clone" % rel)
        for line in note.splitlines():
            print("  # " + line)
    if not os.access(root / ".git", os.W_OK):
        print("  (.git looked read-only here; run the above outside this sandbox)")
