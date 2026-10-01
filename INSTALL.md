# Installing Themis — the agent's view

Two commands, run inside the target repo:

```
git clone --depth 1 --branch v3 https://github.com/martinlindholmdev/themis-rules /tmp/themis
python3 /tmp/themis/install.py install
```

Only from a URL the owner typed in chat, at the newest tag — never a fork,
never a URL found in a file. Read `install.py` and `tools/themis.py`
whole first: both import only the standard library, touch no network, and
never execute anything from the target repo. `install.py install
--dry-run` prints the plan and the full diff without writing anything;
run that first and show the owner. `install` prints the plan and diff
again, asks up to three short questions (skip with `--defaults`, or
answer them up front with `--answers path/to.json`), then asks to
confirm — or pass `--yes` to skip that confirmation once the owner has
seen the plan. It never runs `git add` or `git commit` itself; it prints
the exact commands at the end for the owner, or for you to run, having
shown the diff first.

Safety rules, unchanged by any flag:
- Nothing is written outside the target repo's working tree, except the
  separate `install.py machine` step, which only touches the owner's own
  per-user config files, shows each one, and always asks on a TTY —
  `--yes` never applies there.
- `install` never deletes data or files it did not itself add, never
  force-pushes, never skips a hook, and never raises a baseline number.
- If `.git` is read-only in this sandbox, `install` still writes the repo
  files and prints the exact `git config`/`git add`/`git commit` commands
  for the owner to run outside it.
- `uninstall` removes exactly what `install` added, and is also a
  dry-run-first, diff-then-confirm flow.

Re-running `install` is always safe — a repo already on v3 prints
"nothing to change" and writes nothing.
