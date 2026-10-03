# Contributing

This repository obeys its own rules. The four checker files are installed
here, and a pre-commit hook runs the checker on every commit. The rules are
in [RULES.md](RULES.md); the layout is in [AGENTS.md](AGENTS.md).

Before sending a change, both of these must pass:

```
python3 -m unittest discover -s tests
python3 tools/themis.py check
```

`tools/themis.py`, `tools/themis_lang.py`, `tools/themis_scan.py` and
`tools/themis_gate.py` are copied byte for byte into every repository that
installs Themis. A behaviour change in any of them is an upgrade for all of
those repositories and needs a test in `tests/`. Each file stays under 800
lines and uses the standard library only: no network, no dependencies.

`install.py`, `install_plan.py` and `install_gate.py` run only in this
repository. They keep to the same limits: no file over 800 lines, no
function over 100.

Prefer small, focused changes reviewed by a different model. Rule 10 in
`RULES.md` says what counts as small.

Security-relevant changes (the secret patterns, what `install.py` writes or
executes, the machine-level pointer text) need the care described in
[SECURITY.md](SECURITY.md). Say so in the pull request.
