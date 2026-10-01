<p align="center"><img src="assets/themis-tile.svg" alt="" width="96"></p>
<h1 align="center">Themis</h1>
<p align="center">
<a href="https://github.com/martinlindholmdev/themis-rules/actions/workflows/ci.yml"><img src="https://github.com/martinlindholmdev/themis-rules/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/martinlindholmdev/themis-rules" alt="License"></a>
</p>

Themis is a set of rules and a pre-commit hook for repositories written by
AI coding agents. It enforces three things mechanically: file and function
size against a baseline that may only shrink, comments that describe the
code rather than its history, and no secrets in a staged diff. The rest of
the rules are text the agent reads.

## Install

From inside the target repository (a fixed `/tmp/themis` path collides when
more than one install runs at once, so use `mktemp -d`, and verify the tag
actually checked out before trusting anything in it):

```
THEMIS_SRC=$(mktemp -d)
git clone --depth 1 --branch v3 https://github.com/martinlindholmdev/themis-rules "$THEMIS_SRC"
git -C "$THEMIS_SRC" describe --tags --exact-match  # must print v3
python3 "$THEMIS_SRC/install.py" install
```

Or tell your agent: "Install Themis from
github.com/martinlindholmdev/themis-rules at tag v3."

The installer reads the repository, prints the plan (full content for the new files it owns, a hash summary for
the vendored ones, a diff for files that already exist), and
writes nothing until you confirm. It makes no network requests, executes
nothing from the target repository, and never runs `git commit`. The agent's
instructions and the safety rules are in [docs/install.md](docs/install.md).

A refused commit looks like this:

```
$ git commit -m "add retry logic"
retry.py: 816 lines, over the 800-line limit. Split it; do not raise the baseline.
retry.py: function retry is 816 lines, over the 100-line limit. Split it; do not raise the baseline.
themis: FAIL, 2 problem(s)
```

## What is enforced

The checker, `tools/themis.py`, runs on every commit and refuses it when:

- a file is over 800 lines or a function over 100, or either has grown past
  its recorded baseline;
- a comment matches one of the history patterns (a date, "previously",
  "used to", the word "reviewer") beyond its baseline count;
- a staged line matches a private key, a provider-shaped API token, a long
  bearer token, or a password, secret or token assignment, unless the line
  carries `themis: allow-secret`.

The two limits, the marker text and the secret patterns are fixed in the
checker and are not configured per repository. Only the owner raises the
baseline, with `python3 tools/themis.py rebaseline`, committed like any
other change. A matched secret is reported by file and line; the matched
text is never printed.

## What is not enforced

The remaining rules in [RULES.md](RULES.md) hold only because the agent
reads them: the file header convention, searching for an existing helper
before writing one, no code for a case that cannot happen, fewer and more
meaningful tests, the plan-then-review workflow and the decision log. Themis
checks none of these.

The secret check recognises common key and token formats. It is not a
complete secret scanner; for that, run a dedicated tool such as
[gitleaks](https://github.com/gitleaks/gitleaks) alongside it. Themis is also
not a code reviewer or a workflow framework: it enforces a small set of
rules and is meant to sit next to those tools.

## How it works

`tools/themis.py` is one standard-library Python file. It is copied into the
target repository, not linked, so it keeps working for anyone who clones
that repository later, with no install step and no network access. It has
three commands:

- `check` measures every recognised source file against
  `themis-baseline.json`. `--staged` measures the staged files and the
  staged diff (what the pre-commit hook runs). `--range A...B` (the flag's spelling) measures
  the tree at `B` and scans the direct, two-dot diff `A..B` for secrets (what
  CI runs).
- `status` reports what is installed, which hook mechanism is wired up, and
  which file extensions are and are not measured. A repository with no
  recognised source files fails loudly rather than reporting clean.
- `rebaseline` records the current sizes as the new ceiling. Owner only; a
  new install computes this once itself and shows it in the plan, rather
  than running the command as a separate, unshown step.

`install.py` stays in this repository and is never copied. It writes the
checker, the hook, `themis.json` and the rules block in `AGENTS.md`; wires
the pre-commit hook for plain git, husky, lefthook or the pre-commit
framework; offers the per-agent adapters and the CI workflow; upgrades an
agent-rules v1 or v2 install in place; and removes everything it added with
`uninstall`.

## Agent support

`AGENTS.md` is read natively by most agents. Where one needs more, such as a
one-line `CLAUDE.md` or a config key that turns on hook verification,
`install.py` adds it. Of the 17 agent surfaces checked, at least one (Aider)
skips a local git hook by default, and several document a flag or mode that
bypasses their own permission layer; the CI workflow covers those. The full
matrix, with sources and check dates, is in
[docs/frameworks.md](docs/frameworks.md).

## CI backstop

When a GitHub remote is present, `install` offers
`.github/workflows/themis.yml`: a job named `themis` that runs
`themis.py check --range <base>...<head>` on a pull request and the same
range check against the commit before the push on an ordinary push. A
brand-new branch has no earlier commit to range from, so git's own
empty-tree hash stands in as the base — the range still scans every line
of the tree for secrets, never falling back to a bare size/comment check
with no secret scan. Either way, it is always the *base* commit's own
copy of the checker that runs, so a change cannot rewrite the checker to
pass itself. Full history, no `paths:` filter. Mark it a required status
check in the repository's branch protection settings; that is what makes
it a backstop
rather than advice.

## Updating and uninstalling

Re-run `install` from a newer tag (the same `mktemp -d` clone above) to
update the checker, the hook and the rules block in place. A repository
that is already current prints "nothing to change" and writes nothing.
`python3 tools/themis.py status` reports the installed version.
`python3 "$THEMIS_SRC/install.py" uninstall` removes exactly what `install`
added and prints the `git add` and `git commit` commands for the result.

## Name

Themis is the Greek goddess of order and law. The mark is a meander, one
unbroken line that turns only at right angles.

## License

MIT. See [LICENSE](LICENSE).
