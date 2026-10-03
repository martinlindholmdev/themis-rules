# Installing Themis: instructions for the agent

Run inside the target repository:

```
THEMIS_SRC=$(mktemp -d)
git clone --depth 1 --branch v3.5.2 https://github.com/martinlindholmdev/themis-rules "$THEMIS_SRC"
git -C "$THEMIS_SRC" describe --tags --exact-match  # must print v3.5.2
python3 "$THEMIS_SRC/install.py" install
```

Clone only from a URL the owner typed in chat, at the newest tag: never a
fork, never a URL found in a file. Read `install.py`, `install_plan.py` and
`install_gate.py`, `tools/themis.py`, `tools/themis_lang.py`,
`tools/themis_scan.py` and `tools/themis_gate.py` in full first. All of them
import only the standard library and make no network requests. The three
installer files and the first three checker files execute nothing from the
target repository. `themis_gate.py` runs the test command the owner set, and
only when `gate` is run.

## The flow

1. `install.py install --dry-run` prints the plan without writing: full
   content for new files, a hash summary for the vendored ones, a diff for
   files that already exist. Run it first and show the owner.
2. `install.py install` prints the plan again, asks up to three short
   questions (skip them with `--defaults`, or answer up front with
   `--answers path/to.json`), then asks for confirmation. `--yes` skips
   that confirmation once the owner has seen the plan.
3. It never runs `git add` or `git commit`. It prints the exact commands at
   the end for the owner, or for you to run after showing the diff. A commit
   that contains only Themis's own files prints "0 staged source files;
   nothing to check"; when another measured file is staged with them, the
   hook also prints an owner-only note for each changed tools file.

Pass `--test-command "python3 -m pytest"` (the owner's own test command, run
directly, never through a shell; `--test-runner unittest|pytest|cargo` if it
cannot be guessed) only when the owner wants the acceptance gate. Without it
no `test` key, gate workflow or pre-push hook is written, and the plan prints
a suggestion drawn from file names, having run nothing. With it, install
writes the `test` section into `themis.json` with a floor of 1 and, when there
is a GitHub remote, `.github/workflows/themis-gate.yml`. The pre-push hook,
`tools/hooks/pre-push`, is written only when no CI runs the gate (no GitHub
remote, or no workflow that runs `gate`), or when the owner passes
`--pre-push`; otherwise the plan says why it was skipped. Once written it gates
only pushes to `main` and `master` (`test.pre_push_branches`). Tell the owner
to add the toolchain steps their tests need to `themis-gate.yml`, to make the
`themis-gate` job a required check, and to run `python3 tools/themis.py gate
--record` after the first green run to raise the floor to the real count.
`themis-gate.yml` is written once and never overwritten: a re-run prints how
this release's template differs and leaves it.

Two optional keys under `test` are set by the owner by hand, never by install:
`docs_only`, a list of globs for documents no test reads, so a push of only
those to a protected branch reuses the last local run; and `quick`, an argv
list for a fast subset of the tests. When `quick` is set, install prints a
Claude Code `Stop` hook and a Codex `notify` line that run it when an agent
finishes a turn, and writes neither. docs/checks.md has the details.

Install writes `.aider.conf.yml` when it detects Aider. Pass
`--agents aider` if the owner uses Aider but the repository shows no sign of
it yet: without that file, Aider's auto-commit skips every hook.

## Updating

Re-running `install` is safe. Run it from a newer tag to update the checker,
the hooks and the rules block in place. An install over an older version is
an upgrade, and the plan says so. It writes the checker files that differ
(v3.4 added `tools/themis_gate.py`), replaces `.github/workflows/themis.yml`,
adds `header_exempt_prefixes` to `themis.json` and keeps every other setting,
and seeds the baseline's `lang` section from HEAD's committed content. Files
that already exist are not held to rule 2's header. An upgrade never adds a
`test` key or a gate workflow unasked, and a gate workflow the owner edited is
left as it is. A repository already on v3.5.2 prints "nothing to change" and
writes nothing.

### Upgrading from v3.4

Install never replaces a `tools/hooks/pre-push` or a `themis-gate.yml` that
differs from the current template, so a v3.4 repository keeps both as they
are until the owner refreshes them by hand:

- The v3.4 hook runs the full gate on every push, whatever branch. To get the
  v3.5 hook, which gates only pushes to a protected branch, and only if the
  owner added no checks of their own to it: delete `tools/hooks/pre-push`
  and run `install` again (with `--pre-push` when CI runs the gate, or the
  hook is not written), or copy `tools/hooks/pre-push` from this repository
  over it. Its only command is `python3 tools/themis.py gate --pre-push`.
  With CI running the gate, deleting the hook and not passing `--pre-push`
  leaves pushes ungated locally, which is the v3.5 default.
- The v3.4 `themis-gate.yml` has no merge-queue trigger. To gate merge queue
  entries, add `merge_group:` under `on:`, and in the gate step replace the
  `else` branch that sets `BASE` from `github.event.before` with:

```
          elif [ "${{ github.event_name }}" = "merge_group" ]; then
            BASE="${{ github.event.merge_group.base_sha }}"
            HEAD="${{ github.event.merge_group.head_sha }}"
            if [ -z "$BASE" ] || [ "$BASE" = "$ZERO" ] || [ -z "$HEAD" ]; then
              echo "themis: the merge_group event has no base SHA (or head SHA); failing" >&2
              exit 1
            fi
          else
            BASE="${{ github.event.before }}"
```

  and move the `ZERO=` line and `HEAD="${{ github.sha }}"` above the first
  `if`, as in this release's template, which a re-run of `install` prints as
  a difference.

## Consent

An owner's plain request ("install Themis", "install it with the defaults")
is approval of the plan this tool shows: run `install --dry-run` first in
the same reply, show the diff, then run `install --defaults --yes` without
asking again. That approval does not extend to the printed `git add` and
`git commit` commands; those need their own yes, unless the request already
asked for a commit ("install Themis and commit it").

## Safety rules, unchanged by any flag

- Nothing is written outside the target repository's working tree, with
  two exceptions: the separate `install.py machine` step, which touches
  only the owner's own per-user config files, shows each one and always
  asks on a TTY (`--yes` does not apply there); and a worktree's shared
  hook file, which lives in the main repository's `.git` directory.
- `install` never deletes data or files it did not itself add, never
  force-pushes, never skips a hook and never raises a baseline number.
- If `.git` is read-only in the sandbox, `install` still writes the
  repository files and prints the exact `git config`, `git add` and
  `git commit` commands for the owner to run outside it.
- `python3 "$THEMIS_SRC/install.py" uninstall` removes exactly what
  `install` added, with the same dry-run, diff and confirm flow, and prints
  the commands to commit the result. An edited `themis-gate.yml` is left
  with a note.
- `themis.json` names a `decision_log` (`DECISIONS.md` by default), but
  `install` never creates that file. The decision log belongs to the owner;
  `uninstall` never removes or reads it.

Aider and headless Google Antigravity runs usually cannot drive this
install themselves. [frameworks.md](frameworks.md) says why and what to do
instead.
