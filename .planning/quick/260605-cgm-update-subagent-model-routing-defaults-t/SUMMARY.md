---
quick_id: 260605-cgm
slug: update-subagent-model-routing-defaults-t
status: complete
completed: 2026-06-05T04:59:38Z
---

# Summary

Updated GSD/Codex subagent routing to use `gpt-5.5` by default.

## Changes

- `.planning/config.json`: set Codex profile `opus` and `sonnet` to `gpt-5.5` with `high` reasoning effort; set `gsd-executor` override to `gpt-5.5` with `xhigh`; set `gsd-code-fixer` override to `gpt-5.5` with `high`.
- `.codex/agents/*.toml`: updated all installed agent router headers to `gpt-5.5`; kept only `gsd-executor.toml` at `xhigh`, with all other agents at `high`.
- `AGENTS.md`: updated the subagent model routing table to match the new defaults.

## Verification

- Confirmed `.planning/config.json`, `.codex/agents`, and `AGENTS.md` contain no remaining `gpt-5.4` or `gpt-5.3-codex-spark` references.
- Confirmed only `.codex/agents/gsd-executor.toml` has `model_reasoning_effort = "xhigh"`.
