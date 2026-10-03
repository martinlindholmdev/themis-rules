# Why the rules are as they are

One entry per rule in [RULES.md](../RULES.md): why the rule exists and,
where one exists, a public source. The rules apply to any repository and any
coding agent, not to a particular project or vendor. "Themis's own choice"
marks a design choice Themis makes for every repository, with no study behind
it. A source supports the reason given; it does not endorse Themis.

Two reasons apply to all of the rules. A rules file is advice, while a hook
or a required CI check enforces a condition, so Themis checks what a script
can check ([Claude Code memory](https://code.claude.com/docs/en/memory),
[Codex hooks](https://learn.chatgpt.com/docs/hooks),
[GitHub protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)).
Keeping the block short is Themis's own choice. IFScale reports declining
instruction following as keyword-inclusion instructions increase from 10 to
500 in a report-writing task ([IFScale](https://arxiv.org/abs/2507.11538));
it does not establish an effect for this rule block.

## Shape

**1. Size limits and a baseline that only shrinks.** Agents work less well
as their context fills, so smaller files and functions limit how much must
be read at once ([Claude Code best practices](https://code.claude.com/docs/en/best-practices),
[Chroma: context rot](https://www.trychroma.com/research/context-rot)).
The size limits and shrinking baseline are Themis's own choice; Google's
Python guide suggests considering a split when a function exceeds about 40 lines ([Google Python style guide](https://google.github.io/styleguide/pyguide.html)).

**2. A header on every source file.** The header tells an agent what a file
is for and what must not change, at the moment it opens the file. A module
docstring has precedent ([Google Python style guide](https://google.github.io/styleguide/pyguide.html),
[ruff D100](https://docs.astral.sh/ruff/rules/undocumented-public-module/)).
The four fields are Themis's own choice, and no study measures their effect.

**3. Comments say what the code does now.** A wrong comment misleads a model
more than a missing one does ([arXiv 2404.03114](https://arxiv.org/abs/2404.03114)).
History goes stale, so it belongs in the decision log.

**4. One file for a shared fact.** A second copy drifts from the first.
Cursor advises pointing to canonical examples instead of copying code
([Cursor rules](https://cursor.com/docs/rules)).

**5. Search before writing a helper.** Copied blocks grew as a share of code
changes from 2021 to 2024, while moved code fell
([GitClear, a vendor report](https://www.gitclear.com/ai_assistant_code_quality_2025_research)).
Reusing an existing helper keeps one place to fix.

**6. No code for a case that cannot happen.** Claude Code warns that chasing every
finding from a reviewer asked to find gaps can produce defensive code and tests
for cases that cannot happen
([Claude Code best practices](https://code.claude.com/docs/en/best-practices)).
Excluding such code is Themis's own choice.

**7. Fewer tests, checked with planted bugs.** Fewer tests is Themis's own
choice. A planted bug shows whether a test catches that fault; line coverage
alone can miss useful tests
([Google: mutation testing in review](https://arxiv.org/abs/2103.07189),
[Meta: mutation-guided test generation](https://arxiv.org/html/2501.12862v1)).
Some planted changes alter nothing an owner would notice, so a surviving one
is read before it counts as a missing test
([Google: practical mutation testing](https://arxiv.org/abs/2102.11378)).

**8. A code map, held to the tree by a test.** A map is intended to help an
agent find the right file without reading the tree; its use is Themis's own
choice, not a demonstrated benefit. Hand-written repository overviews have
not been shown to help agents ([arXiv 2602.11988](https://arxiv.org/abs/2602.11988)),
and incorrect documentation can hinder code understanding ([arXiv 2404.03114](https://arxiv.org/abs/2404.03114)),
so a short map checked against the tree is Themis's own choice. Aider builds
its repository map automatically from source files using tree-sitter ([Aider repository map](https://aider.chat/2023/10/22/repomap.html)).

**9. A long job logs its duration.** Themis's own choice: one line makes a
slow or stuck job visible without extra tooling.

## Work

**10. A plan for anything larger than one sentence, reviewed by another model.**
Vendors recommend scoping tasks and planning when needed; the one-sentence
threshold matches Claude Code advice
([Claude Code best practices](https://code.claude.com/docs/en/best-practices),
[Codex best practices](https://learn.chatgpt.com/guides/best-practices)).
A model tends to prefer its own output ([arXiv 2404.13076](https://arxiv.org/abs/2404.13076)),
which motivates a cross-check. The 20-line plan limit and the different-model
requirement are Themis's own choice. Errors are correlated across models too
([Kim et al., ICML 2025](https://proceedings.mlr.press/v267/kim25e.html)),
so a second model is a cross-check, not a guarantee.

**11. Change only what the task names; ask before a dependency.** Claude Code
recommends checking that nothing outside the task scope changed
([Claude Code best practices](https://code.claude.com/docs/en/best-practices)).
Models suggest packages that do not exist ([arXiv 2406.10279](https://arxiv.org/abs/2406.10279)),
so requiring a person's approval for a new dependency is Themis's own choice.

**12. Fix the cause.** In benchmark tasks, METR observed agents modifying tests
or scoring code to obtain higher scores; instructions not to cheat had nearly
negligible effect
([METR: reward hacking](https://metr.org/blog/2025-06-05-recent-reward-hacking/)).
Prohibiting these shortcuts in repository work is Themis's own choice.

**13. Done means shown output and a review.** An owner needs evidence of
success, not just an agent's claim
([Claude Code best practices](https://code.claude.com/docs/en/best-practices),
[Cognition: testing](https://cognition.com/blog/testing-development),
[Codex best practices](https://learn.chatgpt.com/guides/best-practices)).
When `themis.json` sets a test command, the acceptance gate checks that the
tests ran and passed.

**14. No secrets; stage by name; never skip the hook.** A committed secret
stays in history. A local hook can be skipped
([git push](https://git-scm.com/docs/git-push)), whereas a required check on a
protected branch blocks merging unless it passes or an authorised actor
bypasses protection
([GitHub protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)),
so CI is the backstop. Staging by name is Themis's own choice: it keeps
unrelated files out of a commit.

**15. Decisions go in a log.** An agent cannot rely on a previous session's
conversation being available. Notes kept outside the context window carry
decisions forward ([Anthropic: context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents),
[Anthropic: long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)).
