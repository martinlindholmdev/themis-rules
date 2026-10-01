# Contributing

This repository obeys its own rules: `tools/themis.py` is installed here
and a pre-commit hook runs it on every commit. The rules are in
[RULES.md](RULES.md); the layout is in [AGENTS.md](AGENTS.md).

Before sending a change, both of these must pass:

```
python3 -m unittest discover -s tests
python3 tools/themis.py check
```

`tools/themis.py` is copied byte for byte into every repository that
installs Themis, so a behaviour change there is an upgrade for all of them
and needs a test in `tests/`. It stays under 800 lines and standard-library
only: no network, no dependencies. `install.py` and `install_plan.py` run
only in this repository and keep to the same limits: no file over 800
lines, no function over 100.

Small, focused changes reviewed by a different model are preferred over
large ones; rule 10 in `RULES.md` says what counts as small.

Security-relevant changes (the secret patterns, what `install.py` writes or
executes, the machine-level pointer text) need the care described in
[SECURITY.md](SECURITY.md). Say so in the pull request.
