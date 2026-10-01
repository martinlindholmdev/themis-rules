# Agent support matrix

Checked against each tool's official documentation on 2026-10-01. "Not
documented" means the documentation says nothing either way, not that the
behaviour was tested and found safe. The notes below the table give each
agent's user-level config file, its permission layer, and the sources.

| Agent | Reads `AGENTS.md` | Runs git | Skips a git hook | Themis writes |
|---|---|---|---|---|
| Claude Code | Only when no `CLAUDE.md` is present | Yes | No | `CLAUDE.md` with `@AGENTS.md` |
| Codex CLI and app | Yes | Yes, `.git` read-only | No | Nothing |
| OpenCode | Yes | Yes | Not documented | Nothing |
| Goose | Yes | Yes, no approval in Auto mode | Not documented | Nothing |
| Cursor | Yes | Yes | Not documented | Nothing; deny rule below |
| Windsurf | Yes | Yes, Turbo mode auto-runs | Not documented | Nothing |
| Copilot coding agent (cloud) | Yes | In a cloud VM | No local hook exists there | Nothing; CI only |
| VS Code Copilot agent mode | Yes | Yes | Not documented | Nothing |
| Gemini CLI | Only via `context.fileName` | Yes | Not documented | `GEMINI.md` with `@AGENTS.md` |
| Google Antigravity (`agy`) | Yes | Yes, sandboxed | No, but see note | Nothing; CI is the guarantee |
| Aider | Only via `read:` | Yes, auto-commits | **Yes, by default** | `.aider.conf.yml` |
| Cline | Yes | Yes | Not documented | Nothing |
| Roo Code | Yes | Yes | Not documented | Nothing |
| Zed | Yes, unless an earlier rules file exists | Yes | Not documented | Nothing; warns |
| Amp | Yes | Yes, no approval by default | Not documented | Nothing |
| Warp | Yes, unless `WARP.md` exists | Yes | Not documented | Nothing; warns |
| OpenWork | Yes (OpenCode engine) | Yes | None found in source | Nothing |

## Notes

### Claude Code

- Rules: reads `AGENTS.md` only when no `CLAUDE.md` sits in or above the
  repository (since v2.1.277); `@AGENTS.md` inside a `CLAUDE.md` always
  works.
- User config: `~/.claude/CLAUDE.md`, `~/.claude/rules/*.md`.
- Shell: bash and git. Its sandbox mode protects only `.git/hooks` and
  `.git/config` from writes; commits and hooks otherwise run normally.
- Hook skip: not by design; issue #40117 reports `--no-verify` use in the
  wild.
- Permissions: a `PreToolUse` hook inspecting the full command (a
  prefix-deny rule alone misses variants).
- Themis: a one-line `CLAUDE.md` with `@AGENTS.md`, created if absent,
  appended to if present.
- Sources: code.claude.com/docs/en/memory, code.claude.com/docs/en/sandboxing,
  code.claude.com/docs/en/permissions.

### Codex CLI and app

- Rules: `~/.codex/AGENTS.md` first, then root-to-cwd `AGENTS.md` (closer
  wins), `AGENTS.override.md`; 32 KiB cap.
- User config: `~/.codex/AGENTS.md` (appended, backed up).
- Shell: the `workspace-write` sandbox makes `.git` read-only, including
  when `.git` is a worktree's gitdir pointer.
- Hook skip: with approval `never`, a blocked commit fails; with
  `on-request`, the owner approves an unsandboxed run and hooks fire. The
  desktop app's "Commit or push" button has been reported, unverified, to
  set `core.hooksPath=/dev/null`.
- Permissions: `on-request` plus `workspace-write`; a `prefix_rule` in
  `~/.codex/rules`.
- Themis: native read, nothing extra. Do not assume the app's commit button
  runs hooks; hand git steps to the owner when `.git` is read-only.
- Sources: learn.chatgpt.com/docs/agent-configuration/agents-md,
  learn.chatgpt.com/docs/agent-approvals-security.

### OpenCode

- Rules: walks up for `AGENTS.md`, falls back to `CLAUDE.md`, then
  `~/.config/opencode/AGENTS.md`; first match wins.
- User config: the same global file.
- Shell: no sandbox; bash allowed by default.
- Hook skip: not documented.
- Permissions: `permission.bash` pattern rules (approximate matching).
- Themis: native read, nothing extra; an optional deny rule in
  `opencode.json` (below).
- Sources: opencode.ai/docs/rules, opencode.ai/docs/permissions.

### Goose

- Rules: `AGENTS.md` then `.goosehints`, nested per directory; names set by
  `CONTEXT_FILE_NAMES`.
- User config: `~/.config/goose/.goosehints`, not `AGENTS.md`.
- Shell: no sandbox; the default Auto mode approves every tool call.
- Hook skip: not documented.
- Permissions: `GOOSE_MODE` manual or smart approval; no per-command rules.
- Themis: native read. The git hook is the only real backstop in Auto mode.
- Sources: goose-docs.ai/docs/guides/context-engineering/using-goosehints,
  goose-docs.ai/docs/guides/managing-tools/goose-permissions.

### Cursor (editor and `cursor-agent` CLI)

- Rules: `AGENTS.md` at root and nested (deeper wins); prefers
  `.cursor/rules/*.mdc`, which needs frontmatter.
- User config: GUI only (Settings, Rules, User Rules); no file.
- Shell: shell and git, approved by default; CLI `-p` mode runs unapproved.
- Hook skip: not documented. Forum reports of `--no-verify` and of Source
  Control forcing `core.hooksPath=/dev/null` (v3.15.6): a reported risk,
  not a specification.
- Permissions: a `beforeShellExecution` hook can deny a command.
- Themis: native read; a deny rule for `--no-verify` and `-n` (below). The
  machine part is GUI only, so the text is printed to paste.
- Sources: cursor.com/docs/context/rules, cursor.com/docs/agent/hooks.

### Windsurf (Devin Desktop, Cascade)

docs.windsurf.com redirects to docs.devin.ai.

- Rules: `AGENTS.md` at root, always on; subdirectories scoped.
- User config: `~/.codeium/windsurf/memories/global_rules.md`, 6000
  characters at most.
- Shell: a real terminal including git; modes Disabled, Allowlist, Auto,
  Turbo.
- Hook skip: not documented; Turbo mode auto-runs everything.
- Permissions: `cascadeCommandsAllowList` and `DenyList`.
- Themis: native read; see the Windsurf entry under hook-skip guards.
- Sources: docs.devin.ai/desktop/cascade/agents-md,
  docs.devin.ai/desktop/cascade/memories.

### GitHub Copilot coding agent (cloud)

- Rules: `AGENTS.md` at root and nested, plus
  `.github/copilot-instructions.md`, `CLAUDE.md`, `GEMINI.md`.
- User config: no local file; organisation-level instructions live in
  GitHub settings.
- Shell: an ephemeral Actions VM that checks out the repository and pushes
  only to `copilot/*` branches.
- Hook skip: inferred, not stated. A fresh clone carries no untracked hook,
  so a local pre-commit hook never fires there. `copilot-setup-steps.yml`
  runs before the agent and may itself set `core.hooksPath`, so a hook can
  fire inside the cloud agent if that step wires it up.
- Permissions: branch protection and required status checks apply to its
  pull requests; a workflow run on its pull request waits for a human
  "Approve and run".
- Themis: cannot run the local installer; enforced only through the
  required CI check.
- Sources: github.blog/changelog/2025-08-28,
  docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent,
  docs.github.com/en/copilot/concepts/agents/cloud-agent/risks-and-mitigations.

### VS Code Copilot agent mode (local)

- Rules: `AGENTS.md` at root; nested needs `chat.useNestedAgentsMdFiles`;
  prefers `.github/copilot-instructions.md`.
- User config: `~/.copilot/copilot-instructions.md` (documented for
  CLI-style "Agent Host" sessions; the IDE otherwise uses settings sync).
- Shell: local shell and git, per-command approval, `autoApprove` settings.
- Hook skip: not documented; a normal local commit.
- Permissions: approval settings only; the documentation says explicitly
  "not a security boundary".
- Themis: native read, nothing extra.
- Sources: code.visualstudio.com/docs/agent-customization/custom-instructions,
  code.visualstudio.com/docs/agents/run/approvals.

### Gemini CLI

- Rules: reads `GEMINI.md`, not `AGENTS.md`, unless `context.fileName` in
  `settings.json` is set to include it.
- User config: `~/.gemini/GEMINI.md`, `~/.gemini/settings.json`.
- Shell: shell with approval; a YOLO mode; no sandbox documented around
  `.git`.
- Hook skip: not documented. It keeps checkpoints in a shadow repository
  under `~/.gemini/history`.
- Permissions: not documented.
- Themis: a `GEMINI.md` with `@AGENTS.md` (appended if the file exists), or
  set `context.fileName` to include `AGENTS.md` directly.
- Account eligibility, user-reported and unconfirmed by a maintainer: a
  single GitHub issue (google-gemini/gemini-cli #28229, opened 2026-07-01,
  no maintainer reply as of 2026-10-01) reports that Gemini CLI stopped
  serving personal Google accounts around 2026-06-18, pointing them to
  Google Antigravity instead; API-key users are reportedly unaffected.
- Source: geminicli.com/docs/cli/gemini-md.

### Google Antigravity (`agy`)

The terminal counterpart to the Antigravity 2.0 desktop app, and the
replacement for personal-account Gemini CLI users since the change above.

- Rules: `GEMINI.md` or `AGENTS.md` at the workspace root, parsed on
  startup; `agy inspect` prints what it loaded; nested-file precedence not
  documented.
- User config: `~/.gemini/antigravity-cli/settings.json`, a JSON file, not
  a prose instructions file, so the Themis machine part prints the pointer
  text for the owner to place by hand.
- Shell: bash and git through its own sandbox. `.git` has been reported
  mounted read-only in the workspace "even for otherwise-writable agents"
  (secondary source, unverified against a primary changelog).
- Hook skip: not by default; hooks run inside the sandboxed git. A known
  problem, reported fixed in an unconfirmed version: local hooks or global
  git config could block the app's own internal checkpoint commits.
- Permissions: allow, ask and deny lists in `settings.json` (deny over ask
  over allow). `--dangerously-skip-permissions` removes the agent's own
  hook layer entirely (PreToolUse hooks are "not invoked at all"), and no
  documented policy or environment variable blocks that flag (secondary
  source, unverified against primary docs).
- Themis: native read, nothing extra to write. Because that flag can remove
  every local hook on this client, the CI backstop is the real guarantee.
- Headless runs need several allow rules, not one. Measured on a test
  machine on 2026-10-01, not taken from Google's documentation: an
  unattended `agy -p "install Themis..."` only got through once its
  settings allowed `toolPermission` `proceed-in-sandbox` (or an
  equivalent), `command(git)`, and `read_url` for both `github.com` and
  `raw.githubusercontent.com`. A narrow command allow-list alone failed at
  its first `ls -la`. On a private repository it cannot read the docs
  through raw URLs at all. Interactive use, where a person approves each
  step, works without any of these.
- Sources: antigravity.google/docs/cli/best-practices,
  antigravity.google/docs/settings, antigravity.google/docs/sandbox.
  Secondary: agenticcontrolplane.com/controls/antigravity,
  agenticcontrolplane.com/blog/antigravity-permissions-reference.

### Aider

- Rules: reads nothing automatically; needs `read: AGENTS.md` in
  `.aider.conf.yml`, or `--read`.
- User config: `~/.aider.conf.yml`.
- Shell: shell, and it auto-commits its own edits.
- Hook skip: yes, by default. `git-commit-verify` defaults to `False`, so
  commits run with `--no-verify` unless told otherwise (confirmed with
  `GIT_TRACE` on a test machine, 2026-10-01).
- Permissions: `git-commit-verify: true` in config.
- Themis: when Aider is detected in the repository (`.aider.conf.yml`,
  `.aider.chat.history.md`, `.aider.tags.cache*`, or `.aider` in
  `.gitignore`), or `install --agents aider` is passed, Themis creates
  `.aider.conf.yml` with `read: AGENTS.md` and `git-commit-verify: true`,
  every line marked `# themis`. An existing file gets just those lines
  added; a flow-list `read: [a, b]` is left for the owner to edit.
  `uninstall` removes the file when only those lines remain. With no sign
  of Aider, `install` only prints a note.
- Aider cannot drive the install itself. A release test with a small local
  model (gpt-oss-20b) could not get Aider to run `install.py` on its own
  behalf; point a person or a different agent at it and have Aider only
  read the result. Separately, `--yes-always` combined with a URL in the
  prompt has been observed making Aider install Playwright, Chromium and
  pandoc to fetch and render the URL. Avoid `--yes-always` when pasting a
  Themis install URL into an Aider prompt, or pass `--no-detect-urls`.
- Sources: aider.chat/docs/usage/conventions.html, aider.chat/docs/git.html.

### Cline

- Rules: reads `AGENTS.md` and `~/.agents/AGENTS.md`; prefers a
  `.clinerules/` folder when present.
- User config: `~/Documents/Cline/Rules` (also `~/.cline/rules`).
- Shell: shell, with tiered auto-approve.
- Hook skip and permissions: not documented.
- Themis: native read, nothing extra.
- Source: docs.cline.bot/customization/cline-rules.

### Roo Code

- Rules: reads `AGENTS.md` by default (`roo-cline.useAgentRules`); prefers
  a recursive `.roo/rules/` folder.
- User config: `~/.roo/rules/`.
- Shell: `execute_command` with allow and deny prefix lists.
- Hook skip and permissions: not documented.
- Themis: native read, nothing extra.
- Source: roocodeinc.github.io/Roo-Code/features/custom-instructions.

### Zed

- Rules: project root only, first match wins, in this order: `.rules`,
  `.cursorrules`, `.windsurfrules`, `.clinerules`,
  `.github/copilot-instructions.md`, `AGENT.md`, `AGENTS.md`, `CLAUDE.md`,
  `GEMINI.md`. No nesting.
- User config: `~/.config/zed/AGENTS.md` (Windows: `%APPDATA%\Zed\AGENTS.md`).
- Shell: a terminal tool; its sandboxing documentation says "git metadata
  is protected".
- Hook skip: not documented.
- Permissions: `agent.tool_permissions` `always_deny` regexes can block
  `--no-verify` (below).
- Themis: warns, rather than writes, when any file earlier in that list
  already exists, since it would silently pre-empt `AGENTS.md`.
- Sources: zed.dev/docs/ai/instructions, zed.dev/docs/ai/sandboxing,
  zed.dev/docs/ai/tool-permissions.

### Amp

- Rules: `AGENTS.md` from cwd up to `$HOME`, plus the subtree; falls back
  to `AGENT.md` and `CLAUDE.md`.
- User config: `~/.config/amp/AGENTS.md` or `~/.config/AGENTS.md`.
- Shell: shell, with no approval by default.
- Hook skip and permissions: not documented.
- Themis: native read, nothing extra. The pre-commit hook is the only real
  backstop given the lack of approval gating.
- Source: ampcode.com/docs/customize/agents-md.

### Warp

- Rules: `AGENTS.md` at the root, but `WARP.md` takes priority if both
  exist.
- User config: global rules, GUI only; no file.
- Shell: a real terminal; approvals through Agent Profiles.
- Hook skip and permissions: not documented.
- Themis: warns if `WARP.md` exists, since it would pre-empt `AGENTS.md`.
  The machine part is GUI only, so the text is printed to paste.
- Source: docs.warp.dev/agent-platform/capabilities/rules.

### OpenWork (`com.differentai.openwork`)

A desktop app, explicitly "not a CLI", built on a bundled OpenCode engine
as its sidecar binary, so it behaves like OpenCode above.

- Rules: it does not evaluate policy itself; the bundled engine reads
  `AGENTS.md` (walking up, falling back to `CLAUDE.md`, then
  `~/.config/opencode/AGENTS.md`).
- User config: the same `~/.config/opencode/AGENTS.md`, plus the user's
  global `opencode.json`. OpenWork's settings panel shows which config
  layer won but reads those files rather than replacing them.
- Shell: `bash`, `edit` and `mcp` are permission keys the engine evaluates
  against merged config (engine defaults, global `opencode.json`,
  OpenWork's injected config, workspace `opencode.json`; last match wins).
  No hardcoded default was seen; it falls to "ask" when nothing matches.
- Hook skip: no git-hook-skip or `core.hooksPath` logic found anywhere in
  its source; commits run through the owner's real local git and hooks
  fire normally.
- Themis: treat as OpenCode; native read, nothing extra.
- Source: github.com/different-ai/openwork (source read 2026-10-01).

## Hook-skip guards, where one exists

Copy the relevant snippet into that agent's own config alongside the Themis
git hook. None of these replace the CI backstop; they only narrow the
window before it catches a skipped hook.

**Claude Code** (`.claude/settings.json`, a `PreToolUse` hook). The hook
command receives the tool call as JSON on stdin (there is no
`$CLAUDE_TOOL_INPUT` environment variable), and only exit code 2 blocks the
call; exit 1 is reported but does not stop it.

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{"type": "command", "command": "python3 .claude/hooks/block-hook-skip.py"}]
    }]
  }
}
```

```python
# .claude/hooks/block-hook-skip.py
import json, re, sys
command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
if re.search(r"--no-verify|core\.hooksPath", command):
    print("blocked: looks like a hook-skip attempt", file=sys.stderr)
    sys.exit(2)
```

**Codex** (`~/.codex/rules`, Starlark `prefix_rule`, not shell text):

```python
prefix_rule(pattern=["git", "commit", "--no-verify"], decision="forbidden")
prefix_rule(pattern=["git", "-c", "core.hooksPath"], decision="forbidden")
```

**Cursor** (`.cursor/hooks.json`, `beforeShellExecution`). There is no
declarative deny list; the hook is a script that receives the command as
JSON on stdin and must itself print a decision.

```json
{"version": 1, "hooks": {"beforeShellExecution": [{"command": "./deny-hook-skip.sh"}]}}
```

```sh
#!/bin/sh
# .cursor/deny-hook-skip.sh
if grep -Eq -- '--no-verify|core\.hooksPath' <&0; then echo '{"permission":"deny"}'; fi
```

**Zed** (`settings.json`), under
`agent.tool_permissions.tools.terminal.always_deny`, a list of
`{"pattern": ...}` objects, not bare strings:

```json
{"agent": {"tool_permissions": {"tools": {"terminal": {"always_deny":
  [{"pattern": "--no-verify"}, {"pattern": "core\\.hooksPath"}]}}}}}
```

**OpenCode** (`opencode.json`, `permission.bash`):

```json
{"permission": {"bash": {"git commit --no-verify": "deny", "git -c core.hooksPath=*": "deny"}}}
```

**Goose**: no per-command rule exists; run it in `GOOSE_MODE=manual` for a
repository where a skipped hook would matter.

**Windsurf**: no documented deny-list key was found on the memories page
cited above. Rather than guess at one, configure command permissions in
Cascade's settings panel, per docs.devin.ai/desktop/cascade/agents-md and
the sandboxing and permissions pages linked from it.

## Fresh clones

Themis tracks its hook file at `tools/hooks/pre-commit`, but the git
setting that points at it, `core.hooksPath`, lives in `.git/config` and is
not cloned. A fresh clone of a repository installed the plain-git way (no
husky, lefthook or pre-commit framework) therefore has no active hook until
`install.py install` is run once in that clone. The CI backstop
(`.github/workflows/themis.yml`) is what guarantees enforcement regardless
of which clone, which agent, or whether a hook is wired up at all.
