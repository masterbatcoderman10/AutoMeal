---
name: "gsd-execute-phase"
description: "Execute all plans in a phase with wave-based parallelization"
metadata:
  short-description: "Execute all plans in a phase with wave-based parallelization"
---

<codex_skill_adapter>
## A. Skill Invocation
- This skill is invoked by mentioning `$gsd-execute-phase`.
- Treat all user text after `$gsd-execute-phase` as `{{GSD_ARGS}}`.
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
- `Task(isolation="worktree")` / `Agent(isolation="worktree")` → no automatic Codex git-worktree binding. For worktree-required flows, the orchestrator must first create an explicit `git worktree add -b worktree-agent-*` checkout, then pass that `worktree_root`, branch, and expected base into the spawned agent prompt. Executor agents must operate only inside that handed-off worktree root (#3360).

Spawn verification guard:
- Immediately after `multi_agent_v1.spawn_agent` returns an agent id, inspect the matching Codex session JSON under `$CODEX_HOME/sessions/` and verify `turn_context.payload.model` plus reasoning effort match the resolved GSD role. If the child inherited the parent/global model, close the agent before waiting on or merging its work, fix the agent TOML/config route, and retry only after the route is verified.

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
Execute all plans in a phase using wave-based parallel execution.

Orchestrator stays lean: discover plans, analyze dependencies, group into waves, spawn subagents, collect results. Each subagent loads the full execute-plan context and handles its own plan.

Optional wave filter:
- `--wave N` executes only Wave `N` for pacing, quota management, or staged rollout
- phase verification/completion still only happens when no incomplete plans remain after the selected wave finishes

Flag handling rule:
- The optional flags documented below are available behaviors, not implied active behaviors
- A flag is active only when its literal token appears in `{{GSD_ARGS}}`
- If a documented flag is absent from `{{GSD_ARGS}}`, treat it as inactive

Context budget: ~15% orchestrator, 100% fresh per subagent.
</objective>

<execution_context>
@/Users/mali/Documents/Projects/MealTracker/.codex/get-shit-done/workflows/execute-phase.md
@/Users/mali/Documents/Projects/MealTracker/.codex/get-shit-done/references/ui-brand.md
</execution_context>

<runtime_note>
**Copilot (VS Code):** Use `vscode_askquestions` wherever this workflow calls `AskUserQuestion`. They are equivalent — `vscode_askquestions` is the VS Code Copilot implementation of the same interactive question API.
</runtime_note>

<context>
Phase: {{GSD_ARGS}}

**Available optional flags (documentation only — not automatically active):**
- `--wave N` — Execute only Wave `N` in the phase. Use when you want to pace execution or stay inside usage limits.
- `--gaps-only` — Execute only gap closure plans (plans with `gap_closure: true` in frontmatter). Use after verify-work creates fix plans.
- `--interactive` — Execute plans sequentially inline (no subagents) with user checkpoints between tasks. Lower token usage, pair-programming style. Best for small phases, bug fixes, and verification gaps.

**Active flags must be derived from `{{GSD_ARGS}}`:**
- `--wave N` is active only if the literal `--wave` token is present in `{{GSD_ARGS}}`
- `--gaps-only` is active only if the literal `--gaps-only` token is present in `{{GSD_ARGS}}`
- `--interactive` is active only if the literal `--interactive` token is present in `{{GSD_ARGS}}`
- If none of these tokens appear, run the standard full-phase execution flow with no flag-specific filtering
- Do not infer that a flag is active just because it is documented in this prompt

Context files are resolved inside the workflow via `gsd-sdk query init.execute-phase` and per-subagent `<files_to_read>` blocks.
</context>

<process>
Execute end-to-end.
Preserve all workflow gates (wave execution, checkpoint handling, verification, state updates, routing).
</process>
