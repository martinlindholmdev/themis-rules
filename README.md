<p align="center"><img src="assets/themis-icon-light.svg" alt="Themis mark: a 3D meander" width="96"></p>
<h1 align="center">Themis</h1>
<p align="center">
<a href="https://github.com/martinlindholmdev/themis-rules/actions/workflows/ci.yml"><img src="https://github.com/martinlindholmdev/themis-rules/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/martinlindholmdev/themis-rules" alt="License"></a>
</p>

**Named for the Greek goddess of law and order. Built to keep AI-written code in line.**

Themis is a set of repository rules for coding agents, with a small Python checker that enforces part of them. The rules and the checker live in your repository. There is no hosted service and no third-party Python dependency.

A Git hook runs the checker before each commit. An optional CI job runs it again on proposed changes. When the owner sets a test command, a second CI job runs the project's own tests on the committed tree.

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
| File and function size | Refuses a file over 800 lines or a function over 100. Code already over a limit is recorded in a baseline that may shrink, never grow. |
| Comment style | Flags history-style comments, such as a date, "used to", "previously", "reviewer" or "this session". |
| File header | Refuses a new source file whose opening comment or docstring lacks Purpose, Entry points, Invariants and Never change without a decision, each with real text. Existing files are not checked. |
| Secrets | Refuses added lines that match common credential patterns. |
| Acceptance gate | When the owner sets a test command: runs it on the committed tree and fails on an error, no test count, a count below the floor or too many skips. Without a command it is off, and `status` reports tests as honour-system. |

Function length is measured for Python, Rust, Go, Swift, Kotlin, Java, C# and JS/TS. Other files get the file limit, the comment check and the secret check.

The other rules in [RULES.md](RULES.md) hold only because the agent reads them. So do the parts of rules 2 and 3 the checks leave out: whether a header is true, and whether comments are in the present tense.

Secret detection is a pattern match, not a complete scanner. Run a dedicated tool such as [gitleaks](https://github.com/gitleaks/gitleaks) alongside it.

A local hook can be skipped, so a protected CI job is the backstop. Themis is not a code reviewer or a workflow framework.

## Install

Requires git and Python 3.9 or later. From inside the target repository:

```
THEMIS_SRC=$(mktemp -d)
git clone --depth 1 --branch v3.5.2 https://github.com/martinlindholmdev/themis-rules "$THEMIS_SRC"
git -C "$THEMIS_SRC" describe --tags --exact-match  # must print v3.5.2
python3 "$THEMIS_SRC/install.py" install
```

The installer prints its plan and writes nothing until you confirm. It makes no network requests, executes nothing from the target repository and never runs `git commit`.

Or tell your agent: "Install Themis from github.com/martinlindholmdev/themis-rules at tag v3.5.2." The agent's instructions, and the steps to update or uninstall, are in [docs/install.md](docs/install.md).

The checker is committed with the repository. Activate the hook in each fresh clone with `git config core.hooksPath tools/hooks`. A repository that uses husky, lefthook or the pre-commit framework uses that tool's own install step instead.

`AGENTS.md` is read natively by most agents, and `install.py` adds what the others need. Aider skips Git hooks by default; install writes an Aider config that turns hook checking on. The supported agents, with sources, are in [docs/frameworks.md](docs/frameworks.md).

## Daily use

- `python3 tools/themis.py status` shows the installed version, the hook, whether a workflow runs the checker and the gate, whether tests are honour-system, and what is not measured. It reports only what it can see in the clone.
- `python3 tools/themis.py check` measures the whole tree. `check --staged` is what the hook runs.
- `python3 tools/themis.py rebaseline` lowers the recorded sizes to the current ones. It refuses to raise any number.
- `python3 tools/themis.py gate` runs the project's tests on a clean committed tree, once a test command is set (`install --test-command "python3 -m pytest"`). `gate --record` raises the floor to the number of tests that ran. Lowering it is the owner's own commit: `gate --lower N --reason "..."`.

## CI and the test gate

When the repository has a GitHub remote, `install` offers `.github/workflows/themis.yml`. Its job, `themis`, runs `check --range <base>...<head>` on pull requests, pushes and merge queue entries. It runs the base commit's copy of the checker, so a change cannot rewrite the checker to pass itself. When the base commit has no checker, the change that introduces Themis runs its own copy and needs the owner's review.

When the owner sets a test command, `install` also writes `.github/workflows/themis-gate.yml`, once. Its job, `themis-gate`, runs `gate --range` with the base commit's checker. The file belongs to the owner from then on: add the toolchain and dependency steps the tests need above the gate step. Themis never overwrites it.

Mark both jobs as required status checks in the branch protection settings; without that they are advice, not a backstop. Give `themis-gate` no secrets and no self-hosted runner, because it runs the proposed code's tests. `status` cannot see branch protection and says so.

## Read more

- [docs/checks.md](docs/checks.md): what each check measures, its configuration and the baseline.
- [docs/install.md](docs/install.md): installing, upgrading and uninstalling.
- [docs/frameworks.md](docs/frameworks.md): support for 17 coding agents.
- [SECURITY.md](SECURITY.md): what Themis does and never does, and how to protect the workflows.
- [CONTRIBUTING.md](CONTRIBUTING.md): changing Themis itself.

## License

MIT. See [LICENSE](LICENSE).

<sub>The mark is a meander, one unbroken line that turns only at right angles.</sub>
