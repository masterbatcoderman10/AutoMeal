---
status: completed
quick_id: 260601-ulg
slug: remove-meal-reasoning-parser-repair-path
started: 2026-06-01T18:01:44Z
---

# Remove Meal Reasoning Parser Repair Path

## Goal

Trust the strict structured-output reasoning model and remove the secondary parser-repair LLM call.

## Tasks

1. Delete the `meal_reasoning` parser repair helper and retry branch.
2. Remove parser-specific settings/tests for reasoning.
3. Verify malformed reasoning now falls straight to `FAILED_UNCLEAR`.
4. Run tests and restart API/bot.
