<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/themis-icon-dark.svg"><img src="assets/themis-icon-light.svg" alt="Themis mark: a 3D meander" width="96"></picture></p>
<h1 align="center">Themis</h1>
<p align="center">
<a href="https://github.com/martinlindholmdev/themis-rules/actions/workflows/ci.yml"><img src="https://github.com/martinlindholmdev/themis-rules/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/martinlindholmdev/themis-rules" alt="License"></a>
</p>

**Named for the Greek goddess of law and order. Built to keep AI-written code in line.**

Themis gives AI coding agents a shared set of repository rules, backed by a small Python checker. A Git hook checks file and function size, flags history-style comments, requires a header on every new source file, and catches common secret patterns before a commit. An optional CI check provides a second check on proposed changes. Set a test command and a gate runs your own tests on the committed tree in CI and fails on errors, zero tests, too few tests or too many skips.

The rules and checker live in your repository. No hosted service and no third-party Python dependencies.

A refused commit looks like this:

```
$ git commit -m "add retry logic"
retry.py: 816 lines, over the 800-line limit. Split it; do not raise the baseline.
retry.py: function retry is 816 lines, over the 100-line limit. Split it; do not raise the baseline.
themis: FAIL, 2 problem(s)
```

## What it checks

| Check | What it does |
|---|---|
| File and function size | Checks size limits and existing baseline allowances. |
| Comment style | Flags supported history-style patterns in comments. |
| File header | Refuses a new source file that does not open with a comment or docstring holding Purpose, Entry points, Invariants and Never change without a decision, each with real text. Existing files are not checked. |
| Secrets | Rejects added lines matching common credential patterns. |
| Acceptance gate | When the owner sets a test command: runs it on the exact committed tree and fails on an error, no test count, a count below the floor or too many skips. Off, and reported as honour-system, until a command is set. |

The other rules in [RULES.md](RULES.md) hold only because the agent reads them, as do the parts of rules 2 and 3 the checks leave out: whether a header is true, and whether comments are in the present tense. Secret detection is pattern-based and is not a complete scanner; run a dedicated tool such as [gitleaks](https://github.com/gitleaks/gitleaks) alongside it. A local hook can be skipped, so protected CI is the backstop. Themis is not a code reviewer or a workflow framework. Full behaviour is in [docs/checks.md](docs/checks.md).

## Install

Requires git and Python 3.9 or later. From inside the target repository:

```
THEMIS_SRC=$(mktemp -d)
git clone --depth 1 --branch v3.4 https://github.com/martinlindholmdev/themis-rules "$THEMIS_SRC"
git -C "$THEMIS_SRC" describe --tags --exact-match  # must print v3.4
python3 "$THEMIS_SRC/install.py" install
```

The installer prints the plan and writes nothing until you confirm. It makes no network requests, executes nothing from the target repository and never runs `git commit`.

Or tell your agent: "Install Themis from github.com/martinlindholmdev/themis-rules at tag v3.4." The agent's instructions are in [docs/install.md](docs/install.md).

When the local hook is enabled, it checks staged changes before a commit. The checker is committed with the repository; activate the local hook in each fresh clone with `git config core.hooksPath tools/hooks`. A repository wired through husky, lefthook or the pre-commit framework uses that tool's own install step instead.

## Daily use

- `python3 tools/themis.py status` shows the installed version, the wired hook, whether a workflow runs the checker (and the gate), whether tests are honour-system, and what is not measured. It reports only what it can see in the clone.
- `python3 tools/themis.py check` measures the whole tree. `check --staged` is what the hook runs.
- `python3 tools/themis.py rebaseline` lowers the recorded sizes to today's. It refuses to raise any number.
- `python3 tools/themis.py gate` runs the project's tests once a test command is set (`install --test-command "python3 -m pytest"`), on a clean committed tree. `gate --record` raises the floor to the tests that ran; lowering it is the owner's own commit, `gate --lower N --reason "..."`.

## Languages and agents

Function measurement for Python plus seven language families: Rust, Go, Swift, Kotlin, Java, C# and JS/TS (`.js .jsx .mjs .cjs .ts .tsx`). Other extensions get the file limit, the comment check and the secret check.

`AGENTS.md` is read natively by most agents, and `install.py` adds what the others need. The documented integrations, with sources, are in [docs/frameworks.md](docs/frameworks.md). Aider skips a local git hook by default; install creates the Aider config that turns hook checking on when it detects Aider or is given `--agents aider`.

## CI

When a GitHub remote is present, `install` offers `.github/workflows/themis.yml`: a job named `themis` that runs `check --range <base>...<head>` on every pull request and push. It runs the base commit's own copies of the four checker files, so a change cannot rewrite the checker to pass itself. When the base commit has no checker at all, the first introduction runs the checked-out copy, so that first change needs the owner's own review. Mark the job a required status check in the branch protection settings; without that it is advice, not a backstop. [SECURITY.md](SECURITY.md) covers protecting the workflow file.

When the owner sets a test command, `install` also writes `.github/workflows/themis-gate.yml`, once: a job named `themis-gate` that runs `gate --range` on the base commit's checker. It is the owner's file from then on. Add the toolchain and dependency steps your tests need above the gate step; Themis never overwrites it, and a re-run or an upgrade only prints how this release's template differs. Make the `themis-gate` job a required check too, and give it no secrets and no self-hosted runner, because it runs your tests on the proposed code. `status` cannot see branch protection and says so. [docs/checks.md](docs/checks.md) has the details.

## Updating and uninstalling

Re-run `install` from a newer tag to update the checker, the hook and the rules block in place. An upgrade from v3 to v3.3 keeps your `themis.json` settings, adds `header_exempt_prefixes` and the fourth checker file; it never adds a `test` key or a gate workflow you did not ask for, and a gate workflow you have edited is left as it is. `python3 "$THEMIS_SRC/install.py" uninstall` removes exactly what `install` added and prints the commands to commit the result.

[CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md)

## License

MIT. See [LICENSE](LICENSE).

<sub>The mark is a meander, one unbroken line that turns only at right angles.</sub>
