"""The acceptance gate: runs the project's own test command and judges it.

Purpose: run the command the owner set under "test" in themis.json on the
exact committed tree, read how many tests ran and were skipped from its
output, and fail on an error, no count, too few tests or too many skips;
also holds the git runner and the hook, CI and gate lines `status` prints.
Entry points: run() for `themis.py gate` (plain, --range A...B, --reuse,
--pre-push, --record, --lower N --reason TEXT), add_arguments(),
parse_test_config(), runs_gate_in_ci(), status_lines(), git(), hooks_dir(),
hook_status().
Invariants: standard library only, python3 3.9+, no network access; the
command is an argv list run without a shell and with no stdin; its
settings come from the BASE commit's themis.json (A for --range, the
destination branch's current commit for --pre-push, HEAD otherwise), so a
change cannot edit its own gate; the tracked working tree
and index must equal the tree of the commit being gated before the run and
again after it, except under the owner's ignore_paths; stdout and stderr are
merged and ANSI codes stripped before the output is read; a missing count is
a failure, never a zero; a pass names the commit and tree it covers; the
local receipt in .git is evidence for a reader and a skip-the-rerun cache,
never read by CI; --pre-push gates only a push to a protected branch and
reuses the receipt across a documents-only change that leaves themis.json and
every judged setting as the receipt saw them; writes only that receipt,
themis.json under --record and --lower, and the decision log under --lower.
Never change without a decision: the themis.json "test" key names and their
meaning, the runner presets, the PASS line, and the rule that the base
commit's settings and the committed tree decide.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import fnmatch
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, NamedTuple, Optional, Tuple

SELF_NAME = "themis.py"
CONFIG_NAME = "themis.json"
RECEIPT = "themis/gate.json"
TAIL_LINES = 40
#: runner -> (count pattern, skip pattern); one group each, summed over all matches.
#: pytest's xfailed counts as skipped: `xfail(run=False)` reports xfailed
#: without running the body and the summary cannot tell the two apart.
PRESETS = {
    "unittest": (r"^Ran (\d+) tests? in ", r"\bskipped=(\d+)"),
    "pytest": (r"(?:^|, |= )(\d+) (?:passed|failed|skipped|xfailed|xpassed|errors?)\b",
               r"(?:^|, |= )(\d+) (?:skipped|xfailed)\b"),
    "cargo": (r"^running (\d+) tests?$", r"\b(\d+) ignored\b"),
}
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def git(root: Path, *args: str) -> str:
    """Runs git in `root`, quotepath off, output decoded as UTF-8."""
    cmd = ["git", "-c", "core.quotepath=off", "-C", str(root)] + list(args)
    return subprocess.run(cmd, check=True, capture_output=True, encoding="utf-8", errors="replace").stdout


def _safe(text: str) -> str:
    """A name from the repo or the test output with control characters made visible."""
    return "".join(c if ord(c) >= 0x20 and ord(c) != 0x7f else "?" for c in text)


# ---------------------------------------------------------------- hooks and CI

def hooks_dir(root: Path) -> Tuple[Path, str]:
    """core.hooksPath if set, else --git-path hooks (safe under worktrees
    and submodules, where .git is a file, not a dir)."""
    try:
        configured = git(root, "config", "--get", "core.hooksPath").strip()
    except subprocess.CalledProcessError:
        configured = ""
    if configured:
        path = Path(configured)
        return (path if path.is_absolute() else root / path), "core.hooksPath=%s" % configured
    git_path = git(root, "rev-parse", "--git-path", "hooks").strip()
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


def _workflow_texts(root: Path) -> List[str]:
    workflows = root / ".github" / "workflows"
    if not workflows.is_dir():
        return []
    return [p.read_text(encoding="utf-8", errors="replace")
            for p in sorted(workflows.iterdir()) if p.suffix in (".yml", ".yaml") and p.is_file()]


_RUNS_GATE = re.compile(r"%s\"?\s+gate\b" % re.escape(SELF_NAME))


def runs_gate_in_ci(root: Path) -> bool:
    """True when a workflow file runs the gate."""
    return any(_RUNS_GATE.search(t) for t in _workflow_texts(root))


def ci_line(root: Path, configured: bool) -> str:
    """What the workflow files show; whether the job is a required check, and
    whether its triggers cover every branch, is not something a clone can see."""
    texts = _workflow_texts(root)
    if not any(SELF_NAME in t for t in texts):
        return "CI: no workflow runs %s" % SELF_NAME
    line = "CI: workflow wiring detected (a workflow runs %s" % SELF_NAME
    if configured and not runs_gate_in_ci(root):
        return line + ", but none runs the gate: tests are not checked on the server)"
    return line + "); a required check, branch protection and trigger coverage are not verified"


# --------------------------------------------------------------- configuration

class GateConfig(NamedTuple):
    command: List[str]
    count: "re.Pattern[str]"
    skip: Optional["re.Pattern[str]"]
    min_tests: int
    max_skipped: int
    timeout: int
    ignore: List[str]
    branches: List[str]
    docs_only: Optional[List[str]]
    quick: Optional[List[str]]


def _pattern(value: object, name: str, problems: List[str]) -> Optional["re.Pattern[str]"]:
    if not isinstance(value, str) or not value or len(value) > 500:
        problems.append("test.%s must be a regular expression of at most 500 characters" % name)
        return None
    try:
        compiled = re.compile(value, re.MULTILINE)
    except re.error as exc:
        problems.append("test.%s does not compile (%s)" % (name, exc))
        return None
    if compiled.groups != 1:
        problems.append("test.%s must have exactly one group, the number" % name)
        return None
    return compiled


def _whole(raw: dict, key: str, default: int, low: int, high: int, problems: List[str]) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        problems.append("test.%s must be a whole number from %d to %d" % (key, low, high))
        return default
    return value


def _strings(raw: dict, key: str, default: Optional[List[str]], problems: List[str]) -> Optional[List[str]]:
    value = raw.get(key, default)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) and v and "\0" not in v for v in value):
        problems.append("test.%s must be a list of non-empty strings" % key)
        return default
    return list(value)


def parse_test_config(raw: object) -> Tuple[Optional[GateConfig], List[str]]:
    """(config, problems) for a themis.json "test" value. None with no
    problems means no gate is configured; a configured gate that cannot be
    understood is a problem, never silently the same as none."""
    if raw is None:
        return None, []
    if not isinstance(raw, dict):
        return None, ["test must be an object"]
    problems: List[str] = []
    command = raw.get("command")
    if (not isinstance(command, list) or not command
            or not all(isinstance(a, str) and a and "\0" not in a for a in command)):
        problems.append("test.command must be a non-empty list of strings (an argv, never a shell string)")
    runner = raw.get("runner")
    if runner is not None and runner not in PRESETS:
        problems.append("test.runner must be one of %s" % ", ".join(sorted(PRESETS)))
        runner = None
    preset = PRESETS.get(runner, (None, None))
    count = _pattern(raw["count_pattern"], "count_pattern", problems) if "count_pattern" in raw else None
    skip = _pattern(raw["skip_pattern"], "skip_pattern", problems) if "skip_pattern" in raw else None
    if count is None and not any("count_pattern" in p for p in problems):
        if preset[0] is None:
            problems.append("test needs a runner (%s) or a count_pattern" % ", ".join(sorted(PRESETS)))
        else:
            count = re.compile(preset[0], re.MULTILINE)
    if skip is None and preset[1] is not None and "skip_pattern" not in raw:
        skip = re.compile(preset[1], re.MULTILINE)
    if skip is None and "max_skipped" in raw:
        problems.append("test.max_skipped needs a skip_pattern or a runner preset to read skips from")
    ignore = raw.get("ignore_paths", [])
    if not isinstance(ignore, list) or not all(isinstance(p, str) and p for p in ignore):
        problems.append("test.ignore_paths must be a list of non-empty path prefixes")
        ignore = []
    branches = _strings(raw, "pre_push_branches", ["main", "master"], problems) or []
    docs_only = _strings(raw, "docs_only", None, problems)
    quick = _strings(raw, "quick", None, problems)
    if quick == []:
        problems.append("test.quick must name a command (an argv list) when present")
    floor = _whole(raw, "min_tests", 1, 1, 10 ** 9, problems)
    ceiling = _whole(raw, "max_skipped", 0, 0, 10 ** 9, problems)
    timeout = _whole(raw, "timeout", 1800, 1, 86400, problems)
    if problems or count is None:
        return None, problems
    return GateConfig(list(command), count, skip, floor, ceiling, timeout, list(ignore),
                      branches, docs_only, quick), []


def raw_test_at(root: Path, rev: str) -> Tuple[object, Optional[str]]:
    """(the "test" value, None) from themis.json committed at `rev`, or
    (None, why) when there is no readable themis.json there."""
    try:
        text = git(root, "show", "%s:%s" % (rev, CONFIG_NAME))
    except subprocess.CalledProcessError:
        return None, "no %s at %s" % (CONFIG_NAME, rev)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None, "%s at %s is not valid JSON" % (CONFIG_NAME, rev)
    return (data.get("test") if isinstance(data, dict) else None), None


# ------------------------------------------------------------------- judging

def clean_output(text: str) -> str:
    """Line breaks normalised and ANSI colour codes removed, so a runner that
    colours its summary still matches the patterns."""
    return _ANSI.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))


def _sum(pattern: "re.Pattern[str]", text: str) -> Optional[int]:
    found = [int(m.group(1)) for m in pattern.finditer(text)]
    return sum(found) if found else None


def judge(cfg: GateConfig, output: str, status: Optional[int],
          timed_out: bool) -> Tuple[Optional[int], Optional[int], List[str]]:
    """(tests that ran, skipped or None when not measured, problems). A
    skip is not a test that ran. No count in the output is a problem even
    when the exit status was zero."""
    if timed_out:
        return None, None, ["the test command timed out after %d seconds" % cfg.timeout]
    problems: List[str] = []
    if status != 0:
        problems.append("the test command exited with status %s" % status)
    try:
        total = _sum(cfg.count, output)
        skipped = None if cfg.skip is None else (_sum(cfg.skip, output) or 0)
    except ValueError:
        return None, None, problems + ["a test pattern matched text that is not a number"]
    if total is None:
        return None, skipped, problems + ["no test count found in the output; a run that reports "
                                           "no count is never read as a pass"]
    ran = total - (skipped or 0)
    if ran < 0:
        return None, skipped, problems + ["the output reports more skips (%d) than tests (%d)" % (skipped, total)]
    if ran < max(1, cfg.min_tests):
        problems.append("%d test(s) ran, below the floor of %d" % (ran, max(1, cfg.min_tests)))
    if skipped is not None and skipped > cfg.max_skipped:
        problems.append("%d test(s) skipped, above the ceiling of %d" % (skipped, cfg.max_skipped))
    return ran, skipped, problems


def command_hash(command: Optional[list]) -> str:
    """A short hash of a list: the test command, the docs_only globs or the settings."""
    return hashlib.sha256(json.dumps(command).encode("utf-8")).hexdigest()[:12]


def settings_hash(cfg: "GateConfig") -> str:
    """A short hash of every setting that changes what the gate judges: the
    command, both patterns, floor, skip ceiling, timeout, ignore_paths,
    protected branches and the docs_only list. test.quick is left out, since
    the gate never runs it."""
    return command_hash([cfg.command, cfg.count.pattern, cfg.skip.pattern if cfg.skip else None,
                         cfg.min_tests, cfg.max_skipped, cfg.timeout, cfg.ignore, cfg.branches, cfg.docs_only])


class Ran(NamedTuple):
    output: str
    status: Optional[int]
    timed_out: bool
    error: Optional[str]


def _stop_tree(proc: "subprocess.Popen[bytes]") -> None:
    """Ends the command and everything it started: the whole process group on
    POSIX (the command runs in its own session), `taskkill /T` on Windows. A
    descendant that leaves the group on purpose is not reached."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        proc.kill()
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        proc.kill()


def run_command(root: Path, cfg: GateConfig) -> Ran:
    first = cfg.command[0]
    exe = str(root / first) if ("/" in first or os.sep in first) else shutil.which(first)
    if exe is None:
        return Ran("", None, False, "command not found: %s" % _safe(first))
    argv = [exe] + cfg.command[1:]
    group = {"start_new_session": True} if os.name != "nt" else {}
    try:
        proc = subprocess.Popen(argv, cwd=str(root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, **group)
    except OSError as exc:
        return Ran("", None, False, "cannot run %s (%s)" % (_safe(first), exc.strerror or "error"))
    try:
        out, _ = proc.communicate(timeout=cfg.timeout)
    except subprocess.TimeoutExpired:
        _stop_tree(proc)
        try:
            out, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            out = b""
        return Ran(clean_output(out.decode("utf-8", errors="replace")), None, True, None)
    return Ran(clean_output(out.decode("utf-8", errors="replace")), proc.returncode, False, None)


# ------------------------------------------------------------ the committed tree

def tree_problems(root: Path, rev: str, ignore: List[str]) -> List[str]:
    """Tracked paths whose index or working-tree content differs from the
    tree of `rev`, less the owner's ignore_paths. The tests read the working
    tree, so a result is only about `rev` when none differ."""
    differing = set()
    for extra in ((), ("--cached",)):
        out = git(root, "diff", "--name-only", "--no-renames", "-z", *extra, rev)
        differing.update(p for p in out.split("\0") if p)
    left = sorted(p for p in differing if not any(p.startswith(i) for i in ignore))
    if not left:
        return []
    names = ", ".join(_safe(p) for p in left[:5]) + (" and %d more" % (len(left) - 5) if len(left) > 5 else "")
    return ["tracked files differ from the committed tree of %s: %s; the gate covers only what is committed, "
            "so commit or restore them (generated files the tests need go in test.ignore_paths)" % (rev[:12], names)]


def _rev(root: Path, name: str) -> Optional[str]:
    try:
        return git(root, "rev-parse", "--verify", "--quiet", name).strip() or None
    except subprocess.CalledProcessError:
        return None


# -------------------------------------------------------------------- receipt

def receipt_path(root: Path) -> Path:
    return root / git(root, "rev-parse", "--git-path", RECEIPT).strip()


def read_receipt(root: Path) -> Optional[dict]:
    try:
        data = json.loads(receipt_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None
    return data if isinstance(data, dict) else None


def write_receipt(root: Path, data: dict) -> None:
    try:
        path = receipt_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    except (OSError, subprocess.CalledProcessError):
        print("note: the local receipt could not be written; the gate will rerun next time")


def _matching_receipt(root: Path, cfg: GateConfig) -> Optional[dict]:
    tree = _rev(root, "HEAD^{tree}")
    receipt = read_receipt(root)
    if (receipt and tree and receipt.get("tree") == tree and receipt.get("command") == command_hash(cfg.command)
            and receipt.get("settings") == settings_hash(cfg)):
        return receipt
    return None


def _modes(root: Path, tree: str) -> dict:
    """path -> mode for every entry of `tree`, a gitlink included."""
    out = git(root, "ls-tree", "-r", "-z", "--full-tree", tree)
    return {entry.split("\t", 1)[1]: entry.split(" ", 1)[0] for entry in out.split("\0") if "\t" in entry}


def _docs_only_receipt(root: Path, cfg: GateConfig) -> Optional[dict]:
    """The receipt, when it was written under these settings (the command and
    docs_only list included) and every path changed since its tree is a
    regular file, of the same mode on both sides, matching a docs_only glob
    and not themis.json. A gitlink, symlink, mode change or any git error
    means no reuse."""
    receipt = read_receipt(root)
    if (not cfg.docs_only or not receipt or receipt.get("command") != command_hash(cfg.command)
            or receipt.get("docs_only") != command_hash(cfg.docs_only)
            or receipt.get("settings") != settings_hash(cfg)):
        return None
    old = receipt.get("tree")
    if not isinstance(old, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", old):
        return None
    try:
        fields = [f for f in git(root, "diff", "--name-status", "-z", "--no-renames", "--ignore-submodules=none",
                                 old, "HEAD^{tree}").split("\0") if f]
        before, after = _modes(root, old), _modes(root, "HEAD^{tree}")
    except subprocess.CalledProcessError:
        return None
    if len(fields) % 2:
        return None
    for path in fields[1::2]:
        if path == CONFIG_NAME:
            return None
        modes = {before.get(path), after.get(path)} - {None}
        if len(modes) != 1 or not modes <= {"100644", "100755"}:
            return None
        if not any(fnmatch.fnmatchcase(path, glob) for glob in cfg.docs_only):
            return None
    return receipt


# ------------------------------------------------------------------ the gate

def _fail(problems: List[str], output: str = "") -> int:
    print("themis: gate FAIL, %d problem(s)" % len(problems))
    for problem in problems:
        print("  " + problem)
    lines = output.strip().splitlines()[-TAIL_LINES:]
    if lines:
        print("--- last %d line(s) of the test output ---" % len(lines))
        print("\n".join(lines))
    return 1


def _pass_line(commit: str, tree: str, cfg: GateConfig, ran: int, skipped: Optional[int], note: str = "") -> str:
    return "themis: gate PASS commit=%s tree=%s tests=%d skipped=%s floor=%d cmd=%s%s" % (
        commit, tree, ran, "n/a" if skipped is None else skipped, max(1, cfg.min_tests),
        command_hash(cfg.command), note)


def _load(root: Path, cfg_rev: str) -> Tuple[Optional[GateConfig], int]:
    """(config, -1) to go on, or (None, exit status) when the gate ends here."""
    raw, why = raw_test_at(root, cfg_rev)
    if why is not None:
        print("themis: gate skipped, %s: tests are honour-system here" % why)
        return None, 0
    cfg, problems = parse_test_config(raw)
    if problems:
        return None, _fail(["themis.json at %s: %s" % (cfg_rev[:12], p) for p in problems])
    if cfg is None:
        print("themis: gate skipped, no test command in %s at %s: tests are honour-system here"
              % (CONFIG_NAME, cfg_rev[:12]))
        return None, 0
    return cfg, -1


def execute(root: Path, cfg_rev: str, target: str, local: bool, reuse: bool,
            cfg: Optional[GateConfig] = None) -> Tuple[int, Optional[GateConfig], int]:
    """Gates `target` under the settings committed at `cfg_rev`, or under
    `cfg` when the caller already loaded them from there; that caller is the
    pre-push gate, which also reuses a receipt across a documents-only change.
    Returns (exit status, config, tests that ran)."""
    docs = cfg is not None
    if cfg is None:
        cfg, ended = _load(root, cfg_rev)
        if cfg is None:
            return ended, None, 0
    commit, head = _rev(root, target + "^{commit}"), _rev(root, "HEAD")
    if commit is None or commit != head:
        return _fail(["the checked-out commit is not %s; the gate runs only on the commit it names" % target]), cfg, 0
    tree = _rev(root, commit + "^{tree}") or ""
    before = tree_problems(root, commit, cfg.ignore)
    if before:
        return _fail(before), cfg, 0
    receipt = _matching_receipt(root, cfg) if reuse else None
    note = " (reused: the local run on this exact tree)"
    if receipt is None and docs:
        receipt = _docs_only_receipt(root, cfg)
        note = " (reused: only docs_only files changed since the local run on tree %s)" % (
            receipt or {}).get("tree", "")[:12]
    if receipt:
        print(_pass_line(commit, tree, cfg, receipt.get("tests", 0), receipt.get("skipped"), note))
        return 0, cfg, int(receipt.get("tests", 0))
    result = run_command(root, cfg)
    if result.error:
        return _fail([result.error]), cfg, 0
    ran, skipped, problems = judge(cfg, result.output, result.status, result.timed_out)
    problems += tree_problems(root, commit, cfg.ignore)
    if problems or ran is None:
        return _fail(problems or ["no result"], result.output), cfg, 0
    print(_pass_line(commit, tree, cfg, ran, skipped))
    if local:
        write_receipt(root, {"commit": commit, "tree": tree, "command": command_hash(cfg.command),
                             "docs_only": command_hash(cfg.docs_only), "settings": settings_hash(cfg),
                             "tests": ran, "skipped": skipped})
    return 0, cfg, ran


def _destination_readable(root: Path, remote_sha: str) -> bool:
    """True when the destination's current commit is a new branch (all-zero
    sha) or an object present in this clone; git's advertised sha is the only
    commit whose settings count, so a stale remote-tracking ref never stands in."""
    return set(remote_sha) == {"0"} or _rev(root, remote_sha + "^{commit}") is not None


def _branches_at(root: Path, rev: str) -> List[str]:
    """test.pre_push_branches committed at `rev`, or none when it has no valid list."""
    raw, why = raw_test_at(root, rev)
    cfg, _ = parse_test_config(raw) if why is None else (None, [])
    return cfg.branches if cfg is not None else []


def pre_push(root: Path, lines: List[str]) -> int:
    """The pre-push hook's gate. Each stdin line is `local-ref local-sha
    remote-ref remote-sha`; only a line updating a protected branch
    (test.pre_push_branches at HEAD or at the destination's current commit)
    is gated, under the test settings at the destination's current commit,
    or HEAD's when the branch is new, so a push cannot remove, weaken or skip
    its own gate; a branch update whose current commit this clone lacks is
    refused. Each gated commit must have the checked-out tree, since that is
    the tree the gate tests."""
    pushes = [p for p in (line.split() for line in lines) if len(p) == 4 and set(p[1]) != {"0"}]
    if not pushes:
        return 0
    raw, why = raw_test_at(root, "HEAD")
    head_cfg, problems = parse_test_config(raw) if why is None else (None, [])
    if problems:
        return _fail(["themis.json at HEAD: %s" % p for p in problems])
    head_branches = head_cfg.branches if head_cfg is not None else []
    gated = []
    for local_ref, local_sha, remote_ref, remote_sha in pushes:
        if not remote_ref.startswith("refs/heads/"):
            continue
        if not _destination_readable(root, remote_sha):
            return _fail(["the current commit of %s is not in this clone, so its test settings cannot be read; "
                          "fetch, then push again" % _safe(remote_ref)])
        new = set(remote_sha) == {"0"}
        protected = head_branches + ([] if new else _branches_at(root, remote_sha))
        if remote_ref[len("refs/heads/"):] in protected:
            gated.append((local_ref, local_sha, "HEAD" if new else remote_sha))
    if not gated:
        print("themis: pre-push: nothing pushed to %s, so no tests run here; CI runs them"
              % (", ".join(_safe(b) for b in head_branches) or "a protected branch"))
        return 0
    head_tree = _rev(root, "HEAD^{tree}")
    for local_ref, local_sha, _ in gated:
        if head_tree is None or _rev(root, local_sha + "^{tree}") != head_tree:
            sys.stderr.write("themis: %s is not the checked-out commit, so the gate has not tested it; "
                             "check it out and push from there\n" % _safe(local_ref))
            return 1
    judged = set()
    for _, _, cfg_rev in gated:
        cfg, ended = _load(root, cfg_rev)
        if cfg is None:
            if ended:
                return ended
            continue
        if settings_hash(cfg) not in judged:
            judged.add(settings_hash(cfg))
            status = execute(root, cfg_rev, "HEAD", True, True, cfg)[0]
            if status:
                return status
    return 0


# ------------------------------------------------- owner-only changes to the floor

def _update_test_section(root: Path, safe_path: Callable[[Path, str], Path],
                         change: Callable[[dict, dict], Optional[str]]) -> int:
    """Rewrites the working-tree themis.json through `change(whole, test)`,
    which returns an error text or None."""
    try:
        path = safe_path(root, CONFIG_NAME)
        whole = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print("themis: cannot read %s (%s)" % (CONFIG_NAME, exc.__class__.__name__))
        return 1
    test = whole.get("test") if isinstance(whole, dict) else None
    if not isinstance(test, dict):
        print("themis: %s has no test section to change" % CONFIG_NAME)
        return 1
    before = json.dumps(whole)
    error = change(whole, test)
    if error:
        print("themis: " + error)
        return 1
    if json.dumps(whole) == before:
        return 0
    path.write_text(json.dumps(whole, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


def record_floor(root: Path, safe_path: Callable[[Path, str], Path], observed: int) -> int:
    def change(whole: dict, test: dict) -> Optional[str]:
        current = test.get("min_tests", 1)
        if not isinstance(current, int) or isinstance(current, bool) or observed <= current:
            print("themis: floor stays at %s (this run had %d)" % (current, observed))
            return None
        test["min_tests"] = observed
        print("themis: floor raised from %d to %d in %s; commit it" % (current, observed, CONFIG_NAME))
        return None
    return _update_test_section(root, safe_path, change)


def lower_floor(root: Path, safe_path: Callable[[Path, str], Path], target: int, reason: Optional[str]) -> int:
    reason = (reason or "").strip()
    if not reason or "\n" in reason or "\r" in reason or len(reason) > 300:
        print("themis: --lower needs --reason with one line of at most 300 characters")
        return 2

    def change(whole: dict, test: dict) -> Optional[str]:
        current = test.get("min_tests", 1)
        log = whole.get("decision_log")
        if not isinstance(current, int) or isinstance(current, bool) or not 1 <= target < current:
            return "the floor is %s; --lower needs a whole number from 1 to %s" % (current, current - 1)
        if not isinstance(log, str) or not re.fullmatch(r"[\w./-]+", log):
            return "set decision_log in %s to a file name first; the lowering is written there" % CONFIG_NAME
        try:
            log_path = safe_path(root, log)
            old = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            line = "- The test floor was lowered from %d to %d: %s\n" % (current, target, reason)
            log_path.write_text(old + ("" if not old or old.endswith("\n") else "\n") + line, encoding="utf-8")
        except (OSError, ValueError) as exc:
            return "cannot write the decision log (%s)" % exc.__class__.__name__
        test["min_tests"] = target
        test["floor_reason"] = reason
        print("themis: floor lowered from %d to %d; %s and %s changed. Commit them on the base branch "
              "by themselves, before the change that removes tests." % (current, target, CONFIG_NAME, log))
        return None
    return _update_test_section(root, safe_path, change)


# ------------------------------------------------------- command line, status

def add_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--range", metavar="A...B", help="CI: gate commit B under the settings committed at A")
    group.add_argument("--reuse", action="store_true", help="skip the run when the last local run covers this tree")
    group.add_argument("--pre-push", action="store_true",
                       help="the pre-push hook: read git's ref lines on stdin, gate only a push to a protected branch")
    group.add_argument("--record", action="store_true", help="after a pass, raise min_tests to the tests that ran")
    group.add_argument("--lower", type=int, metavar="N", help="owner only: lower min_tests to N")
    parser.add_argument("--reason", help="with --lower: why, in one line; written to the decision log")


def run(root: Path, args: argparse.Namespace, safe_path: Callable[[Path, str], Path]) -> int:
    if args.lower is not None:
        return lower_floor(root, safe_path, args.lower, args.reason)
    if args.reason is not None:
        print("themis: --reason goes with --lower")
        return 2
    if args.pre_push:
        return pre_push(root, sys.stdin.read().splitlines())
    cfg_rev, target = "HEAD", "HEAD"
    if args.range:
        if "..." not in args.range:
            print("themis: --range needs the form A...B (e.g. origin/main...HEAD)")
            return 2
        cfg_rev, target = args.range.split("...", 1)
        base, _ = raw_test_at(root, cfg_rev)
        head, _ = raw_test_at(root, target)
        if base != head:
            print("note: the test settings changed between %s and %s; owner only, the settings at %s are used"
                  % (cfg_rev[:12], target[:12], cfg_rev[:12]))
    status, cfg, ran = execute(root, cfg_rev, target, not args.range, args.reuse)
    if status == 0 and cfg is not None and args.record:
        return record_floor(root, safe_path, ran)
    return status


def _pre_push_line(root: Path) -> str:
    hooks_path, _ = hooks_dir(root)
    hook = hooks_path / "pre-push"
    if hook.is_file() and re.search(r"%s\"?\s+gate\b" % re.escape(SELF_NAME),
                                    hook.read_text(encoding="utf-8", errors="replace")):
        return "pre-push: runs the gate before a push to a protected branch"
    return "pre-push: not wired in this clone; the gate runs in CI only"


def status_lines(root: Path, raw_test: object) -> List[str]:
    """The CI, acceptance gate and local-gate lines for `status`, from this
    clone's themis.json; nothing here asks a server anything."""
    cfg, problems = parse_test_config(raw_test)
    lines = [ci_line(root, cfg is not None)]
    if problems:
        return lines + ["acceptance gate: configured but not valid (%s)" % "; ".join(problems)]
    if cfg is None:
        return lines + ["acceptance gate: not configured: tests are honour-system"]
    lines.append("acceptance gate: configured (command %s, floor %d, max skipped %s)" % (
        " ".join(_safe(a) for a in cfg.command), max(1, cfg.min_tests), cfg.max_skipped if cfg.skip else "not measured"))
    receipt = _matching_receipt(root, cfg)
    lines.append("last local gate: tree matches HEAD, %s tests" % receipt.get("tests") if receipt
                 else "last local gate: none or stale")
    lines.append(_pre_push_line(root))
    return lines
