---
name: "gsd-workstreams"
description: "Manage parallel workstreams — list, create, switch, status, progress, complete, and resume"
metadata:
  short-description: "Manage parallel workstreams — list, create, switch, status, progress, complete, and resume"
---

<codex_skill_adapter>
## A. Skill Invocation
- This skill is invoked by mentioning `$gsd-workstreams`.
- Treat all user text after `$gsd-workstreams` as `{{GSD_ARGS}}`.
- If no arguments are present, treat `{{GSD_ARGS}}` as empty.

## B. AskUserQuestion → request_user_input Mapping
GSD workflows use `AskUserQuestion` (Claude Code syntax). Translate to Codex `request_user_input`:

Parameter mapping:
- `header` → `header`
- `question` → `question`
- Options formatted as `"Label" — description` → `{label: "Label", description: "description"}`
- Generate `id` from header: lowercase, replace spaces with underscores

Batched calls:
- `AskUserQuestion([q1, q2])` → single `request_user_input` with multiple entries in `questions[]`

Multi-select workaround:
- Codex has no `multiSelect`. Use sequential single-selects, or present a numbered freeform list asking the user to enter comma-separated numbers.

Execute mode fallback:
- When `request_user_input` is rejected or unavailable, activate TEXT_MODE: append `--text` to `{{GSD_ARGS}}` so the workflow's built-in text-mode branching takes over. Present every `AskUserQuestion` call as a plain-text numbered list, then stop and wait for the user's reply. Do NOT pick a default and continue (#3018 / #3808).
- You may only proceed without a user answer when one of these is true:
  (a) the invocation included an explicit non-interactive flag (`--auto` or `--all`),
  (b) the user has explicitly approved a specific default for this question, or
  (c) the workflow's documented contract says defaults are safe (e.g. autonomous lifecycle paths).
- Do NOT write workflow artifacts (CONTEXT.md, DISCUSSION-LOG.md, PLAN.md, checkpoint files) until the user has answered the plain-text questions or one of (a)-(c) above applies. Surfacing the questions and waiting is the correct response — silently defaulting and writing artifacts is the #3018 failure mode.

## C. Task() → Codex Multi-Agent Mapping
GSD workflows use `Task(...)` (Claude Code syntax). Translate to Codex multi-agent tools when they are actually available.

Tool discovery first:
- Before deciding sub-agents are unavailable, call `tool_search` with a query like `spawn agent multi-agent subagent wait close agent`.
- If discovery exposes `multi_agent_v1`, use `multi_agent_v1.spawn_agent`, `multi_agent_v1.wait_agent`, and `multi_agent_v1.close_agent`.
- Do not claim multi-agent spawning is unavailable just because it was not in the initial tool list; Codex may expose the tools lazily after discovery.

Direct mapping after discovery:
- `Task(subagent_type="X", prompt="Y")` → `multi_agent_v1.spawn_agent(agent_type="X", message="Y")`
- `Task(model="...")` → omit by default. GSD embeds the resolved per-agent model directly into each agent's `.toml` at install time so `model_overrides` from `.planning/config.json` and `~/.gsd/defaults.json` are honored automatically by Codex's agent router. Only pass a model override when the user explicitly requested it or the runtime contract requires it.
- Resolved `reasoning_effort="low|medium|high|xhigh"` → pass `reasoning_effort` only when the exposed tool schema supports it. Omit missing, empty, inherited, or unsupported values; do not invent one-off effort literals in workflow prose.
- `fork_context: false` by default — GSD agents load their own context via `<files_to_read>` blocks.
- `Task(isolation="worktree")` / `Agent(isolation="worktree")` → no automatic Codex worktree binding. Workflows that require worktree isolation must use an explicit manual worktree protocol before spawning (#3360).

Spawn restriction and fallback:
- Codex permits sub-agent spawning only when the user explicitly asks for sub-agents, delegation, or parallel agent work, or when the invoked GSD workflow itself explicitly requires sub-agents as part of the user's chosen command.
- If `tool_search` does not expose multi-agent tools, or spawning is not permitted, do not stop at a tooling complaint. Execute the workflow inline in the current agent where safe, preserving gates and artifacts; if the workflow explicitly requires isolated sub-agents/worktrees and no safe inline path exists, fail closed with the exact missing capability and next remediation.

Parallel fan-out:
- Spawn multiple agents → collect agent IDs → `multi_agent_v1.wait_agent(targets=[...])` as needed.

Result parsing:
- Look for structured markers in agent output: `CHECKPOINT`, `PLAN COMPLETE`, `SUMMARY`, etc.
- `multi_agent_v1.close_agent(target=id)` after collecting results from each agent.
</codex_skill_adapter>

# $gsd-workstreams

Manage parallel workstreams for concurrent milestone work.

## Usage

`$gsd-workstreams [subcommand] [args]`

### Subcommands

| Command | Description |
|---------|-------------|
| `list` | List all workstreams with status |
| `create <name>` | Create a new workstream |
| `status <name>` | Detailed status for one workstream |
| `switch <name>` | Set active workstream |
| `progress` | Progress summary across all workstreams |
| `complete <name>` | Archive a completed workstream |
| `resume <name>` | Resume work in a workstream |

## Step 1: Parse Subcommand

Parse the user's input to determine which workstream operation to perform.
If no subcommand given, default to `list`.

## Step 2: Execute Operation

### list
Run: `gsd-sdk query workstream.list --raw --cwd "$CWD"`
Display the workstreams in a table format showing name, status, current phase, and progress.

### create
Run: `gsd-sdk query workstream.create <name> --raw --cwd "$CWD"`
After creation, display the new workstream path and suggest next steps:
- `$gsd-new-milestone --ws <name>` to set up the milestone

### status
Run: `gsd-sdk query workstream.status <name> --raw --cwd "$CWD"`
Display detailed phase breakdown and state information.

### switch
Run: `gsd-sdk query workstream.set <name> --raw --cwd "$CWD"`
Also set `GSD_WORKSTREAM` for the current session when the runtime supports it.
If the runtime exposes a session identifier, GSD also stores the active workstream
session-locally so concurrent sessions do not overwrite each other.

### progress
Run: `gsd-sdk query workstream.progress --raw --cwd "$CWD"`
Display a progress overview across all workstreams.

### complete
Run: `gsd-sdk query workstream.complete <name> --raw --cwd "$CWD"`
Archive the workstream to milestones/.

### resume
Set the workstream as active and suggest `$gsd-resume-work --ws <name>`.

## Step 3: Display Results

Format the JSON output from gsd-sdk query into a human-readable display.
Include the `${GSD_WS}` flag in any routing suggestions.
