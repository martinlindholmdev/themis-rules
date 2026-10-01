# Security

## Reporting

Please report a security issue privately — use GitHub's "Report a
vulnerability" button on this repo's Security tab, rather than opening a
public issue. Include the file, the input that triggers it, and what you
expected instead. Themis has no maintained-release SLA; expect an
acknowledgement, not a guaranteed fix date.

## What Themis does

- `tools/themis.py` is standard-library Python only: no network access,
  no third-party dependencies, ever. It writes to exactly one file (the
  baseline), and only when explicitly asked to rebaseline.
- It scans staged diffs and commit ranges for secret-shaped strings
  (private keys, provider-shaped API tokens, long credential
  assignments) and refuses the commit — but it is a pattern match, not a
  secret scanner with an entropy model or a provider API to verify
  against. It will miss secrets that don't match its patterns, and it
  will occasionally flag something that isn't one (use `themis:
  allow-secret` on that line for a confirmed false positive).
- A matched secret's file and line number are reported; the matched text
  itself is never printed, logged, or included in any message.
- `install.py` never executes code from the repo it is installing into:
  not an old checker it is replacing, not a generated hook file it edits
  around, and it never runs `git commit` itself (it only prints the
  command). It makes no network requests.
- The machine-level pointer (`install.py machine`) writes a short,
  read-only instruction — read AGENTS.md, offer once, never run anything
  — into a handful of per-user agent config files, and only after the
  owner confirms each file on a TTY. It is not a mechanism for silent,
  unattended changes to anyone's machine.

## What Themis never does

- Sends anything over the network.
- Executes a file it has not first byte-compared against its own known
  source.
- Writes outside the target repo's working tree, except the machine part
  described above, which the owner confirms file by file.
- Force-pushes, deletes data, or skips a hook on your behalf.
- Raises a size baseline on its own — only the repo owner does that, by
  hand, with `python3 tools/themis.py rebaseline`.
