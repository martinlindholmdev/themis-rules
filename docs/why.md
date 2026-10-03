# Why the rules are as they are

One entry per rule in [RULES.md](../RULES.md): why the rule exists and,
where one exists, a public source. "Project judgement" marks a rule that
rests on this project's own reasoning, not on a published source. A source
supports the reason given; it does not endorse Themis.

Two reasons apply to all of the rules. A rules file is advice, while a hook
or a required CI check is enforced, so Themis checks what a script can check
([Claude Code memory](https://code.claude.com/docs/en/memory),
[Claude Code best practices](https://code.claude.com/docs/en/best-practices)).
The block is kept short because instruction following falls as the number of
instructions grows ([IFScale](https://arxiv.org/abs/2507.11538)).

## Shape

**1. Size limits and a baseline that only shrinks.** Agents work less well
as their context fills, so smaller files and functions are cheaper to read
and to change ([Claude Code best practices](https://code.claude.com/docs/en/best-practices),
[Chroma: context rot](https://www.trychroma.com/research/context-rot)).
The numbers 800 and 100 are project judgement; Google's Python guide suggests
considering a split past about 40 lines ([Google Python style guide](https://google.github.io/styleguide/pyguide.html)).

**2. A header on every source file.** The header tells an agent what a file
is for and what must not change, at the moment it opens the file. A module
docstring has precedent ([Google Python style guide](https://google.github.io/styleguide/pyguide.html),
[ruff D100](https://docs.astral.sh/ruff/rules/undocumented-public-module/)).
The four fields are project judgement, and no study measures their effect.

**3. Comments say what the code does now.** A wrong comment misleads a model
more than a missing one does ([arXiv 2404.03114](https://arxiv.org/abs/2404.03114)).
History goes stale, so it belongs in the decision log.

**4. One file for a shared fact.** A second copy drifts from the first.
Vendors advise pointing to one source instead of copying it
([Cursor rules](https://cursor.com/docs/rules)).

**5. Search before writing a helper.** Copied blocks grew as a share of code
changes from 2020 to 2024, while moved code fell
([GitClear, a vendor report](https://www.gitclear.com/ai_assistant_code_quality_2025_research)).
Reusing an existing helper keeps one place to fix.

**6. No code for a case that cannot happen.** Agents asked to find gaps tend
to add defensive code and tests for cases that cannot happen
([Claude Code best practices](https://code.claude.com/docs/en/best-practices)).
Such code costs reading time and proves nothing.

**7. Fewer tests, checked with planted bugs.** A planted bug shows whether a
test catches a fault; line coverage is a weak measure of that
([Google: mutation testing in review](https://arxiv.org/abs/2103.07189),
[Meta: mutation-guided test generation](https://arxiv.org/html/2501.12862v1),
[coverage and test effectiveness](https://dl.acm.org/doi/10.1145/2568225.2568271)).
Some planted changes alter nothing an owner would notice, so a surviving one
is read before it counts as a missing test
([Google: practical mutation testing](https://arxiv.org/abs/2102.11378)).

**8. A code map, held to the tree by a test.** A map lets an agent find the
right file without reading the tree. Hand-written repository overviews have
not been shown to help agents ([arXiv 2602.11988](https://arxiv.org/abs/2602.11988)),
and stale documentation misleads them ([arXiv 2404.03114](https://arxiv.org/abs/2404.03114)),
so the map is short and a test keeps it true. Aider builds its map from the
code for the same reason ([Aider repository map](https://aider.chat/2023/10/22/repomap.html)).

**9. A long job logs its duration.** Project judgement. One line makes a slow
or stuck job visible without extra tooling.

## Work

**10. A plan for anything larger than one sentence, reviewed by another model.**
The one-sentence threshold matches vendor advice
([Claude Code best practices](https://code.claude.com/docs/en/best-practices)).
A model tends to prefer its own output ([arXiv 2404.13076](https://arxiv.org/abs/2404.13076)),
which favours a different reviewer. Errors are correlated across models too
([Kim et al., ICML 2025](https://proceedings.mlr.press/v267/kim25e.html)),
so a second model reduces the risk but does not remove it.

**11. Change only what the task names; ask before a dependency.** A change
outside the task is one the owner did not ask for and may not see
([Claude Code best practices](https://code.claude.com/docs/en/best-practices)).
Models suggest packages that do not exist ([arXiv 2406.10279](https://arxiv.org/abs/2406.10279)),
so a new dependency needs a person's yes.

**12. Fix the cause.** Agents do get tests to pass by editing or special-casing
them, and telling them not to has little effect
([METR: reward hacking](https://metr.org/blog/2025-06-05-recent-reward-hacking/),
[Anthropic: long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)).
The rule names the forms this takes so a reviewer can look for them.

**13. Done means shown output and a review.** The owner reads results, not
code, so a claim of success needs its evidence beside it
([Claude Code best practices](https://code.claude.com/docs/en/best-practices),
[Cognition: testing](https://cognition.com/blog/testing-development)).
The acceptance gate turns "the tests ran and passed" into a check.

**14. No secrets; stage by name; never skip the hook.** A committed secret
stays in history. A local hook can be skipped
([git push](https://git-scm.com/docs/git-push)), and a required check on a
protected branch cannot
([GitHub protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)),
so CI is the backstop. Staging by name is project judgement: it keeps
unrelated files out of a commit.

**15. Decisions go in a log.** An agent starts each session without the last
one's conversation. Notes kept outside the context window carry decisions
forward ([Anthropic: context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents),
[Anthropic: long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)).
