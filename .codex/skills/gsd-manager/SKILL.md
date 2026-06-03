---
name: "gsd-manager"
description: "Interactive command center for managing multiple phases from one terminal"
metadata:
  short-description: "Interactive command center for managing multiple phases from one terminal"
---

<codex_skill_adapter>
## A. Skill Invocation
- This skill is invoked by mentioning `$gsd-manager`.
- Treat all user text after `$gsd-manager` as `{{GSD_ARGS}}`.
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

<objective>
Single-terminal command center for managing a milestone. Shows a dashboard of all phases with visual status indicators, recommends optimal next actions, and dispatches work — discuss runs inline, plan/execute run as background agents.

Designed for power users who want to parallelize work across phases from one terminal: discuss a phase while another plans or executes in the background.

**Creates/Updates:**
- No files created directly — dispatches to existing GSD commands via Skill() and background Task agents.
- Reads `.planning/STATE.md`, `.planning/ROADMAP.md`, phase directories for status.

**After:** User exits when done managing, or all phases complete and milestone lifecycle is suggested.
</objective>

<execution_context>
@/Users/mali/Documents/Projects/MealTracker/.codex/get-shit-done/workflows/manager.md
@/Users/mali/Documents/Projects/MealTracker/.codex/get-shit-done/references/ui-brand.md
</execution_context>

<context>
No arguments required. Requires an active milestone with ROADMAP.md and STATE.md.

Project context, phase list, dependencies, and recommendations are resolved inside the workflow using `gsd-sdk query init.manager`. No upfront context loading needed.
</context>

<process>
If `--analyze-deps` is in {{GSD_ARGS}}:
Read and execute `@/Users/mali/Documents/Projects/MealTracker/.codex/get-shit-done/workflows/analyze-dependencies.md` end-to-end.

Execute end-to-end.
Maintain the dashboard refresh loop until the user exits or all phases complete.
</process>
