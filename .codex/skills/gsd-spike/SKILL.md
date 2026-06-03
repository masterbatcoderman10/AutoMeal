---
name: "gsd-spike"
description: "Spike an idea through experiential exploration, or propose what to spike next (frontier mode)"
metadata:
  short-description: "Spike an idea through experiential exploration, or propose what to spike next (frontier mode)"
---

<codex_skill_adapter>
## A. Skill Invocation
- This skill is invoked by mentioning `$gsd-spike`.
- Treat all user text after `$gsd-spike` as `{{GSD_ARGS}}`.
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
Spike an idea through experiential exploration — build focused experiments to feel the pieces
of a future app, validate feasibility, and produce verified knowledge for the real build.
Spikes live in `.planning/spikes/` and integrate with GSD commit patterns, state tracking,
and handoff workflows.

Two modes:
- **Idea mode** (default) — describe an idea to spike
- **Frontier mode** (no argument or "frontier") — analyzes existing spike landscape and proposes integration and frontier spikes

Does not require prior new-project setup — auto-creates `.planning/spikes/` if needed.
</objective>

<execution_context>
@/Users/mali/Documents/Projects/MealTracker/.codex/get-shit-done/workflows/spike.md
@/Users/mali/Documents/Projects/MealTracker/.codex/get-shit-done/workflows/spike-wrap-up.md
@/Users/mali/Documents/Projects/MealTracker/.codex/get-shit-done/references/ui-brand.md
</execution_context>

<runtime_note>
**Copilot (VS Code):** Use `vscode_askquestions` wherever this workflow calls `AskUserQuestion`.
</runtime_note>

<context>
Idea: {{GSD_ARGS}}

**Available flags:**
- `--quick` — Skip decomposition/alignment, jump straight to building. Use when you already know what to spike.
- `--text` — Use plain-text numbered lists instead of AskUserQuestion (for non-the agent runtimes).
- `--wrap-up` — Package spike findings into a persistent project skill for future build conversations. Runs the spike-wrap-up workflow.
</context>

<process>
Parse the first token of {{GSD_ARGS}}:
- If it is `--wrap-up`: strip the flag, execute the spike-wrap-up workflow
- Otherwise: pass all of {{GSD_ARGS}} as the idea to the spike workflow end-to-end.

Preserve all workflow gates (prior spike check, decomposition, research, risk ordering, observability assessment, verification, MANIFEST updates, commit patterns).
</process>
