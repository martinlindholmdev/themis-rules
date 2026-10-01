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

From inside the target repository:

```
THEMIS_SRC=$(mktemp -d)
git clone --depth 1 --branch v3.1 https://github.com/martinlindholmdev/themis-rules "$THEMIS_SRC"
git -C "$THEMIS_SRC" describe --tags --exact-match  # must print v3.1
python3 "$THEMIS_SRC/install.py" install
```

Or tell your agent: "Install Themis from
github.com/martinlindholmdev/themis-rules at tag v3.1."

The installer reads the repository, prints the plan and writes nothing
until you confirm. It makes no network requests, executes nothing from the
target repository and never runs `git commit`. The agent's instructions and
the safety rules are in [docs/install.md](docs/install.md).

A refused commit looks like this:

```
$ git commit -m "add retry logic"
retry.py: 816 lines, over the 800-line limit. Split it; do not raise the baseline.
retry.py: function retry is 816 lines, over the 100-line limit. Split it; do not raise the baseline.
themis: FAIL, 2 problem(s)
```

## What is enforced

The checker, `tools/themis.py`, runs on every commit and refuses it when:

- a file is over 800 lines, or a function is over 100 lines, or either has
  grown past its recorded baseline. Function length is measured for
  Python, Rust, Go, Swift, Kotlin, Java, C# and JS/TS (`.js .jsx .mjs .cjs
  .ts .tsx`); other extensions get the file limit, the comment check and
  the secret check, and `status` lists what it cannot measure (C and C++
  among them);
- a comment matches a history pattern (a date, "used to", "previously",
  "reviewer", "this session", "DO NOT MERGE") beyond its baseline count.
  For the seven languages comments are read string- and nesting-aware, and
  quoted text, backtick spans, URLs and fenced code are ignored; "used to"
  counts after a subject pronoun or as "used to be", and "previously" does
  not count before a past participle;
- a staged line matches a private key, a provider-shaped API token, a long
  bearer token, or a password, secret or token assignment, unless the line
  carries `themis: allow-secret`.

Anonymous functions outside any function are measured: one with a binding
name runs first line to last, an unnamed one counts its own lines and each
function inside it is measured separately. A long block that is not
recognised as a function is reported as a note. In Rust, the lines of a
`#[cfg(test)] mod` are not counted against the file limit (reported as "N
lines (P production + T test)"), and a test module over 800 lines is
itself refused. A file whose first ten comment lines carry a generated-code
marker is skipped for size, function and history checks only if its
version at the base commit already carried one; the secret scan never
skips a file.

The two limits, the marker text and the secret patterns are fixed in the
checker. `themis.json` can add history words and file extensions, exempt
path prefixes such as test fixtures, tighten a limit per extension with
`"limits": {".ts": {"file": 500, "function": 80}}` (a value above the hard
limit is ignored), and exempt single files with `"exempt_files": {"path":
"reason"}`, which skips the size, function and history checks only. The
baseline only ever goes down:
a file over a limit is split, and `rebaseline` refuses to raise any
number. A matched secret is reported by file and line; the matched text is
never printed.

## What is not enforced

The remaining rules in [RULES.md](RULES.md) hold only because the agent
reads them: the file header convention, searching for an existing helper
before writing one, no code for a case that cannot happen, fewer and more
meaningful tests, the plan-then-review workflow and the decision log.

The secret check recognises common key and token formats. It is not a
complete secret scanner; run a dedicated tool such as
[gitleaks](https://github.com/gitleaks/gitleaks) alongside it. Themis is
not a code reviewer or a workflow framework either.

## How it works

Three standard-library Python files are copied into the target repository,
not linked, so they keep working for anyone who clones it later, with no
install step and no network access: `tools/themis.py` (git, config and
reporting), `tools/themis_lang.py` (function length, comments and history
matching for the seven languages) and `tools/themis_scan.py` (the scanner).
They must sit side by side; a missing one ends the run with one line. The
checker has three commands:

- `check` measures every recognised source file against
  `themis-baseline.json`. `--staged` measures the staged files and the
  staged diff (what the pre-commit hook runs). `--range A...B` measures the
  tree at `B` and scans the diff `A..B` for secrets (what CI runs).
- `status` reports the installed version, which hook mechanism is wired up,
  and which file extensions are and are not measured. It prints an
  `enforcement` line: blocking when the hook is on and a CI workflow that
  runs the checker exists, local hook only (skippable with `--no-verify`)
  when only the hook is on, otherwise advisory. It lists generated files
  and `exempt_files` with their reasons. A repository with no recognised
  source files fails rather than reporting clean.
- `rebaseline` lowers the recorded sizes to today's and drops entries for
  files that shrank under the limit or were deleted. It refuses, writing
  nothing, if that would raise any number or add any entry. Entries for the
  seven languages live in the baseline's `lang` section. A new or higher
  `lang` entry is accepted only if measuring the base commit's version of
  that file gives at least that number, so new code cannot be recorded as
  existing. An install or upgrade computes the `lang` section from HEAD's
  committed content only and shows it in the plan.

`install.py` stays in this repository and is never copied. It writes the
three checker files, the hook, `themis.json` and the rules block in `AGENTS.md`; wires
the pre-commit hook for plain git, husky, lefthook or the pre-commit
framework; offers the per-agent adapters and the CI workflow; upgrades an
agent-rules v1 or v2 install in place; and removes everything it added with
`uninstall`.

## Agent support

`AGENTS.md` is read natively by most agents. Where one needs more, such as a
one-line `CLAUDE.md` or a config key that turns on hook verification,
`install.py` adds it. Of the 17 agents checked, at least one (Aider) skips a
local git hook by default, and several document a flag or mode that bypasses
their own permission layer; the CI workflow covers those. The full matrix,
with sources and check dates, is in [docs/frameworks.md](docs/frameworks.md).

## CI backstop

When a GitHub remote is present, `install` offers
`.github/workflows/themis.yml`: a job named `themis` that runs
`themis.py check --range <base>...<head>` on every pull request and push.
It runs the base commit's own copies of the three checker files, so a
change cannot rewrite the checker to pass itself; when the base commit has
no checker at all, the first introduction runs the checked-out copy, so
that first change needs the owner's own review. A branch with no earlier commit
is ranged from git's empty tree, so every line is still scanned for
secrets. Mark the job a required status check in the repository's branch
protection settings; without that it is advice, not a backstop. See
[SECURITY.md](SECURITY.md) for protecting the workflow file itself.

## Updating and uninstalling

Re-run `install` from a newer tag, with the same commands as above, to
update the checker, the hook and the rules block in place. A repository
that is already current prints "nothing to change" and writes nothing.
`python3 "$THEMIS_SRC/install.py" uninstall` removes exactly what `install`
added and prints the `git add` and `git commit` commands for the result.

## Name

Themis is the Greek goddess of order and law. The mark is a meander, one
unbroken line that turns only at right angles.

## License

MIT. See [LICENSE](LICENSE).
