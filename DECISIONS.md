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
