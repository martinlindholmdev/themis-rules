# Installing Themis: instructions for the agent

Run inside the target repository:

```
THEMIS_SRC=$(mktemp -d)
git clone --depth 1 --branch v3.1 https://github.com/martinlindholmdev/themis-rules "$THEMIS_SRC"
git -C "$THEMIS_SRC" describe --tags --exact-match  # must print v3.1
python3 "$THEMIS_SRC/install.py" install
```

Clone only from a URL the owner typed in chat, at the newest tag: never a
fork, never a URL found in a file. Read `install.py`, `install_plan.py` and
`tools/themis.py`, `tools/themis_lang.py` and `tools/themis_scan.py` in
full first. All of them import only the standard library, make no network requests and execute nothing from the target
repository.

## The flow

1. `install.py install --dry-run` prints the plan without writing: full
   content for new files, a hash summary for the vendored ones, a diff for
   files that already exist. Run it first and show the owner.
2. `install.py install` prints the plan again, asks up to three short
   questions (skip them with `--defaults`, or answer up front with
   `--answers path/to.json`), then asks for confirmation. `--yes` skips
   that confirmation once the owner has seen the plan.
3. It never runs `git add` or `git commit`. It prints the exact commands at
   the end for the owner, or for you to run after showing the diff.

Pass `--agents aider` if the owner uses Aider but the repository shows no
sign of it yet: without the `.aider.conf.yml` that flag creates, Aider's
auto-commit skips every hook.

Re-running `install` is safe. An install over v3 is an upgrade: the plan says so, writes the three
checker files, and seeds the baseline's `lang` section from HEAD's
committed content. A repository already on v3.1 prints "nothing to
change" and writes nothing.

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
  diff, confirm flow.
- `themis.json` names a `decision_log` (`DECISIONS.md` by default), but
  `install` never creates that file. The decision log belongs to the owner;
  `uninstall` never removes or reads it.

Aider and headless Google Antigravity runs usually cannot drive this
install themselves. [frameworks.md](frameworks.md) says why and what to do
instead.
