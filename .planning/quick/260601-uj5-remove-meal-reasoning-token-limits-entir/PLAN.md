---
status: completed
quick_id: 260601-uj5
slug: remove-meal-reasoning-token-limits-entir
started: 2026-06-01T17:58:58Z
---

# Remove Meal Reasoning Token Limits

## Goal

Remove token caps from the primary `meal_reasoning` model call and restart API/bot.

## Tasks

1. Remove the `max_tokens` cap from the reasoning chat completion.
2. Remove the OpenRouter reasoning `max_tokens` budget from the `meal_reasoning` trace/input body.
3. Keep parser repair bounded separately.
4. Update tests and verify.
5. Restart API/bot containers.
