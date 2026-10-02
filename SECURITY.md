# Security

## Reporting

Report a security issue privately through the "Report a vulnerability"
button on this repository's Security tab, not as a public issue. Include
the file, the input that triggers it, and what you expected instead. Themis
has no release SLA; expect an acknowledgement, not a guaranteed fix date.

## What Themis does

- `tools/themis.py`, `tools/themis_lang.py`, `tools/themis_scan.py` and
  `tools/themis_gate.py` are standard-library Python only: no network access,
  no third-party dependencies. `check` and `status` write nothing;
  `rebaseline` writes the baseline and can only lower it. `gate` writes a
  receipt under `.git/themis/`; `gate --record` and `gate --lower` write
  `themis.json`, and `--lower` appends a line to the decision log.
- It scans staged diffs and commit ranges for secret-shaped strings
  (private keys, provider-shaped API tokens, long credential assignments)
  and refuses the commit. It is a pattern match, not an entropy model or a
  provider lookup: it misses secrets that do not match its patterns and
  occasionally flags something that is not one. Mark a confirmed false
  positive with `themis: allow-secret` on that line.
- A matched secret is reported by file and line number. The matched text is
  never printed, logged or included in any message.
- `exempt_files` in `themis.json` is the owner's bypass of the size,
  function and history checks for the files it names. It never skips the
  secret scan, and the list enforced is the one already committed at the
  base commit, so a change cannot exempt itself.
- A generated-file marker (in a file's first ten comment lines) exempts the
  file from the size, function and history checks only when the version of
  that file at the base commit carried a marker too. A marker added to an
  existing, new or renamed file is reported and the file is measured. The
  secret scan never skips a file.
- A new or raised `lang` baseline entry is accepted only when the base
  commit's own version of the file measures at least that number.
- `install.py` never executes code from the repository it installs into:
  not an old checker it replaces, not a hook file it edits around, not the
  test command it writes into `themis.json` (it reads root-level file names
  only, to print a suggestion). It never runs `git commit`; it prints the
  command. It makes no network requests.
- The acceptance gate (`gate`) does run the test command the owner set under
  `test` in `themis.json`, and only then: with no `test` section nothing runs.
  The command is an argv list run without a shell and with no stdin; its
  settings are read from the base commit, so a change cannot edit its own gate;
  and the committed tree must equal the working tree before and after the run.
  The local hook, `tools/hooks/pre-push`, runs project code exactly as the
  owner's own test command would, once git is pointed at `tools/hooks` and a
  `test` section is committed.
- `install.py machine` writes a short, read-only instruction (read
  `AGENTS.md`, offer once, never run anything) into up to eight per-user
  agent config files, and only after the owner confirms each file on a TTY.
  It is not a mechanism for unattended changes to anyone's machine.

## What Themis never does

- Sends anything over the network.
- Executes code from the target repository during install. Even the
  installer's final `status` step runs the installer's own copy of the
  checker, after confirming byte for byte that the copy it wrote matches it.
- Writes `themis-gate.yml` more than once. It is written when a test command is
  set and the file does not exist; an existing file is never replaced.
- Writes outside the target repository's working tree, except the machine
  step above (confirmed file by file) and a worktree's shared hook file,
  which lives in the main repository's `.git` directory.
- Force-pushes, deletes data, or skips a hook on your behalf.
- Raises a size baseline, for anyone. `rebaseline` refuses to raise any
  number, and the hook and the CI range check refuse a commit that does.
  The one addition allowed is a `lang` entry that the base commit's own
  content already measures at least as large; it records what existed.

## Trust boundary

The local checker files, git and python are trusted: anything that can
edit them can edit the check. The independent boundary is the CI backstop
running the protected base copies of the checker files, so a change cannot
weaken the check it is judged by. The gate's local receipt is not a trust
anchor: anyone with the checkout can forge it, so CI never reads it. The gate
protects the command, patterns and floor; edits to the tests themselves, to
`pytest.ini`, `conftest.py`, skip markers, discovery or coverage exclusions
and to the workflows need review by a person.

## For repositories that install Themis

The CI backstop (`.github/workflows/themis.yml`) only protects a branch
that is itself protected, and a pull request can edit the workflow file in
the same change it is meant to check. Mark the `themis` job a required
status check, and add a `CODEOWNERS` entry for `.github/workflows/` that
requires review from someone other than the author, so a workflow change
needs a second set of eyes before it can weaken what the backstop checks.

The gate workflow (`.github/workflows/themis-gate.yml`, job `themis-gate`) runs
the project's tests on the proposed code, so a pull request's own tests run in
it. Give that job no secrets, no self-hosted runner and `contents: read`
only, as the generated file does; mark it a required status check as well
(Themis cannot see branch protection and `status` says so); and cover the
file with the same `CODEOWNERS` entry. The owner adds toolchain steps to it;
Themis never overwrites it.
