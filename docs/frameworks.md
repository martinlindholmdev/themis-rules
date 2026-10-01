# Framework support matrix

Checked against each tool's official docs on 2026-10-01 (Gemini CLI's
account-eligibility note checked against a GitHub issue on the same
date). Columns: (a) how it reads rules in a repo, (b) its user-level
("machine") config file, (c) whether it runs a real shell/git, (d)
whether it is documented to skip a git hook, (e) its own permission
layer, (f) what Themis does for it. "Not documented" means the official
docs say nothing either way, not that it has been tested and found safe.

## Claude Code, Codex, OpenCode, Goose

**Claude Code** — (a) reads `AGENTS.md` only when no `CLAUDE.md` sits in
or above the repo (since v2.1.277); `@AGENTS.md` inside a `CLAUDE.md`
always works. (b) `~/.claude/CLAUDE.md`, `~/.claude/rules/*.md`.
(c) bash + git; its own sandbox mode protects only `.git/hooks` and
`.git/config` from writes — commits and hooks otherwise run normally.
(d) not by design; issue #40117 reports `--no-verify` use in the wild.
(e) a `PreToolUse` hook inspecting the full command (a prefix-deny rule
alone misses variants). (f) a one-line `CLAUDE.md` with `@AGENTS.md`,
created if absent, appended to if present. Sources:
code.claude.com/docs/en/memory, code.claude.com/docs/en/sandboxing,
code.claude.com/docs/en/permissions.

**Codex CLI/app** — (a) `~/.codex/AGENTS.md` first, then root-to-cwd
`AGENTS.md` (closer wins), `AGENTS.override.md`, 32 KiB cap.
(b) `~/.codex/AGENTS.md` (appended, backed up). (c) the `workspace-write`
sandbox makes `.git` **read-only**, including when `.git` is a worktree's
gitdir pointer. (d) with approval `never`, a blocked commit just fails;
with `on-request`, the owner approves an unsandboxed run and hooks fire;
the desktop app's "Commit or push" button has been reported (unverified)
to set `core.hooksPath=/dev/null`. (e) `on-request` + `workspace-write`;
a `prefix_rule` in `~/.codex/rules`. (f) native `AGENTS.md` read, nothing
extra; don't assume the app's commit button runs hooks — hand git steps
to the owner when `.git` is read-only. Sources:
learn.chatgpt.com/docs/agent-configuration/agents-md,
learn.chatgpt.com/docs/agent-approvals-security.

**OpenCode** — (a) walks up for `AGENTS.md`, falls back to `CLAUDE.md`,
then `~/.config/opencode/AGENTS.md`; first match wins. (b) same global
file. (c) no sandbox; bash allowed by default. (d) not documented.
(e) `permission.bash` pattern rules (approximate matching). (f) native
read, nothing extra; an optional deny rule in `opencode.json`. Source:
opencode.ai/docs/rules, opencode.ai/docs/permissions.

**Goose** — (a) `AGENTS.md` then `.goosehints`, nested per directory,
names set by `CONTEXT_FILE_NAMES`. (b) `~/.config/goose/.goosehints`
(**not** `AGENTS.md` — the only place the original design doc guessed
wrong). (c) no sandbox; default Auto mode approves every tool call.
(d) not documented. (e) `GOOSE_MODE` manual/smart approval; no
per-command rules. (f) native read; the hook is the only real backstop
in Auto mode. Source: goose-docs.ai/docs/guides/context-engineering/using-goosehints,
goose-docs.ai/docs/guides/managing-tools/goose-permissions.

## Cursor, Windsurf, Copilot

**Cursor** (editor + `cursor-agent` CLI) — (a) `AGENTS.md` root and
nested (deeper wins); prefers `.cursor/rules/*.mdc` (needs frontmatter).
(b) GUI-only (Settings → Rules → User Rules), no file. (c) shell + git,
approved by default; CLI `-p` mode runs unapproved. (d) not documented;
forum reports of `--no-verify` and Source Control forcing
`core.hooksPath=/dev/null` (v3.15.6) — a reported risk, not a spec.
(e) a `beforeShellExecution` hook can deny a command. (f) native
`AGENTS.md` read; ship a deny rule for `--no-verify`/`-n` (snippet
below); GUI-only machine part, text printed to paste. Source:
cursor.com/docs/context/rules, cursor.com/docs/agent/hooks.

**Windsurf** (Devin Desktop/Cascade; docs.windsurf.com redirects to
docs.devin.ai) — (a) `AGENTS.md` at root, always on; subdirectories
scoped. (b) `~/.codeium/windsurf/memories/global_rules.md`, a **6000-char
cap**. (c) a real terminal incl. git; modes Disabled/Allowlist/Auto/
Turbo. (d) not documented; Turbo auto-runs everything. (e) a
`cascadeCommandsAllowList`/`DenyList`. (f) native read; a deny-list
hook-skip flag in Turbo mode (snippet below). Source:
docs.devin.ai/desktop/cascade/agents-md, docs.devin.ai/desktop/cascade/memories.

**GitHub Copilot coding agent (cloud)** — (a) `AGENTS.md` root and
nested, plus `.github/copilot-instructions.md`, `CLAUDE.md`, `GEMINI.md`.
(b) no local file; org-level instructions live in GitHub settings.
(c) an ephemeral Actions VM that checks out the repo and pushes only to
`copilot/*` branches. (d) inferred, not stated: a fresh clone carries no
untracked hook, so a local pre-commit hook never fires there at all.
(e) branch protection and required status checks apply to its PRs; a
workflow run on its PR waits for a human "Approve and run" —
`copilot-setup-steps.yml` runs *before* the agent and may itself set
`core.hooksPath`, so a local hook can fire inside the cloud agent too if
that step wires it up. (f) cannot run the local installer; enforced only
via the required CI check. Sources: github.blog/changelog/2025-08-28,
docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent,
docs.github.com/en/copilot/concepts/agents/cloud-agent/risks-and-mitigations.

**VS Code Copilot agent mode (local)** — (a) `AGENTS.md` root; nested
needs `chat.useNestedAgentsMdFiles`; prefers
`.github/copilot-instructions.md`. (b) `~/.copilot/copilot-instructions.md`
(documented for CLI-style "Agent Host" sessions; the IDE otherwise uses
settings sync). (c) local shell + git, per-command approval,
`autoApprove` settings. (d) not documented; a normal local commit.
(e) approval settings only — docs say explicitly "not a security
boundary". (f) native read, nothing extra. Source:
code.visualstudio.com/docs/agent-customization/custom-instructions,
code.visualstudio.com/docs/agents/run/approvals.

## Gemini CLI, Google Antigravity, Aider, Cline, Roo, Zed, Amp, Warp, OpenWork

**Gemini CLI** — (a) reads `GEMINI.md`, **not** `AGENTS.md`, unless
`context.fileName` in `settings.json` is set to include it. (b)
`~/.gemini/GEMINI.md`, `~/.gemini/settings.json`. (c) shell with
approval; a YOLO mode; no sandbox documented around `.git`. (d) not
documented; it keeps checkpoints in a shadow repo under
`~/.gemini/history`. (e) not documented. (f) a `GEMINI.md` with
`@AGENTS.md` (appended if the file exists), or set `context.fileName` to
include `AGENTS.md` directly. **Since 2026-06-18, Gemini CLI no longer
serves personal Google accounts** (free, AI Pro or AI Ultra) — it points
them to Google Antigravity instead; API-key users are unaffected
(github.com/google-gemini/gemini-cli issue #28229). Source:
geminicli.com/docs/cli/gemini-md.

**Google Antigravity (`agy`)** — the terminal counterpart to the
Antigravity 2.0 desktop app, and personal-account Gemini CLI users'
replacement since the change above. (a) `GEMINI.md` or `AGENTS.md` at the
workspace root, auto-parsed on startup; `agy inspect` prints what it
loaded; nested-file precedence not documented. (b)
`~/.gemini/antigravity-cli/settings.json` — a **JSON** config, not a
prose instructions file, so Themis's machine part prints the pointer
text for the owner to place by hand rather than writing it. (c) bash +
git through its own sandbox; `.git` has been reported mounted read-only
in the workspace "even for otherwise-writable agents" (secondary source,
not confirmed against a primary changelog — treat as unverified).
(d) not skip-by-default; hooks run inside the sandboxed git. A known
footgun, reported fixed in an unconfirmed version: local hooks or global
git config could block the app's own internal checkpoint commits.
(e) allow/ask/deny lists in `settings.json`, deny > ask > allow — but
**`--dangerously-skip-permissions` removes the hook layer entirely**
(PreToolUse hooks are "not invoked at all"); no documented policy or env
var blocks that flag (secondary source, unverified against primary
docs). (f) native `AGENTS.md` read, nothing extra to write — but a
hook-based kit must assume `--dangerously-skip-permissions` can remove
every local hook on this client, so the CI backstop is the real
guarantee here. Sources: antigravity.google/docs/cli/best-practices,
antigravity.google/docs/settings, antigravity.google/docs/sandbox;
secondary: agenticcontrolplane.com/controls/antigravity,
agenticcontrolplane.com/blog/antigravity-permissions-reference.

**Aider** — (a) reads nothing automatically; needs `read: AGENTS.md` in
`.aider.conf.yml`, or `--read`. (b) `~/.aider.conf.yml`. (c) shell, and
it auto-commits its own edits. (d) **skips hooks by default** —
`git-commit-verify` defaults to `False`, i.e. commits run with
`--no-verify` unless told otherwise. (e) `git-commit-verify: true` in
config. (f) when `.aider.conf.yml` already exists, Themis adds
`read: AGENTS.md` and `git-commit-verify: true` to it (never creates the
file — that would turn Aider on for a repo that isn't using it). Source:
aider.chat/docs/usage/conventions.html, aider.chat/docs/git.html.

**Cline** — (a) reads `AGENTS.md` and `~/.agents/AGENTS.md`; prefers a
`.clinerules/` folder when present. (b) `~/Documents/Cline/Rules` (also
`~/.cline/rules`). (c) shell, with tiered auto-approve. (d)/(e) not
documented. (f) native read, nothing extra. Source:
docs.cline.bot/customization/cline-rules.

**Roo Code** — (a) reads `AGENTS.md` by default
(`roo-cline.useAgentRules`); prefers a recursive `.roo/rules/` folder.
(b) `~/.roo/rules/`. (c) `execute_command` with allow/deny prefix lists.
(d)/(e) not documented. (f) native read, nothing extra. Source:
roocodeinc.github.io/Roo-Code/features/custom-instructions.

**Zed** — (a) project root only, **first match wins**, in this order:
`.rules`, `.cursorrules`, `.windsurfrules`, `.clinerules`,
`.github/copilot-instructions.md`, `AGENT.md`, `AGENTS.md`, `CLAUDE.md`,
`GEMINI.md` — no nesting. (b) `~/.config/zed/AGENTS.md` (Windows:
`%APPDATA%\Zed\AGENTS.md`). (c) a terminal tool; its sandboxing doc says
"git metadata is protected". (d) not documented. (e)
`agent.tool_permissions` `always_deny` regexes can block `--no-verify`
(snippet below). (f) Themis warns, rather than writes, when any file
earlier in that list already exists — it would silently pre-empt
`AGENTS.md`. Source: zed.dev/docs/ai/instructions, zed.dev/docs/ai/sandboxing,
zed.dev/docs/ai/tool-permissions.

**Amp** — (a) `AGENTS.md` from cwd up to `$HOME`, plus the subtree;
falls back to `AGENT.md`/`CLAUDE.md`. (b) `~/.config/amp/AGENTS.md` or
`~/.config/AGENTS.md`. (c) shell, with **no approval by default**.
(d)/(e) not documented. (f) native read, nothing extra — the pre-commit
hook is the only real backstop given the lack of approval gating.
Source: ampcode.com/docs/customize/agents-md.

**Warp** — (a) `AGENTS.md` at the root, but **`WARP.md` takes priority
if both exist**. (b) global rules, GUI-only, no file. (c) a real
terminal; approvals via Agent Profiles. (d)/(e) not documented.
(f) Themis warns if `WARP.md` exists (it would pre-empt `AGENTS.md`);
GUI-only machine part, text printed to paste. Source:
docs.warp.dev/agent-platform/capabilities/rules.

**OpenWork** (`com.differentai.openwork`) — a desktop app, explicitly
"not a CLI", built on a bundled OpenCode engine as its sidecar binary, so
it behaves exactly like OpenCode above: (a)/(d) it does not evaluate
policy itself — the bundled OpenCode engine reads `AGENTS.md` (walking
up, falling back to `CLAUDE.md`, then `~/.config/opencode/AGENTS.md`).
(b) the same `~/.config/opencode/AGENTS.md`, plus the user's global
`opencode.json`; OpenWork's own settings panel shows which config layer
won, but reads those files rather than replacing them. (c) bash/edit/mcp
are permission keys the engine evaluates against merged config
(engine defaults → global `opencode.json` → OpenWork's injected config →
workspace `opencode.json`, last match wins); no hardcoded default seen,
falls to "ask" when nothing matches. (e) no git-hook-skip or
`core.hooksPath` logic found anywhere in its source — commits run
through the owner's real local git, hooks fire normally. (f) treat as
OpenCode: native read, nothing extra. Source:
github.com/different-ai/openwork (read 2026-10-01).

## Hook-skip guards, where one exists

Copy the relevant snippet into that agent's own config alongside
Themis's git hook — none of these replace the CI backstop, they only
narrow the window before it catches a skipped hook.

**Claude Code** (`.claude/settings.json`, a `PreToolUse` hook):
```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{"type": "command", "command": "case \"$CLAUDE_TOOL_INPUT\" in *--no-verify*|*hooksPath*) exit 1;; esac"}]
    }]
  }
}
```

**Codex** (`~/.codex/rules`, a `prefix_rule`):
```
prefix_rule "git commit" allow
prefix_rule "git commit --no-verify" deny
prefix_rule "git -c core.hooksPath" deny
```

**Cursor** (`.cursor/hooks.json`, `beforeShellExecution`):
```json
{"beforeShellExecution": {"deny": ["git commit --no-verify", "git -c core.hooksPath=*"]}}
```

**Zed** (`settings.json`, `agent.tool_permissions`):
```json
{"agent": {"tool_permissions": {"always_deny": ["--no-verify", "core\\.hooksPath"]}}}
```

**OpenCode** (`opencode.json`, `permission.bash`):
```json
{"permission": {"bash": {"git commit --no-verify": "deny", "git -c core.hooksPath=*": "deny"}}}
```

**Goose** — no per-command rule exists; run it in `GOOSE_MODE=manual` for
a repo where a skipped hook would matter.

**Windsurf** (Cascade settings, `cascadeCommandsDenyList`):
```json
{"cascadeCommandsDenyList": ["git commit --no-verify", "git -c core.hooksPath=*"]}
```

## A note on fresh clones

A brand-new clone of a repo with Themis installed the classic way (no
husky/lefthook/pre-commit framework) has **no hook until `install.py
install` is run once in that clone** — this is ordinary git behaviour,
not a Themis gap, since hooks live outside what git clones unless
`core.hooksPath` points at a tracked directory (which Themis's own setup
does, at `tools/hooks`). The CI backstop (`.github/workflows/themis.yml`)
is what actually guarantees enforcement regardless of which clone, which
agent, or whether a hook is wired up at all.
