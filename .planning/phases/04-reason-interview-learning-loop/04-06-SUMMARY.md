# Phase 04: Telegram interview flow and grounding prep

---
phase: 04-reason-interview-learning-loop
plan: 06
subsystem: bot
tags: [telegram, interview, grounding, final-write]

# Dependency graph
requires:
  - phase: 04-reasoning-happy-path
    provides: persisted reasoning state and INTERVIEWING handoff from 04-05
provides:
  - pinned-chat interview helpers and handler wiring
  - confirmation edit replay and photo-aware all-wrong branch
  - minimal packaged/restaurant NEEDS_GROUNDING prep
  - one-shot interview reminder polling
affects:
  - 04-reason-interview-learning-loop
  - 05

# Tech tracking
tech-stack:
  added: []
  patterns:
    - DB-owned interview state with terse bot-facing helper functions
    - shared final-write boundary for confirmed and best-effort interview outcomes
    - minimal grounding handoff stored as NEEDS_GROUNDING metadata for Phase 5

key-files:
  created:
    - app/services/interview_service.py
    - app/services/grounding_stub.py
    - scripts/assert_interview_red.py
  modified:
    - bot/handlers.py
    - bot/main.py
    - bot/messages.py
    - bot/polling.py
    - tests/test_interview_flow.py
    - tests/test_bot_contract.py

key-decisions:
  - Keep Telegram text terse: one context sentence plus the requested answer/edit.
  - Treat packaged and restaurant answers as unverified NEEDS_GROUNDING handoffs until Phase 5 performs web grounding.
  - Keep `INTERVIEWING` as the coarse waiting-user state; detailed progress remains in interview payloads and messages.

requirements-completed:
  - INTERVIEW-01
  - INTERVIEW-02
  - INTERVIEW-03
  - INTERVIEW-04
  - PIPELINE-01

# Metrics
duration: 45min
completed: 2026-05-28
---

## Performance

- **Duration:** 45 min
- **Started:** 2026-05-28T18:45:00Z
- **Completed:** 2026-05-28T19:30:00Z
- **Tasks:** 3
- **Files modified:** 9

## Accomplishments
- Added interview service helpers for roadmap progression, pinned-chat validation, parser fallback, confirmation edits, bulk corrections, all-wrong prompts, final resolution construction, and final confirmation writes.
- Added a grounding stub for packaged/restaurant answers that produces a minimal `NEEDS_GROUNDING` handoff without pulling Phase 5 web tooling forward.
- Wired bot handlers and main startup for interview callback/free-text entry points while preserving `concurrent_updates(False)`.
- Added interview reminder polling using `InterviewSession.last_reminder_at` and `reminder_count`.

## Task Commits

Each task was committed atomically:

1. Task 1: RED interview harness - 15674a8
2. Task 2: GREEN durable interview flow - 6205012
3. Task 3: Prompt wording refactor - 1d6face

## Files Created/Modified
- app/services/interview_service.py - Interview state helpers, confirmation handling, grounding-aware final resolution construction, and shared finalization call.
- app/services/grounding_stub.py - Minimal packaged/restaurant grounding-prep boundary.
- bot/handlers.py - Interview helper exports plus callback/free-text stubs for Telegram wiring.
- bot/main.py - Interview handler registration, reminder task startup/shutdown, and serialized update handling.
- bot/polling.py - One-shot reminder poller for active interview sessions.
- tests/test_interview_flow.py - Interview backbone, edit replay, all-wrong, reminder, grounding prep, and existing-item-id assertions.

## Decisions Made
- Do not add the full SearXNG/Firecrawl grounding loop here; Phase 4 only marks and packages the handoff.
- Preserve existing bot worker style rather than introducing a new queue or framework.
- Use the shared meal resolution service for interview final writes so FoodItem reuse/creation stays centralized.

## Deviations from Plan
- The gsd-executor subagent hit the `gpt-5.3-codex-spark` usage limit before doing work, so implementation was completed inline in the same isolated worktree.

## Issues Encountered
- Existing bot contract tests still encoded Phase 3 direct similarity completion and five startup tasks; they were updated to the Phase 4 reasoning/finalization path and reminder task.

## Next Phase Readiness
- Phase 5 can consume `NEEDS_GROUNDING` prep from packaged/restaurant interview answers.
- Correction and janitor work can build on the durable interview and reminder surfaces.

---
*Phase: 04-reason-interview-learning-loop*
*Completed: 2026-05-28*

## Self-Check: PASSED

- FOUND: .planning/phases/04-reason-interview-learning-loop/04-06-SUMMARY.md
- VERIFIED: `tests.test_interview_flow`
- VERIFIED: adjacent bot, matching, parallel, and reasoning contracts
