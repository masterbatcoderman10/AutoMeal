---
status: complete
quick_id: 260603-9oy
slug: update-reasoning-prompt-from-pasted-text
completed: 2026-06-03T03:09:40Z
---

# Quick Task 260603-9oy Summary

## Result

Updated the runtime meal-reasoning prompt to the pasted prompt shape and fixed deterministic source questioning so it no longer depends on model-emitted source policy wording.

## Changes

- Replaced the runtime prompt body in `app/services/reasoning_service.py` with the pasted prompt content while keeping taxonomy injection dynamic.
- Normalized legacy source-policy aliases such as `ALWAYS_ASK` and `DETERMINISTIC_ONLY` to the supported deterministic policies.
- Updated the reasoning gate to derive source follow-ups from learned-match count and learned source distribution, even when the model output omits or mangles source policy metadata.
- Added the explicit deterministic source decision table: zero embedding matches and fewer than five matches synthesize generic source questions; five or more matches with a dominant source block final write until source affirmation; five or more matches with ambiguous source history synthesize a generic source question.
- Updated the interview layer to synthesize deterministic source questions for approval candidates and to recognize learned distributions that only carry `source`.
- Changed rejected source affirmations so "No" re-asks the canonical deterministic source-origin question instead of falling back to free text.
- Rebuilt and restarted `api` and `bot` on the active `docker-compose.uat-042-clean.yml` stack.

## Verification

- `rtk ./.venv/bin/python -m unittest tests.test_reasoning_contract tests.test_reasoning_gate tests.test_reasoning_flow tests.test_interview_flow -q` -> `Ran 94 tests ... OK`
- `rtk ./.venv/bin/python -m unittest tests.test_bot_contract -q` -> `Ran 67 tests ... OK`
- `rtk docker compose --env-file .env -f docker-compose.yml -f docker-compose.uat-042-clean.yml up -d --build --force-recreate api bot` -> restart completed
- `rtk curl -fsS http://127.0.0.1:18000/health` -> `{"status":"ok"}`
