---
status: completed
quick_id: 260601-uj5
completed: 2026-06-01T18:00:00Z
---

# Summary

Removed primary `meal_reasoning` token limits and restarted API/bot.

## Changes

- Removed the `max_tokens` cap from the main reasoning model call.
- Removed the OpenRouter `reasoning.max_tokens` budget from the `meal_reasoning` trace/input body.
- Kept parser repair capped at 1024 tokens.
- Updated reasoning trace tests for uncapped meal reasoning.

## Verification

- `rtk ./.venv/bin/python -m unittest tests.test_reasoning_flow tests.test_reasoning_gate tests.test_reasoning_contract -q`
- `rtk ./.venv/bin/python -m unittest discover tests -q`
- Rebuilt/recreated API and bot with `docker compose ... up -d --build --force-recreate api bot`.
- Verified `http://127.0.0.1:18000/health` returns `{"status":"ok"}`.
