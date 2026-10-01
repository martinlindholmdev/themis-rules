# AGENTS.md — working on Themis

This repo is the rules kit, and it obeys its own rules (see `RULES.md`,
copied below between the markers, and `CONTRIBUTING.md`). Layout:
`README.md` (what this is, for a person), `RULES.md` (the block any repo
installs), `docs/install.md` (the agent's view of installing it elsewhere),
`docs/frameworks.md` (the 17-surface support matrix), `tools/themis.py`
(the vendored checker, never changed without updating every repo that
has it), `install.py` (the install/machine/uninstall entry points) and
`install_plan.py` (the plan-building and shared mechanics it calls —
together with `install.py`, this repo only, never vendored), and `tests/`.

Before committing: `python3 -m unittest discover -s tests` and
`python3 tools/themis.py status` both clean.

<!-- themis v3 begin -->
# Agent rules

Agents write this code; the owner reads results, not code. [check] marks
what `tools/themis.py` and its hook enforce. The rest holds only because
you read it.

Shape
1. [check] No file over 800 lines, no function over 100. Baseline sizes
   may shrink, never grow. Over the limit: split the code. Never raise a
   limit or edit the baseline; only the owner does.
2. Every source file opens with a header under 30 lines: Purpose, Entry
   points, Invariants, Never change without a decision. Present tense.
3. [check] Comments say what the code does now and why. No dates, "used
   to", bug numbers, reviewer, session or model names. History goes in
   the decision log, one line per decision.
4. A name, limit, path or version needed in a second file moves into one
   file both read, the moment you would write the second copy.
5. Before writing a helper, search the repo for one. Reuse or extend it.
6. No code for a case that cannot happen: no branch for an input the types
   rule out, no option or abstraction with one caller. Delete unused
   code; never silence the warning about it.
7. Fewer tests, not more: one per behaviour the owner would notice
   breaking. A test that pins today's exact output is deleted, not
   updated. Before bulk deletion, plant small bugs; keep what catches them.
8. Past 25 source files, one code map under 40 lines, held to the tree by
   a test. Shrink one module at a time; run the tests between batches.
9. A scheduled or long-running job ends with one log line giving its duration.

Work
10. A change you can describe in one sentence: start. Anything else: a plan
    under 20 lines, reviewed by a different model first.
11. Change only what the task names. Stop and ask before a new dependency,
    an unforeseen design change, deleting data or files, or touching a
    running system — unless this repo's own rules give standing permission.
    Credentials, network or personal data also need a security review.
12. Fix the cause. Never get green by swallowing an error, loosening an
    assertion, raising a limit or skipping the hook. A failure you see is
    yours until unchanged main shows it too.
13. Done means: the check and the tests ran and passed, you show their
    output, and a different model reviewed the diff for correctness and
    for changes outside the task. No output shown, not done.
14. [check] No staged secret (a key, token, password) is committed — the
    rest of this rule is not checked. Stage files by name, never `-A`;
    commit each finished step and push; never force-push, skip the hook,
    or commit a file you did not change.
15. A decision only in chat does not exist: one line in the decision log
    before you finish. Write commits, comments and notes for a reader who
    never saw this conversation.

Start with `python3 tools/themis.py status`: it lists what is on.
<!-- themis v3 end -->

## Standing permissions
- New libraries without asking: no
- Live for real people or data: no
- Second-model reviewer: GPT-5.1 (a different model family than the one building)
