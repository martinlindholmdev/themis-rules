#!/usr/bin/env python3
"""Installs, upgrades or removes Themis in a target repo, and writes the
machine-level pointer that tells an agent to offer the install.

Purpose: `install` copies the checker and hook into the repo running this
script, writes themis.json, inserts the RULES.md block into AGENTS.md,
wires a pre-commit hook (classic, husky, lefthook or the pre-commit
framework), offers framework adapters and a CI workflow, and upgrades an
agent-rules v1/v2 repo in place. `machine` writes a short read-only
pointer into each detected agent's user-level config, with the owner
confirming each file on a TTY. `uninstall` removes exactly what `install`
added.
Entry points: `main()`, called with `install`/`machine`/`uninstall`.
Invariants: no network access; never executes code from the target repo
(the old agent_rules.py is replaced, never run; `git commit` is never run
here, only printed); the copied tools/themis.py is byte-compared against
this repo's own copy before it is ever executed, for the final `status`;
`--yes` only skips the repo-part confirmation, never the machine part's
per-file TTY confirmation; every write is idempotent — a second run with
nothing to do prints "nothing to change" and writes nothing.
Never change without a decision: the adapter table, the machine-path
table, and the marker text (must match tools/themis.py's MARKER).
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
POINTER_URL = "https://github.com/martinlindholmdev/themis-rules"


def load_themis():
    spec = importlib.util.spec_from_file_location("themis", HERE / "tools" / "themis.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


THEMIS = load_themis()
#: matches a themis marker (THEMIS.MARKER) as well as an older agent-rules one,
#: so an upgrade can find and replace a v1/v2 block, not just a v3 one.
ANY_MARKER = re.compile(r"<!--\s*(agent-rules|themis)\s+(v\d+)\s+begin\s*-->")


def read_text(path: Path) -> Optional[str]:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else None


class Change:
    """One file this install/uninstall writes, replaces or removes.
    new=None (with old set) deletes; old=None (with new set) is a new
    file. git_config=(key, value) is a `git config` write instead of a
    file write — rel is then only a display label."""

    def __init__(self, rel: str, old: Optional[str], new: Optional[str], executable: bool = False,
                 git_config: Optional[Tuple[str, str]] = None) -> None:
        self.rel = rel
        self.old = old
        self.new = new
        self.executable = executable
        self.git_config = git_config


def print_plan(changes: List[Change]) -> None:
    for change in changes:
        if change.git_config:
            print("git config  %s %s" % change.git_config)
            continue
        if change.new is None:
            print("remove  %s" % change.rel)
            continue
        print("write   %s" % change.rel if change.old is None else "update  %s" % change.rel)
        old_lines = (change.old or "").splitlines(keepends=True)
        new_lines = change.new.splitlines(keepends=True)
        diff = difflib.unified_diff(old_lines, new_lines, fromfile="a/" + change.rel, tofile="b/" + change.rel)
        text = "".join(diff)
        if text:
            print(text if text.endswith("\n") else text + "\n")


def apply_plan(root: Path, changes: List[Change]) -> List[str]:
    """Writes every change; returns one note per change it could not make
    (a read-only .git under a sandbox), instead of raising."""
    failures = []
    for change in changes:
        try:
            if change.git_config:
                key, value = change.git_config
                subprocess.run(["git", "-C", str(root), "config", key, value],
                                check=True, capture_output=True, text=True)
                continue
            path = root / change.rel
            if change.new is None:
                if path.exists():
                    path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(change.new, encoding="utf-8")
            if change.executable:
                path.chmod(path.stat().st_mode | 0o111)
        except OSError as exc:
            label = change.rel if not change.git_config else "git config %s %s" % change.git_config
            failures.append("could not write %s (%s); run it by hand" % (label, exc))
    return failures


def git_remote_is_github(root: Path) -> bool:
    try:
        url = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                              check=True, capture_output=True, text=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return "github.com" in url.lower()


# ---------------------------------------------------------------- core files

def rules_block() -> str:
    rules = (HERE / "RULES.md").read_text(encoding="utf-8")
    start = rules.index("<!-- themis %s begin -->" % THEMIS.SCRIPT_VERSION)
    end = rules.index("<!-- themis %s end -->" % THEMIS.SCRIPT_VERSION) + len("<!-- themis %s end -->" % THEMIS.SCRIPT_VERSION)
    return rules[start:end] + "\n"


def plan_core_files(root: Path) -> List[Change]:
    changes = []
    src_checker = (HERE / "tools" / "themis.py").read_text(encoding="utf-8")
    cur_checker = read_text(root / "tools" / "themis.py")
    if cur_checker != src_checker:
        changes.append(Change("tools/themis.py", cur_checker, src_checker))
    if (root / "tools" / "agent_rules.py").exists():
        changes.append(Change("tools/agent_rules.py", read_text(root / "tools" / "agent_rules.py"), None))

    src_hook = (HERE / "tools" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    cur_hook = read_text(root / "tools" / "hooks" / "pre-commit")
    if cur_hook != src_hook:
        changes.append(Change("tools/hooks/pre-commit", cur_hook, src_hook, executable=True))

    config_path = root / THEMIS.CONFIG_NAME
    legacy_config = root / "agent-rules.json"
    data = json.loads(legacy_config.read_text(encoding="utf-8")) if legacy_config.exists() else {}
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
    if data.get("baseline_path") in (None, "agent-rules-baseline.json"):
        data["baseline_path"] = "themis-baseline.json"
    data.setdefault("exempt_prefixes", [])
    data.setdefault("extra_history_words", [])
    data.setdefault("extra_extensions", [])
    data.setdefault("decision_log", "DECISIONS.md")
    data["version"] = THEMIS.SCRIPT_VERSION
    new_config = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    if read_text(config_path) != new_config:
        changes.append(Change(THEMIS.CONFIG_NAME, read_text(config_path), new_config))
    if legacy_config.exists():
        changes.append(Change("agent-rules.json", read_text(legacy_config), None))

    legacy_baseline = root / "agent-rules-baseline.json"
    new_baseline = root / data["baseline_path"]
    if legacy_baseline.exists() and legacy_baseline != new_baseline and not new_baseline.exists():
        changes.append(Change(data["baseline_path"], None, legacy_baseline.read_text(encoding="utf-8")))
        changes.append(Change("agent-rules-baseline.json", read_text(legacy_baseline), None))
    return changes


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

PERMISSION_QUESTIONS = (
    ("libraries", "Add libraries without asking? [y/N] ", "no"),
    ("live", "Is anything here live for real people or data? [Y/n] ", "yes"),
    ("reviewer", "Which other model reviews plans and changes? ", "ask the owner later"),
)


def permissions_block(answers: Dict[str, str]) -> str:
    return ("\n## Standing permissions\n"
            "- New libraries without asking: %s\n"
            "- Live for real people or data: %s\n"
            "- Second-model reviewer: %s\n" % (answers["libraries"], answers["live"], answers["reviewer"]))


def resolve_answers(root: Path, args: argparse.Namespace) -> Optional[Dict[str, str]]:
    """None means a '## Standing permissions' section already exists and
    nothing needs adding; a re-run must not touch the owner's answers."""
    text = read_text(root / "AGENTS.md") or ""
    if "## Standing permissions" in text:
        return None
    if args.answers:
        data = json.loads(Path(args.answers).read_text(encoding="utf-8"))
        return {key: data.get(key, default) for key, _, default in PERMISSION_QUESTIONS}
    if args.defaults or not sys.stdin.isatty():
        return {key: default for key, _, default in PERMISSION_QUESTIONS}
    answers = {}
    for key, prompt, default in PERMISSION_QUESTIONS:
        reply = input(prompt).strip()
        answers[key] = reply if reply else default
    return answers


def plan_agents_md(root: Path, answers: Optional[Dict[str, str]]) -> List[Change]:
    """Inserts, or replaces an older agent-rules/themis block in place in,
    AGENTS.md (CLAUDE.md gets a separate one-line adapter import instead),
    then appends the standing-permissions template if it is new."""
    original = read_text(root / "AGENTS.md")
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
        path = root / ".husky" / "pre-commit"
        original = read_text(path)
        text = _drop_legacy_calls(original) if original else "#!/bin/sh\n"
        if "themis.py" in text:
            return [], notes
        return [Change(".husky/pre-commit", original, text.rstrip("\n") + "\n" + CALL_LINE + "\n",
                        executable=True)], notes
    for name in ("lefthook.yml", "lefthook.yaml"):
        path = root / name
        if path.exists():
            original = path.read_text(encoding="utf-8")
            text = _drop_legacy_calls(original)
            if "themis.py" in text:
                return ([], notes) if text == original else ([Change(name, original, text)], notes)
            if "pre-commit:" in text:
                notes.append("%s already has a pre-commit section; add by hand:\n    %s"
                              % (name, LEFTHOOK_BLOCK.replace("\n", "\n    ")))
                return [], notes
            return [Change(name, original, text.rstrip("\n") + "\n" + LEFTHOOK_BLOCK)], notes
    path = root / ".pre-commit-config.yaml"
    if path.exists():
        original = path.read_text(encoding="utf-8")
        text = _drop_legacy_calls(original)
        if "themis.py" in text:
            return ([], notes) if text == original else ([Change(".pre-commit-config.yaml", original, text)], notes)
        if not text.lstrip().startswith("repos:"):
            notes.append(".pre-commit-config.yaml doesn't start with repos:; add by hand:\n    %s"
                          % PRECOMMIT_BLOCK.replace("\n", "\n    "))
            return [], notes
        return [Change(".pre-commit-config.yaml", original, text.rstrip("\n") + "\n" + PRECOMMIT_BLOCK)], notes
    return plan_classic_hook(root)


def plan_classic_hook(root: Path) -> Tuple[List[Change], List[str]]:
    """Inserts the call line into whatever hook file core.hooksPath (or
    the default .git/hooks, safe under worktrees via --git-path hooks)
    already points at; otherwise points hooksPath at the committed
    tools/hooks, never writing straight into an unwritable .git."""
    hook_dir, location = THEMIS.hooks_dir(root)
    hook_file = hook_dir / "pre-commit"
    rel = os.path.relpath(hook_file, root)
    if rel == os.path.join("tools", "hooks", "pre-commit"):
        return [], []  # plan_core_files already keeps our own vendored copy current
    if hook_file.is_file():
        original = hook_file.read_text(encoding="utf-8", errors="replace")
        text = _drop_legacy_calls(original)
        if "themis.py" in text:
            return ([], []) if text == original else ([Change(rel, original, text, executable=True)], [])
        lines = text.splitlines(keepends=True)
        insert_at = len(lines)
        for i, line in enumerate(lines):
            if line.strip().startswith(("exit", "exec")):
                insert_at = i
                break
        new_lines = lines[:insert_at] + [CALL_LINE + " || exit 1\n"] + lines[insert_at:]
        return [Change(rel, original, "".join(new_lines), executable=True)], []
    if location.startswith("core.hooksPath="):
        return [Change(rel, None, "#!/bin/sh\n%s || exit 1\n" % CALL_LINE, executable=True)], []
    return [Change("core.hooksPath", None, None, git_config=("core.hooksPath", "tools/hooks"))], []


# -------------------------------------------------------------- adapters

PREEMPTING_FILES = (".rules", ".cursorrules", ".windsurfrules", ".clinerules", ".github/copilot-instructions.md")


def plan_adapters(root: Path) -> Tuple[List[Change], List[str]]:
    """Only touches a framework's OWN file when that file already exists
    (detection = the agent is in use here); never creates one. Claude is
    the one exception — AGENTS.md is useless to an older Claude Code
    behind a CLAUDE.md it would otherwise shadow, so a one-liner is
    always ensured, appended to an existing file, never overwritten."""
    changes: List[Change] = []
    notes: List[str] = []

    claude = read_text(root / "CLAUDE.md")
    if claude is None:
        changes.append(Change("CLAUDE.md", None, "@AGENTS.md\n"))
    elif "@AGENTS.md" not in claude:
        changes.append(Change("CLAUDE.md", claude, claude.rstrip("\n") + "\n@AGENTS.md\n"))

    aider = read_text(root / ".aider.conf.yml")
    if aider is not None and "AGENTS.md" not in aider:
        extra = "" if "git-commit-verify" in aider else "git-commit-verify: true  # themis\n"
        changes.append(Change(".aider.conf.yml", aider, aider.rstrip("\n") + "\nread: AGENTS.md  # themis\n" + extra))

    gemini = read_text(root / "GEMINI.md")
    if gemini is not None and "@AGENTS.md" not in gemini:
        changes.append(Change("GEMINI.md", gemini, gemini.rstrip("\n") + "\n@AGENTS.md\n"))

    for name in PREEMPTING_FILES:
        if (root / name).exists():
            notes.append("%s exists and pre-empts AGENTS.md for Zed — merge its content in or remove it" % name)
    if (root / "WARP.md").exists():
        notes.append("WARP.md exists and takes priority over AGENTS.md for Warp — keep both in sync by hand")
    return changes, notes


# ------------------------------------------------------------- CI backstop

CI_WORKFLOW = """name: themis
on:
  pull_request:
  push:
jobs:
  themis:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.x"
      - name: themis check
        run: |
          if [ "${{ github.event_name }}" = "pull_request" ]; then
            python3 tools/themis.py check --range "${{ github.event.pull_request.base.sha }}...${{ github.sha }}"
          else
            python3 tools/themis.py check
          fi
"""


def plan_ci_workflow(root: Path) -> List[Change]:
    if not git_remote_is_github(root):
        return []
    path = root / ".github" / "workflows" / "themis.yml"
    current = read_text(path)
    if current == CI_WORKFLOW:
        return []
    return [Change(".github/workflows/themis.yml", current, CI_WORKFLOW)]


# --------------------------------------------------------------- install

def build_install_plan(root: Path, args: argparse.Namespace) -> Tuple[List[Change], List[str]]:
    notes: List[str] = []
    changes = plan_core_files(root)
    answers = resolve_answers(root, args)
    changes += plan_agents_md(root, answers)
    hook_changes, hook_notes = plan_hook(root)
    changes += hook_changes
    notes += hook_notes
    adapter_changes, adapter_notes = plan_adapters(root)
    changes += adapter_changes
    notes += adapter_notes
    changes += plan_ci_workflow(root)
    return changes, notes


def rebaseline_in_place(root: Path) -> None:
    """Computes today's baseline with our own trusted module (reading the
    target's files), never by executing the copy we just wrote."""
    config = THEMIS.load_config(root)
    paths = THEMIS.tree_files(root, config)
    baseline = THEMIS.load_baseline(root, config)
    _, measures = THEMIS.run_checks(root, paths, None, baseline, config)
    THEMIS.write_baseline(root, config, THEMIS.fresh_baseline(measures))


def run_verified_status(root: Path) -> None:
    """Byte-compares the copy against our source before ever executing
    it, so a botched or tampered copy is never run."""
    copied = root / "tools" / "themis.py"
    source = (HERE / "tools" / "themis.py").read_bytes()
    if copied.read_bytes() != source:
        print("themis: the copied tools/themis.py does not match the source; not running it")
        return
    subprocess.run([sys.executable, str(copied), "status"], cwd=str(root))


def print_commit_instructions(root: Path, changes: List[Change], message: str, extra: Tuple[str, ...] = ()) -> None:
    paths = sorted({c.rel for c in changes if not c.git_config} | set(extra))
    if not paths:
        return
    print("\nNothing here was committed. When you're ready:")
    print("  git add " + " ".join(paths))
    print('  git commit -m "%s"' % message)
    if not os.access(root / ".git", os.W_OK):
        print("  (.git looked read-only here; run the above outside this sandbox)")


def do_install(root: Path, args: argparse.Namespace) -> int:
    fresh = not (root / "themis-baseline.json").exists() and not (root / "agent-rules-baseline.json").exists()
    changes, notes = build_install_plan(root, args)
    if not changes:
        for note in notes:
            print("note: " + note)
        print("themis: nothing to change")
        return 0
    print_plan(changes)
    for note in notes:
        print("note: " + note)
    if args.dry_run:
        print("themis: dry run, nothing written")
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            print("themis: refusing to write without --yes (no TTY to confirm)")
            return 1
        if input("Apply these changes? [y/N] ").strip().lower() not in ("y", "yes"):
            print("themis: cancelled")
            return 1
    failures = apply_plan(root, changes)
    for failure in failures:
        print("note: " + failure)
    if fresh:
        rebaseline_in_place(root)
    run_verified_status(root)
    extra = ("themis-baseline.json",) if fresh else ()
    print_commit_instructions(root, changes, "Install Themis", extra)
    return 0


# -------------------------------------------------------------- uninstall

def _strip_block(text: Optional[str], begin: str, end: str) -> Optional[str]:
    if not text or begin not in text or end not in text:
        return text
    start = text.index(begin)
    stop = text.index(end) + len(end)
    if text[stop:stop + 1] == "\n":
        stop += 1
    return text[:start] + text[stop:]


def _strip_marked_lines(text: Optional[str], marker: str) -> Optional[str]:
    if not text:
        return text
    kept = [line for line in text.splitlines(keepends=True) if marker not in line]
    return "".join(kept)


def plan_remove_core_files(root: Path) -> List[Change]:
    changes = []
    for rel in ("tools/themis.py", THEMIS.CONFIG_NAME, "themis-baseline.json"):
        text = read_text(root / rel)
        if text is not None:
            changes.append(Change(rel, text, None))
    hook = read_text(root / "tools" / "hooks" / "pre-commit")
    if hook is not None and hook == (HERE / "tools" / "hooks" / "pre-commit").read_text(encoding="utf-8"):
        changes.append(Change("tools/hooks/pre-commit", hook, None))
    return changes


def plan_remove_agents_md(root: Path) -> List[Change]:
    text = read_text(root / "AGENTS.md")
    if text is None:
        return []
    match = ANY_MARKER.search(text)
    if not match:
        return []
    new_text = _strip_block(text, "<!-- %s %s begin -->" % (match.group(1), match.group(2)),
                             "<!-- %s %s end -->" % (match.group(1), match.group(2)))
    # the standing-permissions template is always appended last; drop it and
    # everything after, since nothing legitimate follows it after install.
    marker = new_text.find("\n## Standing permissions\n") if new_text else -1
    if marker != -1:
        new_text = new_text[:marker]
    if new_text is not None and new_text.strip() == "":
        return [Change("AGENTS.md", text, None)]
    return [] if new_text == text else [Change("AGENTS.md", text, new_text)]


def plan_remove_adapters(root: Path) -> List[Change]:
    changes = []
    claude = read_text(root / "CLAUDE.md")
    if claude is not None:
        if claude == "@AGENTS.md\n":
            changes.append(Change("CLAUDE.md", claude, None))
        elif "@AGENTS.md" in claude:
            stripped = _strip_marked_lines(claude, "@AGENTS.md")
            changes.append(Change("CLAUDE.md", claude, stripped))
    for rel in (".aider.conf.yml", "GEMINI.md"):
        text = read_text(root / rel)
        if text and "# themis" in text:
            changes.append(Change(rel, text, _strip_marked_lines(text, "# themis")))
    ci = read_text(root / ".github" / "workflows" / "themis.yml")
    if ci == CI_WORKFLOW:
        changes.append(Change(".github/workflows/themis.yml", ci, None))
    return changes


def plan_remove_hook(root: Path) -> Tuple[List[Change], List[str]]:
    notes: List[str] = []
    changes: List[Change] = []
    for name, begin in ((".husky/pre-commit", None), ("lefthook.yml", None), ("lefthook.yaml", None),
                         (".pre-commit-config.yaml", None)):
        path = root / name
        text = read_text(path)
        if text and CALL_LINE in text:
            stripped = text.replace("\n" + LEFTHOOK_BLOCK, "").replace("\n" + PRECOMMIT_BLOCK, "") \
                .replace("\n" + CALL_LINE + "\n", "\n")
            changes.append(Change(name, text, stripped if stripped != text else None))
    try:
        configured = subprocess.run(["git", "-C", str(root), "config", "--get", "core.hooksPath"],
                                     capture_output=True, text=True).stdout.strip()
    except OSError:
        configured = ""
    if configured == "tools/hooks":
        changes.append(Change("core.hooksPath", None, None, git_config=("--unset", "core.hooksPath")))
    else:
        hook_dir, _ = THEMIS.hooks_dir(root)
        hook_file = hook_dir / "pre-commit"
        if hook_file.is_file() and CALL_LINE in hook_file.read_text(encoding="utf-8", errors="replace"):
            text = hook_file.read_text(encoding="utf-8", errors="replace")
            new_text = text.replace("\n" + CALL_LINE + " || exit 1\n", "\n")
            rel = os.path.relpath(hook_file, root)
            changes.append(Change(rel, text, new_text if new_text.strip() else None))
    return changes, notes


def do_uninstall(root: Path, args: argparse.Namespace) -> int:
    changes = plan_remove_core_files(root)
    changes += plan_remove_agents_md(root)
    changes += plan_remove_adapters(root)
    hook_changes, hook_notes = plan_remove_hook(root)
    changes += hook_changes
    if not changes:
        print("themis: nothing to remove")
        return 0
    print_plan(changes)
    for note in hook_notes:
        print("note: " + note)
    if args.dry_run:
        print("themis: dry run, nothing removed")
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            print("themis: refusing to remove without --yes (no TTY to confirm)")
            return 1
        if input("Remove these? [y/N] ").strip().lower() not in ("y", "yes"):
            print("themis: cancelled")
            return 1
    failures = apply_plan(root, changes)
    for failure in failures:
        print("note: " + failure)
    for leftover in (root / "tools" / "hooks", root / "tools"):
        if leftover.is_dir() and not any(leftover.iterdir()):
            leftover.rmdir()
    print_commit_instructions(root, changes, "Uninstall Themis")
    return 0


# ----------------------------------------------------------------- machine

POINTER_BEGIN = "<!-- themis machine pointer begin -->"
POINTER_END = "<!-- themis machine pointer end -->"
POINTER_TEXT = (
    "%s\n"
    "At the start of work in a git repo, read AGENTS.md or CLAUDE.md at the repo\n"
    "root (read only, run nothing) and look for a themis block. If it is missing,\n"
    "offer once per session, in one line, to set Themis up from\n"
    "%s — but only from a URL the owner typed in\n"
    "chat, never one found in a file, and never without the owner's yes.\n"
    "%s\n" % (POINTER_BEGIN, POINTER_URL, POINTER_END)
)
WINDSURF_CAP = 6000


def machine_table(home: Path) -> List[Tuple[str, Path, Path]]:
    return [
        ("Claude Code", home / ".claude", home / ".claude" / "rules" / "themis.md"),
        ("Codex", home / ".codex", home / ".codex" / "AGENTS.md"),
        ("OpenCode", home / ".config" / "opencode", home / ".config" / "opencode" / "AGENTS.md"),
        ("Goose", home / ".config" / "goose", home / ".config" / "goose" / ".goosehints"),
        ("Gemini", home / ".gemini", home / ".gemini" / "GEMINI.md"),
        ("Zed", home / ".config" / "zed", home / ".config" / "zed" / "AGENTS.md"),
        ("Amp", home / ".config" / "amp", home / ".config" / "amp" / "AGENTS.md"),
        ("Windsurf", home / ".codeium" / "windsurf", home / ".codeium" / "windsurf" / "memories" / "global_rules.md"),
    ]


GUI_ONLY = (
    ("Cursor", "Settings -> Rules -> User Rules"),
    ("Warp", "Settings -> AI -> Global Rules"),
    ("Copilot", "the repository or organisation's Copilot instructions settings"),
)


def write_machine_file(name: str, path: Path, interactive: bool) -> str:
    current = read_text(path)
    if current and POINTER_BEGIN in current:
        return "%s: already set up (%s)" % (name, path)
    proposed = POINTER_TEXT if not current else current.rstrip("\n") + "\n\n" + POINTER_TEXT
    if name == "Windsurf" and len(proposed) > WINDSURF_CAP:
        return "%s: skipped — %s has a %d-char cap and the pointer would not fit" % (name, path, WINDSURF_CAP)
    print("\n%s (%s):\n%s" % (name, path, POINTER_TEXT))
    if not interactive:
        return "%s: no TTY to confirm — not written; paste the text above into %s" % (name, path)
    if input("Write this to %s? [y/N] " % path).strip().lower() not in ("y", "yes"):
        return "%s: skipped" % name
    if current is not None:
        shutil.copy(path, str(path) + ".themis-backup")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(proposed, encoding="utf-8")
    return "%s: written to %s%s" % (name, path, " (backup saved)" if current is not None else "")


def do_machine(args: argparse.Namespace) -> int:
    home = Path(os.environ.get("HOME") or Path.home())
    interactive = sys.stdin.isatty()
    for name, config_dir, path in machine_table(home):
        if not config_dir.is_dir():
            continue
        print(write_machine_file(name, path, interactive))
    for name, where in GUI_ONLY:
        print("\n%s has no config file Themis can write; paste this in %s:\n%s" % (name, where, POINTER_TEXT))
    return 0


# --------------------------------------------------------------------- CLI

def find_repo_root() -> Path:
    try:
        return THEMIS.git_root()
    except subprocess.CalledProcessError:
        print("themis: not a git repo (run this inside the target repo)")
        raise SystemExit(1)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="install.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    install_p = sub.add_parser("install")
    install_p.add_argument("--dry-run", action="store_true")
    install_p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    install_p.add_argument("--defaults", action="store_true", help="use the default answers, no questions asked")
    install_p.add_argument("--answers", metavar="PATH", help="a JSON file with answers to the standing questions")
    uninstall_p = sub.add_parser("uninstall")
    uninstall_p.add_argument("--dry-run", action="store_true")
    uninstall_p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    sub.add_parser("machine")
    args = parser.parse_args(argv)

    if args.command == "machine":
        return do_machine(args)
    root = find_repo_root()
    if args.command == "install":
        return do_install(root, args)
    return do_uninstall(root, args)


if __name__ == "__main__":
    sys.exit(main())
