# Decisions

One line per decision this repo's owner made, for a reader who wasn't
there. `tools/themis.py` and `install.py` never raise this file, and
`uninstall` never touches it.

- The two hard limits (800 lines, 100-line functions) are the only
  ceiling for `tools/themis.py`; CONTRIBUTING.md's "stays well under 600"
  wording was a stale snapshot, not a separate rule — fixed to say 800.
- `install.py` split into `install.py` (the five CLI entry points) and
  `install_plan.py` (every plan-building function and shared mechanic),
  to land the path-safety, consent and presentation fixes from the
  2026-10-01 security reviews without breaking the 800-line hard limit;
  `install.py` re-exports `install_plan`'s names so nothing that already
  imports it needs to change.
- Standing permissions for this repo: new libraries need asking first,
  nothing here is live for real people or their data, and the
  second-model reviewer is GPT-5.1 (a different model family from the
  one that builds here).
- `themis.json` names `DECISIONS.md` as the decision log, but `install.py`
  never creates that file for any repo it sets up — the log is the
  owner's to start, or not, by hand; `uninstall` never looks at it either
  way. This repo's owner started one, which is this file.
- The CI backstop (both this repo's own `.github/workflows/ci.yml` and
  the `.github/workflows/themis.yml` template `install.py` offers)
  pins every action to a commit SHA, declares `permissions: contents:
  read`, and sets `persist-credentials: false` on checkout — a workflow
  that only reads and checks has no business holding a writable token.
- The generated backstop runs the *base* commit's own copy of
  `tools/themis.py` against a `--range`, on push as well as on a pull
  request, so a change that rewrites the checker to always pass (or a
  key pushed straight to a branch) is still caught by the version that
  existed before that change.
- Every write, delete and chmod refuses any symlink component, even one
  that resolves back inside the repo, and any control character in a
  path; reads use the same rule (`read_text(root, rel)`), so a symlinked
  file or parent is treated as absent and never shown, copied or parsed.
  The checker's own `baseline_path` is confined the same way.
- `check --range` diffs two-dot, not three-dot, because CI's stand-in
  base for a branch with no earlier commit is git's empty tree, which has
  no merge-base; a brand-new-branch push therefore scans every line for
  secrets instead of running a bare size check.
- A new file `install` creates is shown in full in the plan; only the
  files whose content is byte-identical to this kit (checker, hook,
  generated workflow) are summarised with a hash.
- The Aider adapter edits `read:` only as a block list or bare scalar,
  adding AGENTS.md on its own marked line; a flow list `[a, b]` is left
  alone with a note, since its single line cannot be undone cleanly.
- The machine-mode writers and the uninstall planners live in `install.py`, the install plan-building in
  `install_plan.py`, to keep both under the 800-line limit.
- Aider's auto-commit skips git hooks without `.aider.conf.yml`'s
  `git-commit-verify: true`, so when Aider is detected (or `--agents
  aider` is passed) install creates that file, every line marked
  `# themis`, and uninstall removes the file when only those lines are
  left; otherwise install prints a note.
- Aider: an owner file is never deleted unless every line in it is
  Themis's; an owner's `git-commit-verify: false` and a symlinked
  `.aider.conf.yml` are left alone with a printed note; no Aider note is
  printed when Aider is not detected and `--agents aider` is not given.
- `install.py` binds the names it uses from `install_plan.py` explicitly
  instead of copying every name across, so a linter sees each of them.
- The size baseline never rises, for anyone. `rebaseline` only lowers
  numbers or drops entries for files that shrank under the limit or were
  deleted; it refuses, writing nothing, if it would raise a number or add an
  entry. There is no override flag and no environment variable. A file over
  the limit is split to grow. The hook and the CI range check refuse a
  commit that raises the baseline.
- Three files are vendored (`tools/themis.py`, `tools/themis_lang.py`,
  `tools/themis_scan.py`), because the 800-line limit applies to the kit's
  own checker and the readers for seven languages do not fit in one file.
- The baseline has a `lang` section for the seven languages. A new or
  raised entry is accepted only if the base commit's own version of that
  file, measured with the current code, gives at least that number. This
  is not raising the baseline: it records only what already existed, so
  no new code can be recorded as existing.
- An anonymous function block outside any function with no binding name
  counts its own lines, its span minus the function blocks inside it, each
  of which is measured too; wrapping code in callbacks does not hide it.
- A long block outside any function that is not recognised as a function
  is a note: a data table must not block a commit, and a missed shape must
  not be silent. When its header holds the language's function keyword it
  is also keyed `<unmeasured>#n` and refused like a long function.
- C and C++ are not measured for function length yet; their macro-shaped
  headers and preprocessor branches need a separate reader.
- Rule 7 now says to delete only what a read shows is a true duplicate,
  because catching the same planted bug is not proof of one, and that a
  planted bug nothing catches is a missing test. Measured on a real
  project: 37 tests offered as duplicates for catching the same planted bug
  as another test each checked something the other did not, and the planted
  bugs no test caught found 11 missing tests across two packages. No other
  rule changed; this is release v3.2, and installs of v3 and v3.1 are
  offered the upgrade.
- Direction, from the owner: Themis aims at agent-written software that is
  token-efficient to build, safe, and trustworthy enough to deploy without
  an engineer reading every line, for any coding agent. It evolves one
  release at a time from real use and from periodic research into what
  frontier labs and other harnesses do; each new check is validated against
  that research before it is built.
- Rule 2's header is now checked, on new files only: a source file added
  relative to the run's base (staged against HEAD, A...B for CI, working
  tree plus untracked for plain `check`) must open with a comment or
  docstring of at most 29 lines holding Purpose, Entry points, Invariants
  and Never change without a decision, each with a colon and real text. New
  test files were added with a one-line docstring and nothing flagged it.
  Old files are never forced, so there is no baseline; the base commit's own
  `themis.json` decides, a new owner key `header_exempt_prefixes` skips a
  prefix, and the check is skipped with a note when the base has no config.
  It proves shape, not truth. Rule 7's last sentence now ends "unless a read
  shows the change cannot alter what the owner would notice": some planted
  bugs are equivalent changes (another check always stops them first, or
  the input cannot occur), and a test for one checks nothing; the read must
  name the exact place that makes it so. This is release v3.3, and installs
  of v3, v3.1 and v3.2 are offered the upgrade.
- Rule 13 gets a gate: when `themis.json` sets a `test` command, `gate` runs it
  and fails on an error, no test count, a count below the owner's floor or too
  many skips. A repository with no `test` key is never failed, only reported
  by `status` as honour-system, because failing it would force every installed
  repository to configure one. The rule's meaning is unchanged; enforcement is
  added, as rule 2's was in v3.3.
- A fourth vendored file, `tools/themis_gate.py`, holds the gate and the git
  runner and hook lines `status` prints, because `tools/themis.py` stood one
  line under the 800-line limit. The count of vendored files in older
  entries was true when they were written.
- The command, patterns, floor, skip ceiling and ignored paths come from the
  base commit's `themis.json`, like the header check, so a change cannot edit
  its own gate. Lowering the floor is the owner's own commit on the base
  branch (`gate --lower N --reason`, which also writes a decision-log line); a
  change that deletes tests under rule 7 therefore fails until the floor was
  lowered first. There is no override flag and no environment variable.
- A gate pass is bound to a commit by tree, not by HEAD alone: the tracked
  working tree and index must equal the committed tree before the run and
  again after it, so a setup step or the test command that changes tracked
  source cannot earn a pass attached to a commit that lacks the change.
  Generated files the tests need go in the owner's `ignore_paths`.
- The gate runs in its own workflow, `themis-gate.yml`, written once when a test
  command is set and never overwritten, because the owner must add the
  toolchain steps their tests need to it and a regenerated file would delete
  them; an upgrade that would change the template prints the difference.
  `themis.yml` stays wholly Themis's. A base checker older than v3.4 has no
  gate and the step is skipped, so the upgrade change is not held.
- The pre-push hook is on by default once a test command is set, and active
  where git reads `tools/hooks`; a hook manager gets a printed line, not an
  adapter. CI is the authority, a local receipt is only evidence and a cache.
  `status` drops the word "blocking": it prints the hook, the workflow wiring
  and the gate as facts and says plainly that a required check, branch
  protection and trigger coverage are not verified.
- Runner presets exist only for unittest, pytest and cargo, each checked
  against output captured from the real runner; Jest and Vitest have none,
  because no machine used for this release could capture their output, and
  need a `count_pattern`.
- This is release v3.4, and installs of v3 to v3.3 are offered the upgrade.
