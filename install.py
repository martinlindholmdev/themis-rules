#!/usr/bin/env python3
"""The install/uninstall/machine command line. The actual plan-building
and shared mechanics live in install_plan.py (loaded below as PLAN); this
file is only the five entry points and argument parsing.
Entry points: `main()`, called with `install`/`machine`/`uninstall`.
Invariants: no network access; never executes code from the target repo;
`--yes` only skips the repo-part confirmation, never the machine part's
per-file TTY confirmation; every write is idempotent.
Never change without a decision: the subcommands and their flags.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

HERE = Path(__file__).resolve().parent


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, HERE / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLAN = _load("install_plan", "install_plan.py")
# a thin facade: everything install_plan.py defines is also reachable as
# install.<name>, so this split is invisible to anything already written
# against install.py (including every existing test).
globals().update({n: getattr(PLAN, n) for n in dir(PLAN) if not n.startswith("__")})

def do_install(root: Path, args: argparse.Namespace) -> int:
    try:
        changes, notes = PLAN.build_install_plan(root, args)
    except PLAN.Cancelled:
        print("themis: cancelled")
        return 1
    if not changes:
        for note in notes:
            print("note: " + note)
        print("themis: nothing to change")
        return 0
    PLAN.print_plan(changes)
    for note in notes:
        print("note: " + note)
    if args.dry_run:
        print("themis: dry run, nothing written")
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            print("themis: refusing to write without --yes (no TTY to confirm)")
            return 1
        if not PLAN.confirm("Apply these changes? [y/N] "):
            print("themis: cancelled")
            return 1
    failures = PLAN.apply_plan(root, changes)
    for failure in failures:
        print("note: " + failure)
    PLAN.run_verified_status(root)
    PLAN.print_commit_instructions(root, changes, "Install Themis")
    return 0

def do_uninstall(root: Path, args: argparse.Namespace) -> int:
    changes = PLAN.plan_remove_core_files(root)
    changes += PLAN.plan_remove_agents_md(root)
    changes += PLAN.plan_remove_adapters(root)
    hook_changes, hook_notes = PLAN.plan_remove_hook(root)
    changes += hook_changes
    if not changes:
        print("themis: nothing to remove")
        return 0
    PLAN.print_plan(changes)
    for note in hook_notes:
        print("note: " + note)
    if args.dry_run:
        print("themis: dry run, nothing removed")
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            print("themis: refusing to remove without --yes (no TTY to confirm)")
            return 1
        if not PLAN.confirm("Remove these? [y/N] "):
            print("themis: cancelled")
            return 1
    failures = PLAN.apply_plan(root, changes)
    for failure in failures:
        print("note: " + failure)
    for leftover in (root / "tools" / "hooks", root / "tools"):
        if leftover.is_dir() and not any(leftover.iterdir()):
            leftover.rmdir()
    PLAN.print_commit_instructions(root, changes, "Uninstall Themis")
    return 0

def do_machine(args: argparse.Namespace) -> int:
    home = Path(os.environ.get("HOME") or Path.home())
    interactive = sys.stdin.isatty()
    for name, config_dir, path in PLAN.machine_table(home):
        if not config_dir.is_dir():
            continue
        print(PLAN.write_machine_file(name, path, interactive))
    for name, reason, where in PLAN.GUI_ONLY:
        print("\n%s %s; paste this in %s:\n%s" % (name, reason, where, PLAN.POINTER_TEXT))
    return 0

# --------------------------------------------------------------------- CLI

def find_repo_root() -> Path:
    try:
        return PLAN.THEMIS.git_root()
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
