# Contributing

This repo obeys its own rules (see `RULES.md` and `AGENTS.md`): `tools/themis.py`
is installed here too, and a pre-commit hook runs it on every commit.

Before sending a change:

```
python3 -m unittest discover -s tests
python3 tools/themis.py status
```

Both must be clean. If you touch `tools/themis.py` itself, remember it is
vendored byte-for-byte into every repo that installs Themis — a behaviour
change there is an upgrade for all of them, so it needs a test in
`tests/`, not just a passing `status`.

Scope: `tools/themis.py` stays under 600 lines and standard-library only
(no network, no dependencies — it is copied into other people's repos
verbatim). `install.py` stays under 800 lines, no function over 100
lines, and runs only in this repo, never vendored.

Small, focused changes reviewed by a different model are preferred over
large ones. See `RULES.md` rule 10 for what counts as small.

Security-relevant changes (the secret patterns, what `install.py` writes
or executes, the machine-level pointer text) need the extra care in
`SECURITY.md` — say so in the pull request.
