---
quick_id: 260605-cgm
slug: update-subagent-model-routing-defaults-t
created: 2026-06-05
status: complete
---

# Quick Task: Update Subagent Model Routing Defaults

## Goal

Set GSD/Codex subagent routing to default to `gpt-5.5` with `high` reasoning effort, while making `gsd-executor` use `xhigh`.

## Plan

1. Update `.planning/config.json` model profile and explicit model overrides.
2. Update installed `.codex/agents/*.toml` router headers so current Codex subagent spawns use the new model immediately.
3. Update `AGENTS.md` so the documented routing table matches the effective configuration.
4. Verify no old `gpt-5.4` or `gpt-5.3-codex-spark` routes remain in the active project config surface.
