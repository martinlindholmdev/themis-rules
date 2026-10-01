# Contributing

This repository obeys its own rules (see `RULES.md` and `AGENTS.md`).
`tools/themis.py` is installed here too, and a pre-commit hook runs it on
every commit.

Before sending a change:

```
python3 -m unittest discover -s tests
python3 tools/themis.py status
```

Both must be clean.

`tools/themis.py` is copied byte for byte into every repository that
installs Themis, so a behaviour change there is an upgrade for all of them
and needs a test in `tests/`, not only a passing `status`. It stays under
800 lines and standard-library only: no network, no dependencies.
`install.py` (the commands, the uninstall planners and the machine-level
writers) and `install_plan.py` (the install plan-building and shared
mechanics) each stay under 800 lines with no function over 100, and
run only in this repository.

Small, focused changes reviewed by a different model are preferred over
large ones. `RULES.md` rule 10 says what counts as small.

Security-relevant changes (the secret patterns, what `install.py` writes or
executes, the machine-level pointer text) need the care described in
`SECURITY.md`. Say so in the pull request.
