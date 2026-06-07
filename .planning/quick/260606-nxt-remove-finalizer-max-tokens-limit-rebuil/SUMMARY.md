---
status: completed
quick_id: 260606-nxt
completed: 2026-06-06T13:18:00Z
---

# Summary

Removed the finalizer `max_tokens` cap entirely and redeployed the live `api` and `bot` services.

## Changes

- Removed `FINALIZER_MAX_TOKENS` from `Settings`.
- Removed the finalizer `max_tokens` argument from `_bounded_group_finalizer_response()`.
- Updated finalizer contract tests to assert the path is uncapped.

## Verification

- `rtk uv run python - <<'PY' ...` confirmed `Settings.model_fields` no longer includes `FINALIZER_MAX_TOKENS`.
- Verified inside the running `api` container that the finalizer `chat_completion(...)` call no longer includes `max_tokens`.
- Rebuilt/recreated `api` and `bot` with `docker compose up -d --build --force-recreate api bot`.
- Verified `http://127.0.0.1:18000/health` returns `{"status":"ok"}`.
- Verified `mealttracker-api` is healthy and `mealttracker-bot` is started.
