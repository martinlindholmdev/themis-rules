<img src="assets/themis-wordmark.svg" alt="Themis" width="280">

# Themis

Themis is a set of rules and a git hook that enforce code size, comment
style and secret hygiene in repositories written by AI coding agents.

**What you get**
- A size ratchet: files and functions may only shrink from today's
  sizes, never grow past a hard limit, checked at commit time.
- A comment-history check: a comment must describe the code as it is,
  not narrate how it got there.
- A secret scanner on every staged diff and every CI-checked commit
  range — no network call, no API key, the matched text never printed.
- One install command, for a person or an agent: it reads the repo,
  shows the plan and the full diff, and writes nothing until confirmed.
- A CI workflow as a backstop for whatever a local hook cannot reach: a
  cloud agent, a skipped hook, a fresh clone with no hook wired up yet.

**Install**

Tell your agent: "Install Themis from
github.com/martinlindholmdev/themis-rules at tag v3."

By hand, from inside the target repo:
```
git clone --depth 1 --branch v3 https://github.com/martinlindholmdev/themis-rules /tmp/themis
python3 /tmp/themis/install.py install
```

See `INSTALL.md` for the safety rules both paths follow — chiefly: only
from a URL you typed, plan and diff shown before anything is written.

**A refused commit**
```
$ git commit -m "add retry logic"
retry.py: 816 lines, over the 800-line limit. Split it; do not raise the baseline.
retry.py: function retry is 816 lines, over the 100-line limit. Split it; do not raise the baseline.
themis: FAIL, 2 problem(s)
```

**Framework support**

Themis's rules file (`AGENTS.md`) is read natively by most agents. Where
an agent needs something extra — a one-line `CLAUDE.md`, a config key
that turns on hook verification, a warning that another file would
otherwise take priority — `install.py` adds it. Across the 17 agent
surfaces checked, at least one (Aider) skips a local git hook by
default, and a handful of others document a flag or mode that can bypass
their own permission layer; the CI workflow is what covers those. Full
matrix, sources and check dates in
[`docs/frameworks.md`](docs/frameworks.md).

## How it works

`tools/themis.py` is a single standard-library Python file, vendored
(copied) into the target repo rather than linked, so it keeps working
with no install step for anyone who later clones that repo and no
network access ever. It has three jobs:

- `check` — with no flag, measures every recognised source file in the
  working tree against `themis-baseline.json`; `--staged` measures only
  staged files plus the staged diff (what the pre-commit hook runs);
  `--range A...B` measures the whole tree at `B` and scans `git diff
  A...B` for secrets (what CI runs).
- `status` — reports, honestly, what is installed, what hook mechanism
  (if any) is wired up, and which file extensions are and are not
  measured.
- `rebaseline` — owner-only: records today's sizes as the new ceiling.
  Never run by an agent, never run automatically except once, by
  `install.py`, on a brand-new install.

`install.py` lives only in this repo — it is never copied into a target
repo. It writes the checker, the hook, `themis.json`, and the `RULES.md`
block in `AGENTS.md`; wires a pre-commit hook the way whichever hook
manager is present expects (plain git, husky, lefthook, or the
pre-commit framework); offers the per-framework adapters and the CI
workflow described below; and can upgrade an existing agent-rules v1/v2
install in place, or remove everything it added with `uninstall`.

## What is enforced vs what relies on the agent

**Enforced by the checker, mechanically, every commit:**
- No tracked file over 800 lines, no function over 100 — against a
  baseline that may only shrink.
- No comment matching a fixed list of history-narrating patterns (a
  date, "previously", "used to", "reviewer", and so on), past its
  baseline count.
- No staged line matching a private key, a provider-shaped API token, a
  long bearer token, or a password/secret/token assignment — unless
  marked `themis: allow-secret` on that line.

**Relies on the agent actually reading `AGENTS.md`:** the file-header
convention, searching for an existing helper before writing a new one,
not adding code for a case that cannot happen, writing fewer and more
meaningful tests, the plan-then-review workflow, and the decision log.
None of this is mechanically checkable; Themis only enforces the three
things above. The full rule text is in `RULES.md`.

## Frameworks

See [`docs/frameworks.md`](docs/frameworks.md) for the complete,
per-agent breakdown: how each one reads repo rules, its user-level
config path, whether it runs a real shell and git, whether it is
documented to skip a hook, its own permission layer, and what Themis
does (if anything) for it — plus copy-paste hook-skip guard snippets
where one exists.

## CI backstop

Where a GitHub remote is detected, `install` offers
`.github/workflows/themis.yml`: a fixed job named `themis`, full history
(`fetch-depth: 0`), running `themis.py check --range
<base>...<head>` on a pull request and a whole-tree `themis.py check` on
a push (a brand-new branch has no earlier commit to range from). No
`paths:` filter, so it never silently stops running. Mark it a required
status check in the repository's branch protection settings — that is
what actually makes it a backstop rather than an advisory.

## Updating and uninstalling

Re-running `install` against a newer tag updates the checker, the hook
and the rules block in place; a repo already current prints "nothing to
change" and writes nothing. `python3 tools/themis.py status` reports the
installed version at any time. `python3 /tmp/themis/install.py
uninstall` removes exactly what `install` added — the checker, the
hook wiring, the rules block, the adapters, the CI workflow — and prints
the `git add`/`git commit` commands for the result, same as `install`
does.

## FAQ

**Does Themis run any of my code?** No. `install.py` never executes
anything from the target repo — not an old checker it is replacing, not
a hook file it edits around — and it never calls `git commit` itself.

**Does it phone home?** No. Neither `tools/themis.py` nor `install.py`
makes a network request.

**What if I need a bigger file, just this once?** The baseline is
owner-only and local: `python3 tools/themis.py rebaseline`, reviewed and
committed like any other change. An agent cannot raise it.

**What if my repo has no recognised source files?** `status` and `check`
both fail loudly on "0 files measured" rather than reporting a quiet,
misleading "clean" — check `themis.json`'s `extra_extensions`.

**Can I lower the two hard limits (800 lines, 100 lines)?** No — those
two numbers, the marker text, and the secret pattern list are fixed in
`tools/themis.py` itself; changing them is a decision for this project,
not a per-repo config value.

## License

MIT — see [`LICENSE`](LICENSE).

## About the name

Themis is the Greek goddess of order, law and fair judgment. The mark
above is a meander (a Greek key): one unbroken line that only turns at
right angles, among the oldest Greek symbols for order.

---

Copyright (c) 2026 Sisyfos Studios — named for Sisyphus, who rolls the
stone back up the hill every day.
