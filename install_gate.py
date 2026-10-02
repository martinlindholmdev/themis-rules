"""The two CI workflow templates and the pure helpers for the test command.

Purpose: hold the text of .github/workflows/themis.yml and themis-gate.yml,
the list of vendored checker files, and the functions that turn an
`install --test-command` into a valid themis.json "test" section, suggest a
command from file names, and describe how a workflow differs from its template.
Entry points: install_plan.py imports TOOL_NAMES, CI_WORKFLOW, GATE_WORKFLOW,
parse_test_command(), merged_test(), suggest_command(),
agent_finish_snippets() and workflow_difference(); never run directly.
Invariants: standard library only; no network access; nothing here reads or
runs the target repository, it works on values handed in (file names, the
existing "test" section); the command is stored as an argv list and a shell
operator in it is refused, so nothing the owner types is ever run through a
shell; both workflows resolve the checker from the base commit and share one
resolving script, which takes a merge queue entry's base and head from the
merge_group event and fails when the base is missing.
Never change without a decision: the file names in TOOL_NAMES, the workflow
names and job names (an owner's required status check names a job), and the
rule that themis-gate.yml is written once and never overwritten.
"""

from __future__ import annotations

import difflib
import json
import shlex
from pathlib import Path
from typing import List, Optional

TOOL_NAMES = ("themis.py", "themis_lang.py", "themis_scan.py", "themis_gate.py")
RUNNERS = ("unittest", "pytest", "cargo")
SHELL_WORDS = ("&&", "||", ";", "|", "&", ">", ">>", "<", "2>&1")


class BadTestSetting(ValueError):
    """The test command or runner an install was given cannot be used."""


_CHECKOUT = """      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97  # v7.0.0
        with:
          python-version: "3.x"
"""

#: shell that sets BASE and HEAD and puts the BASE commit's own copy of the
#: checker files in $RUNNER_TEMP/themis_base; shared by both workflows.
_RESOLVE_BASE = """          ZERO="0000000000000000000000000000000000000000"
          EMPTY_TREE="4b825dc642cb6eb9a060e54bf8d69288fbee4904"
          HEAD="${{ github.sha }}"
          if [ "${{ github.event_name }}" = "pull_request" ]; then
            BASE="${{ github.event.pull_request.base.sha }}"
          elif [ "${{ github.event_name }}" = "merge_group" ]; then
            # a merge queue entry: the queue's base commit decides, with
            # its own checker and config; with no base SHA the job fails
            # rather than judging the entry against the empty tree.
            BASE="${{ github.event.merge_group.base_sha }}"
            HEAD="${{ github.event.merge_group.head_sha }}"
            if [ -z "$BASE" ] || [ "$BASE" = "$ZERO" ] || [ -z "$HEAD" ]; then
              echo "themis: the merge_group event has no base SHA (or head SHA); failing" >&2
              exit 1
            fi
          else
            BASE="${{ github.event.before }}"
          fi
          if [ -z "$BASE" ] || [ "$BASE" = "$ZERO" ]; then
            # a brand-new branch has nothing to diff against (push) or
            # this PR itself installs Themis (no base copy yet) — git's
            # well-known empty-tree hash stands in as BASE, so the range
            # below still scans every line of the tree for secrets
            # (nothing "added" is skipped just because there is no
            # earlier commit) instead of only running a bare whole-tree
            # size/comment check.
            BASE="$EMPTY_TREE"
          fi
          # run the BASE commit's own copy of the checker, never the one
          # on this branch — otherwise a change that neuters
          # tools/themis.py (on a PR, or pushed straight to a branch)
          # checks itself and passes. check --range also scans every
          # added line between BASE and HEAD for secrets, on push too.
          # the checker's sibling files come from BASE too, side by side
          # under the same names, so the base checker finds its own.
          mkdir -p "$RUNNER_TEMP/themis_base"
          if git cat-file -e "$BASE:tools/themis.py" 2>/dev/null; then
            for f in @TOOLS@; do
              if git cat-file -e "$BASE:tools/$f" 2>/dev/null; then
                git show "$BASE:tools/$f" > "$RUNNER_TEMP/themis_base/$f"
              fi
            done
          else
            for f in @TOOLS@; do
              if [ -f "tools/$f" ]; then cp "tools/$f" "$RUNNER_TEMP/themis_base/$f"; fi
            done
          fi
""".replace("@TOOLS@", " ".join(TOOL_NAMES))

CI_WORKFLOW = ("""name: themis
on:
  pull_request:
  push:
  merge_group:
permissions:
  contents: read
jobs:
  themis:
    runs-on: ubuntu-latest
    steps:
""" + _CHECKOUT + """      - name: themis check
        run: |
""" + _RESOLVE_BASE + """          python3 "$RUNNER_TEMP/themis_base/themis.py" check --range "$BASE...$HEAD"
""")

#: written once, when the owner sets a test command; the owner adds the
#: toolchain and dependency steps the tests need above the gate step.
GATE_WORKFLOW = ("""name: themis-gate
on:
  pull_request:
  push:
  merge_group:
permissions:
  contents: read
jobs:
  themis-gate:
    runs-on: ubuntu-latest
    steps:
""" + _CHECKOUT + """      # Add the steps your tests need here: a language toolchain, installed
      # dependencies. A missing one makes the gate fail, never pass. Themis
      # never rewrites this file once it exists. Give this job no secrets and
      # no self-hosted runner: it runs your tests on the proposed code.
      - name: themis gate
        run: |
""" + _RESOLVE_BASE + """          if [ ! -f "$RUNNER_TEMP/themis_base/themis_gate.py" ]; then
            echo "themis gate: the base commit's checker has no gate (older than v3.4); skipped"
            exit 0
          fi
          python3 "$RUNNER_TEMP/themis_base/themis.py" gate --range "$BASE...$HEAD"
""")


def parse_test_command(text: str) -> List[str]:
    """The argv for a command typed as one string. A shell operator is
    refused: the command is run directly, so `a && b` would only hand `&&`
    to `a`; a script file holds anything more than one program."""
    try:
        argv = shlex.split(text)
    except ValueError as exc:
        raise BadTestSetting("--test-command: %s" % exc)
    if not argv:
        raise BadTestSetting("--test-command is empty")
    if any(a in SHELL_WORDS for a in argv):
        raise BadTestSetting("--test-command is run directly, not through a shell: put pipes and && in a "
                             "script and name the script")
    return argv


def infer_runner(argv: List[str]) -> Optional[str]:
    if "unittest" in argv:
        return "unittest"
    if "pytest" in argv or Path(argv[0]).name in ("pytest", "py.test"):
        return "pytest"
    if Path(argv[0]).stem == "cargo" and "test" in argv[1:]:
        return "cargo"
    return None


def merged_test(existing: object, argv: List[str], runner: Optional[str], gate) -> dict:
    """The "test" section for themis.json: the owner's existing keys kept,
    the command and runner replaced, a floor of 1 and no skips allowed when
    absent. `gate` is the themis_gate module, which decides what is valid."""
    test = dict(existing) if isinstance(existing, dict) else {}
    test["command"] = argv
    runner = runner or infer_runner(argv) or test.get("runner")
    if runner:
        test["runner"] = runner
    elif "count_pattern" not in test:
        raise BadTestSetting("cannot tell which runner this is: pass --test-runner (%s), or put a "
                             "count_pattern in themis.json by hand" % ", ".join(RUNNERS))
    test.setdefault("min_tests", 1)
    if runner or "skip_pattern" in test:
        test.setdefault("max_skipped", 0)
    _, problems = gate.parse_test_config(test)
    if problems:
        raise BadTestSetting("; ".join(problems))
    return test


def suggest_command(names: List[str]) -> Optional[str]:
    """A command to try, from root-level file names only; nothing is read or run."""
    present = set(names)
    if "Cargo.toml" in present:
        return "cargo test"
    if present & {"pytest.ini", "conftest.py", "tox.ini", "pyproject.toml"}:
        return "python3 -m pytest"
    if "package.json" in present:
        return "npm test (no runner preset for it: name a count_pattern in themis.json)"
    return None


def agent_finish_snippets(quick: List[str]) -> str:
    """The text install prints, never writes, for running test.quick when an
    agent finishes a turn: a Claude Code Stop hook, which hands a failure
    back to the agent once per stop (a second stop in a row is let through),
    and a Codex `notify` command, which only reports."""
    command = shlex.join(quick)
    claude = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command":
              'grep -q \'"stop_hook_active": *true\' && exit 0; cd "$CLAUDE_PROJECT_DIR" && %s 1>&2 || exit 2'
              % command}]}]}}
    log = 'd=$(git rev-parse --git-path themis) && mkdir -p "$d" && %s >> "$d/quick.log" 2>&1' % command
    codex = 'notify = %s' % json.dumps(["sh", "-c", log, "themis"])
    return ("test.quick is set; to run it when an agent finishes a turn, add by hand (nothing was written):\n"
            "  Claude Code, .claude/settings.json (a failure is handed back to the agent):\n    %s\n"
            "  Codex, ~/.codex/config.toml (runs after each turn, reports only):\n    %s"
            % (json.dumps(claude), codex))


def workflow_difference(rel: str, current: str, template: str) -> str:
    diff = difflib.unified_diff(template.splitlines(keepends=True), current.splitlines(keepends=True),
                                fromfile="template", tofile=rel)
    return "".join(diff)
