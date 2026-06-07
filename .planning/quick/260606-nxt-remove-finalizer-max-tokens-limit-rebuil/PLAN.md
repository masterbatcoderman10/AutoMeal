---
status: completed
quick_id: 260606-nxt
slug: remove-finalizer-max-tokens-limit-rebuil
started: 2026-06-06T13:14:10.814Z
---

# Remove Finalizer Token Limit

## Goal

Remove the finalizer `max_tokens` cap entirely, then rebuild and redeploy the live `api` and `bot` services.

## Tasks

1. Remove `FINALIZER_MAX_TOKENS` from finalizer config and service usage.
2. Update finalizer contract tests to assert the call is uncapped.
3. Rebuild and force-recreate `api` and `bot`.
4. Verify the live containers are healthy and running the uncapped finalizer path.
