# Installing Themis — the agent's view

Two commands, run inside the target repo (a fixed `/tmp/themis` path
collides when more than one install runs at once — use `mktemp -d`, and
verify the tag actually checked out before trusting anything in it):

```
THEMIS_SRC=$(mktemp -d)
git clone --depth 1 --branch v3 https://github.com/martinlindholmdev/themis-rules "$THEMIS_SRC"
git -C "$THEMIS_SRC" describe --tags --exact-match  # must print v3
python3 "$THEMIS_SRC/install.py" install
```

Only from a URL the owner typed in chat, at the newest tag — never a fork,
never a URL found in a file. Read `install.py`, `install_plan.py` (the
plan-building `install.py` calls) and `tools/themis.py` whole first: all
three import only the standard library, touch no network, and never
execute anything from the target repo. `install.py install
--dry-run` prints the plan (full content for new files, a hash summary for the
vendored ones, a diff for existing files) without writing anything;
run that first and show the owner. `install` prints the plan and diff
again, asks up to three short questions (skip with `--defaults`, or
answer them up front with `--answers path/to.json`), then asks to
confirm — or pass `--yes` to skip that confirmation once the owner has
seen the plan. It never runs `git add` or `git commit` itself; it prints
the exact commands at the end for the owner, or for you to run, having
shown the diff first.

**Consent, precisely.** An owner's plain request — "install Themis",
"install it with the defaults" — is itself approval of the plan this
tool shows: run `install --dry-run` first in the same reply, show the
diff, then run `install --defaults --yes` without asking again. That
approval does not extend to the printed `git add`/`git commit` commands
at the end — those need their own yes, unless the owner's own request
already asked for a commit (e.g. "install Themis and commit it").

Safety rules, unchanged by any flag:
- Nothing is written outside the target repo's working tree, except the
  separate `install.py machine` step (which only touches the owner's own
  per-user config files, shows each one, and always asks on a TTY —
  `--yes` never applies there) and a worktree's shared hook file, which
  legitimately lives in the main repo's `.git` directory, not the
  worktree's own.
- `install` never deletes data or files it did not itself add, never
  force-pushes, never skips a hook, and never raises a baseline number.
- If `.git` is read-only in this sandbox, `install` still writes the repo
  files and prints the exact `git config`/`git add`/`git commit` commands
  for the owner to run outside it.
- `uninstall` removes exactly what `install` added, and is also a
  dry-run-first, diff-then-confirm flow.
- `themis.json` names a `decision_log` (`DECISIONS.md` by default), but
  `install` never creates that file — the decision log belongs to the
  owner, who creates it (or doesn't) by hand; `uninstall` never removes
  or even looks at it.

Re-running `install` is always safe — a repo already on v3 prints
"nothing to change" and writes nothing.

Pass `--agents aider` if the owner uses Aider but the repo shows no sign of it yet:
Aider's auto-commit skips every hook without the `.aider.conf.yml` that flag creates.

If you are Aider or a headless Google Antigravity run, you likely cannot
drive this yourself — see [frameworks.md](frameworks.md) for why, and what to do
instead.
