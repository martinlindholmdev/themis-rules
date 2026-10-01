# Security

## Reporting

Report a security issue privately through the "Report a vulnerability"
button on this repository's Security tab, not as a public issue. Include
the file, the input that triggers it, and what you expected instead. Themis
has no release SLA; expect an acknowledgement, not a guaranteed fix date.

## What Themis does

- `tools/themis.py` is standard-library Python only: no network access, no
  third-party dependencies. It writes to exactly one file, the baseline,
  and only under `rebaseline`, which can only lower it.
- It scans staged diffs and commit ranges for secret-shaped strings
  (private keys, provider-shaped API tokens, long credential assignments)
  and refuses the commit. It is a pattern match, not an entropy model or a
  provider lookup: it misses secrets that do not match its patterns and
  occasionally flags something that is not one. Mark a confirmed false
  positive with `themis: allow-secret` on that line.
- A matched secret is reported by file and line number. The matched text is
  never printed, logged or included in any message.
- `install.py` never executes code from the repository it installs into:
  not an old checker it replaces, not a hook file it edits around. It never
  runs `git commit`; it prints the command. It makes no network requests.
- The machine-level pointer (`install.py machine`) writes a short,
  read-only instruction (read AGENTS.md, offer once, never run anything)
  into up to eight per-user agent config files, and only after the owner
  confirms each file on a TTY. It is not a mechanism for unattended changes
  to anyone's machine.

## What Themis never does

- Sends anything over the network.
- Executes a file it has not first byte-compared against its own known
  source — this is specifically how the installer's final `status` step
  decides whether to run the copy of the checker it just wrote; no other
  step executes anything from the target repository at all.
- Writes outside the target repository's working tree, except the machine
  step above (which the owner confirms file by file) and a worktree's
  shared hook file, which legitimately lives in the main repository's
  `.git` directory, not the worktree's own.
- Force-pushes, deletes data, or skips a hook on your behalf.
- Raises a size baseline, for anyone: the baseline only goes down. A file
  over a limit is split; `rebaseline` refuses to raise any number, and the
  hook and the CI range check refuse a commit that does.

## For repositories that install Themis

The CI backstop (`.github/workflows/themis.yml`) only protects a branch
that is itself protected: a pull request can edit the workflow file in
the same change it is meant to check. Add a `CODEOWNERS` entry for
`.github/workflows/` requiring review from someone who is not the PR's
author, so a workflow change needs a second set of eyes before it can
weaken what the backstop checks.
