---
status: completed
quick_id: 260601-ulg
completed: 2026-06-01T18:03:58Z
---

# Summary

Removed the secondary `meal_reasoning` parser-repair LLM path.

## Changes

- Deleted `_run_reasoning_parser_retry`.
- Removed the repair branch after unparseable reasoning output.
- Removed `REASONING_PARSER_MODEL` and `REASONING_PARSER_FALLBACK_MODEL` settings.
- Added coverage that unparseable reasoning makes only one LLM call and falls into the existing fallback/gate path.

## Verification

- `rtk ./.venv/bin/python -m py_compile app/services/reasoning_service.py tests/test_reasoning_flow.py app/config.py`
- `rtk ./.venv/bin/python -m unittest tests.test_reasoning_flow tests.test_reasoning_gate tests.test_reasoning_contract -q`
- `rtk ./.venv/bin/python -m unittest discover tests -q`
- `rtk git diff --check`
- Rebuilt/recreated API and bot; health returns `{"status":"ok"}`.
