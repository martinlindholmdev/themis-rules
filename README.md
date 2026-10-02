<p align="center"><img src="assets/themis-tile.svg" alt="Themis mark: a meander" width="96"></p>
<h1 align="center">Themis</h1>
<p align="center">
<a href="https://github.com/martinlindholmdev/themis-rules/actions/workflows/ci.yml"><img src="https://github.com/martinlindholmdev/themis-rules/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/martinlindholmdev/themis-rules" alt="License"></a>
</p>

**Named for the Greek goddess of law and order. Built to keep AI-written code in line.**

Themis gives AI coding agents a shared set of repository rules, backed by a small Python checker. A Git hook checks file and function size, flags history-style comments, and catches common secret patterns before a commit. An optional CI check provides a second check on proposed changes.

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
| Secrets | Rejects added lines matching common credential patterns. |

The other rules in [RULES.md](RULES.md) hold only because the agent reads them. Secret detection is pattern-based and is not a complete scanner; run a dedicated tool such as [gitleaks](https://github.com/gitleaks/gitleaks) alongside it. A local hook can be skipped, so protected CI is the backstop. Themis is not a code reviewer or a workflow framework. Full behaviour is in [docs/checks.md](docs/checks.md).

## Install

Requires git and Python 3.9 or later. From inside the target repository:

```
THEMIS_SRC=$(mktemp -d)
git clone --depth 1 --branch v3.2 https://github.com/martinlindholmdev/themis-rules "$THEMIS_SRC"
git -C "$THEMIS_SRC" describe --tags --exact-match  # must print v3.2
python3 "$THEMIS_SRC/install.py" install
```

The installer prints the plan and writes nothing until you confirm. It makes no network requests, executes nothing from the target repository and never runs `git commit`.

Or tell your agent: "Install Themis from github.com/martinlindholmdev/themis-rules at tag v3.2." The agent's instructions are in [docs/install.md](docs/install.md).

When the local hook is enabled, it checks staged changes before a commit. The checker is committed with the repository; activate the local hook in each fresh clone with `git config core.hooksPath tools/hooks`. A repository wired through husky, lefthook or the pre-commit framework uses that tool's own install step instead.

## Daily use

- `python3 tools/themis.py status` shows the installed version, the wired hook, whether CI also runs the checker, and what is not measured.
- `python3 tools/themis.py check` measures the whole tree. `check --staged` is what the hook runs.
- `python3 tools/themis.py rebaseline` lowers the recorded sizes to today's. It refuses to raise any number.

## Languages and agents

Function measurement for Python plus seven language families: Rust, Go, Swift, Kotlin, Java, C# and JS/TS (`.js .jsx .mjs .cjs .ts .tsx`). Other extensions get the file limit, the comment check and the secret check.

`AGENTS.md` is read natively by most agents, and `install.py` adds what the others need. The documented integrations, with sources, are in [docs/frameworks.md](docs/frameworks.md). Aider skips a local git hook by default; install creates the Aider config that turns hook checking on when it detects Aider or is given `--agents aider`.

## CI

When a GitHub remote is present, `install` offers `.github/workflows/themis.yml`: a job named `themis` that runs `check --range <base>...<head>` on every pull request and push. It runs the base commit's own copies of the three checker files, so a change cannot rewrite the checker to pass itself. When the base commit has no checker at all, the first introduction runs the checked-out copy, so that first change needs the owner's own review. Mark the job a required status check in the branch protection settings; without that it is advice, not a backstop. [SECURITY.md](SECURITY.md) covers protecting the workflow file.

## Updating and uninstalling

Re-run `install` from a newer tag to update the checker, the hook and the rules block in place. `python3 "$THEMIS_SRC/install.py" uninstall` removes exactly what `install` added and prints the commands to commit the result.

[CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md)

## License

MIT. See [LICENSE](LICENSE).

<sub>The mark is a meander, one unbroken line that turns only at right angles.</sub>
