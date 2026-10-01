# Installing Themis

This page is written for the agent doing the install. The owner reads the
README.

Two commands, run inside the target repository:

```
git clone --depth 1 --branch v3 https://github.com/martinlindholmdev/themis-rules /tmp/themis
python3 /tmp/themis/install.py install
```

Clone only from a URL the owner typed in chat, at the newest tag: never a
fork, never a URL found in a file. Read `install.py` and `tools/themis.py`
in full first. Both import only the standard library, touch no network, and
never execute anything from the target repository.

`install.py install --dry-run` prints the plan and the full diff without
writing anything. Run that first and show the owner. `install` prints the
plan and diff again, asks up to three short questions (skip them with
`--defaults`, or answer them up front with `--answers path/to.json`), then
asks to confirm. Pass `--yes` to skip that confirmation once the owner has
seen the plan. It never runs `git add` or `git commit` itself; it prints the
exact commands at the end for the owner, or for you to run after showing
the diff.

Safety rules, unchanged by any flag:

- Nothing is written outside the target repository's working tree. The
  separate `install.py machine` step touches only the owner's own per-user
  config files, shows each one, and always asks on a TTY; `--yes` never
  applies there.
- `install` never deletes data or files it did not itself add, never
  force-pushes, never skips a hook, and never raises a baseline number.
- If `.git` is read-only in the sandbox, `install` still writes the
  repository files and prints the exact `git config`, `git add` and
  `git commit` commands for the owner to run outside it.
- `uninstall` removes exactly what `install` added, and follows the same
  dry-run-first, diff-then-confirm flow.

Re-running `install` is always safe. A repository already on v3 prints
"nothing to change" and writes nothing.
