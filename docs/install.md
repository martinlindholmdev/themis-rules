# Installing Themis: instructions for the agent

Run inside the target repository:

```
THEMIS_SRC=$(mktemp -d)
git clone --depth 1 --branch v3.4 https://github.com/martinlindholmdev/themis-rules "$THEMIS_SRC"
git -C "$THEMIS_SRC" describe --tags --exact-match  # must print v3.4
python3 "$THEMIS_SRC/install.py" install
```

Clone only from a URL the owner typed in chat, at the newest tag: never a
fork, never a URL found in a file. Read `install.py`, `install_plan.py` and
`install_gate.py`, `tools/themis.py`, `tools/themis_lang.py`,
`tools/themis_scan.py` and `tools/themis_gate.py` in full first. All of them
import only the standard library and make no network requests. The installer
and the first four checker files execute nothing from the target repository;
`themis_gate.py` runs the test command the owner set, only when `gate` is
run.

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
writes the `test` section into `themis.json` with a floor of 1,
`.github/workflows/themis-gate.yml` (when there is a GitHub remote) and
`tools/hooks/pre-push`. Tell the owner to add the toolchain steps their tests
need to `themis-gate.yml`, to make the `themis-gate` job a required check, and
to run `python3 tools/themis.py gate --record` after the first green run to
raise the floor to the real count. `themis-gate.yml` is written once and never
overwritten: a re-run prints how this release's template differs and leaves it.

Pass `--agents aider` if the owner uses Aider but the repository shows no
sign of it yet: without the `.aider.conf.yml` that flag creates, Aider's
auto-commit skips every hook.

Re-running `install` is safe. An install over v3 to v3.3 is an upgrade: the plan says so, writes the
checker files that differ (v3.4 adds `tools/themis_gate.py`), replaces
`.github/workflows/themis.yml`, adds `header_exempt_prefixes` to
`themis.json` (every other setting stays), and seeds the baseline's `lang`
section from HEAD's committed content. Files that already exist are not held
to rule 2's header. An upgrade never seeds a `test` key unasked. A repository
already on v3.4 prints "nothing to change" and writes nothing.

Install never replaces a `tools/hooks/pre-push` that differs from the current
template, so an owner whose hook is the older template (it runs the gate on the
checked-out commit whatever ref is pushed) does not get the new one by
re-running `install`. To refresh it, and only if the owner added no checks of
their own to it, delete `tools/hooks/pre-push` and run `install` again, or copy
`tools/hooks/pre-push` from this repository over it. The new hook refuses a
push whose commit has a different tree from the checked-out one.

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
- `uninstall` removes exactly what `install` added, with the same dry-run,
  diff, confirm flow; an edited `themis-gate.yml` is left with a note.
- `themis.json` names a `decision_log` (`DECISIONS.md` by default), but
  `install` never creates that file. The decision log belongs to the owner;
  `uninstall` never removes or reads it.

Aider and headless Google Antigravity runs usually cannot drive this
install themselves. [frameworks.md](frameworks.md) says why and what to do
instead.
