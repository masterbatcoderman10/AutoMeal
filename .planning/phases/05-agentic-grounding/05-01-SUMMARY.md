---
phase: 05-agentic-grounding
plan: 01
subsystem: api
tags: [openrouter, firecrawl, searxng, grounding, reasoning, testing]
requires:
  - phase: 04.5-source-aware-clarification-expansion
    provides: grouped clarification payloads, source metadata, and per-group finalizer seams
provides:
  - bounded grounding configuration for Firecrawl-backed search and scrape
  - strict reasoning and grounding schemas with constituents, serving counts, provenance, and stop reasons
  - app-owned grounding service primitives for allowlists, duplicate-call suppression, and timeout budgets
affects: [phase-05-inline-finalizer, reasoning, interview-finalization, tracing]
tech-stack:
  added: []
  patterns: [bounded grounding loop budgets, per-group URL allowlists, strict json-schema grounding contracts]
key-files:
  created: [app/services/grounding_service.py, tests/test_grounding_service.py]
  modified: [app/config.py, app/services/llm_client.py, app/services/reasoning_schema.py, app/services/reasoning_service.py, tests/test_reasoning_contract.py, tests/test_reasoning_flow.py]
key-decisions:
  - "Keep the new grounding surface app-owned: config + service primitives + strict schemas, without changing the existing save-path owner in this plan."
  - "Model tool-loop needs are exposed through `OpenRouterClient.chat_completion()` via optional `tool_choice`, `parallel_tool_calls`, and per-call `timeout` rather than a separate client path."
patterns-established:
  - "Grounding loop state is explicit and deterministic: allowlisted URLs, duplicate-call signatures, call-count budget, and wall-clock budget live in one service module."
  - "Reasoning and grounding contracts are separated: grouped reasoning carries constituent intent, while a second strict schema describes grounded nutrition output with provenance."
requirements-completed: [GROUND-01, GROUND-02, GROUND-03, REASON-04, INTERVIEW-03]
duration: 19min
completed: 2026-06-04
---

# Phase 05 Plan 01: Agentic Grounding Summary

**Firecrawl grounding foundations with bounded loop state, strict constituent-aware contracts, and trace-safe reasoning append helpers**

## Performance

- **Duration:** 19 min
- **Started:** 2026-06-04T08:23:00Z
- **Completed:** 2026-06-04T08:41:44Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- Added RED coverage for the new grounding contract layer: constituent-aware grouped reasoning, provenance-bearing finalizer output, Firecrawl service request shaping, allowlist rejection, duplicate-call suppression, and grounding trace append behavior.
- Implemented `app/services/grounding_service.py` with bounded loop budget/state primitives, Firecrawl search/scrape helpers, per-group URL allowlist checks, and duplicate tool-call bookkeeping.
- Extended Phase 5 foundations in config and schema layers so later inline finalizer work can request bounded tool calls and consume strict constituent/provenance contracts without touching the existing save path yet.

## Task Commits

Each task was committed atomically:

1. **Task 1: RED - capture grounding contract, allowlist, and schema regressions** - `4a17a04` (`test`)
2. **Task 2: GREEN - implement config, Firecrawl client seams, and strict grounding schemas** - `b8711e9` (`feat`)

## Files Created/Modified
- `app/config.py` - Added explicit grounding model, endpoint, timeout, search-limit, and tool-cap settings.
- `app/services/grounding_service.py` - Added app-owned Firecrawl search/scrape seam plus loop budget, allowlist, and duplicate-call primitives.
- `app/services/llm_client.py` - Added optional tool-calling controls and per-request timeout override support for future inline grounding turns.
- `app/services/reasoning_schema.py` - Added grouped reasoning constituent/serving fields and a strict grounding result response schema with provenance and stop reasons.
- `app/services/reasoning_service.py` - Added a trace-safe `append_grounding_trace()` helper for later finalizer integration.
- `tests/test_reasoning_contract.py` - Added schema-contract coverage for constituents, serving counts, provenance-bearing outputs, and stop reasons.
- `tests/test_reasoning_flow.py` - Added a regression asserting grounding trace blocks append without destroying existing reasoning payload structure.
- `tests/test_grounding_service.py` - Added executable coverage for Firecrawl request shaping, allowlist rejection, duplicate-call suppression, and explicit loop budgets.

## Decisions Made
- Kept the plan scoped to foundations only: no orchestration owner changes, no new save path, and no interview/finalizer rewiring in this slice.
- Used a dedicated grounding service module instead of embedding HTTP calls into reasoning/finalization code, so Phase 5 can reuse bounded-loop and allowlist behavior from a single seam.
- Verified the RED/GREEN loop in a Dockerized Python 3.12 environment because host Python runners in this worktree were not reliable for repo imports.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Host-side Python verification was not dependable in this executor environment: `/opt/homebrew/bin/python3` hung under the terminal runner, and `/usr/bin/python3` imported incompatible user-site packages. Verification was moved to the project Docker runtime built from `Dockerfile.api`, which matched the pinned dependencies and produced stable unittest results.
- A stale worktree `index.lock` briefly blocked the Task 2 commit. No active `git add` or `git commit` process was running, the lock had already cleared by the time it was inspected, and the commit succeeded on the next attempt without changing repo content.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Ready for the next Phase 5 slice to wire the inline finalizer/orchestration path onto the new grounding service and strict output contract.
- Container-based verification is the dependable path for this repo in the current executor environment until the host Python setup is aligned with the project dependency set.

## Self-Check

PASSED

- Found `.planning/phases/05-agentic-grounding/05-01-SUMMARY.md`
- Found task commits `4a17a04` and `b8711e9`
- Re-ran targeted verification: `docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_contract tests.test_reasoning_flow tests.test_grounding_service -q`

---
*Phase: 05-agentic-grounding*
*Completed: 2026-06-04*
