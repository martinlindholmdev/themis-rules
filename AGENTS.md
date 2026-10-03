# AGENTS.md: working on Themis

This repository is the rules kit and obeys its own rules: the block below,
copied from `RULES.md`, and `CONTRIBUTING.md`, which lists the two commands
that must pass before a commit.

Layout:

- `README.md`: what Themis is, for a person.
- `RULES.md`: the block every repository installs.
- `docs/install.md`: the agent's instructions for installing it elsewhere.
- `docs/frameworks.md`: the 17-agent support matrix.
- `tools/themis.py`: the vendored checker. Never changed without updating
  every repository that has it. `tools/themis_lang.py`, `tools/themis_scan.py`
  and `tools/themis_gate.py` (the acceptance gate) are vendored with it.
- `install.py`, `install_plan.py` and `install_gate.py`: the commands, the plan
  building, and the two CI workflow templates. Run only in this repository,
  never vendored.
- `tests/`: the test suite.

<!-- themis v3.5.2 begin -->
# Agent rules

Agents write this code; the owner reads results, not code. [check] marks
what `tools/themis.py` and its hook enforce. The rest holds only because
you read it.

Shape
1. [check] No file over 800 lines, no function over 100. Baseline sizes
   may shrink, never grow (`rebaseline` only lowers them). Over the limit:
   split the code. Never raise a limit.
2. [check] Every source file opens with a header under 30 lines: Purpose,
   Entry points, Invariants, Never change without a decision. Present
   tense. Checked on new files only: the opening comment or docstring
   holds those four labels, each followed by a colon and real text, in
   under 30 lines. Whether it is true and present tense is not checked.
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
   updated. Before bulk deletion, plant small bugs; keep what catches
   them, and delete only what a read shows is a true duplicate:
   catching the same bug is not proof. A planted bug nothing catches
   is a missing test, unless a read shows the change cannot alter what
   the owner would notice.
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
13. [check] Done means: the check and the tests ran and passed, you show
    their output, and a different model reviewed the diff for correctness
    and for changes outside the task. No output shown, not done. Checked
    only when themis.json sets a test command: CI then runs it on the
    committed tree and fails on an error, no test count, too few tests or
    too many skips. The review and whether the tests are adequate are not
    checked.
14. [check] No staged secret (a key, token, password) is committed — the
    rest of this rule is not checked. Stage files by name, never `-A`;
    commit each finished step and push; never force-push, skip the hook,
    or commit a file you did not change.
15. A decision only in chat does not exist: one line in the decision log
    before you finish. Write commits, comments and notes for a reader who
    never saw this conversation.

Start with `python3 tools/themis.py status`: it lists what is on.
<!-- themis v3.5.2 end -->

## Standing permissions
- New libraries without asking: no
- Live for real people or data: no
- Second-model reviewer: GPT-5.1 (a different model family than the one building)
