# Phase 04: Telegram fix/correction flow

---
phase: 04-reason-interview-learning-loop
plan: 07
subsystem: bot
tags: [corrections, telegram, visual-learning]

requires:
  - phase: 04-interview-flow
    provides: confirmation-first Telegram interaction patterns
provides:
  - /fix target resolution and correction patch parsing
  - correction diff preview and confirm/cancel semantics
  - scoped visual invalidation for identity fixes
  - quantity-only fixes without visual invalidation
affects:
  - 04-reason-interview-learning-loop

key-files:
  created:
    - app/services/correction_service.py
    - scripts/assert_fix_red.py
  modified:
    - bot/handlers.py
    - bot/messages.py

requirements-completed:
  - INTERVIEW-05
  - INTERVIEW-06

completed: 2026-05-28
---

## Accomplishments
- Added the `/fix` correction service with direct/recent target resolution, diff previews, confirm/cancel behavior, scoped visual invalidation, correction history payloads, and grounding prep for packaged/restaurant corrections.
- Added bot handler hooks and a terse side-effect confirmation message.
- Preserved the identity-vs-quantity split: identity fixes invalidate only the linked visual; quantity fixes recompute nutrition without visual learning.

## Task Commits
- 497d942 test(04-07): add fix red harness
- 68870d4 feat(04-07): add correction service and fix hooks

## Verification
- `rtk /Users/mali/Documents/Projects/MealTracker/.venv/bin/python -m unittest tests.test_fix_flow -q`
- `rtk /Users/mali/Documents/Projects/MealTracker/.venv/bin/python -m unittest tests.test_fix_flow tests.test_interview_flow tests.test_bot_contract -q`
- `rtk /Users/mali/Documents/Projects/MealTracker/.venv/bin/python -m py_compile app/services/correction_service.py bot/handlers.py bot/messages.py`

## Deviations
- Implemented inline in an isolated worktree because the configured gsd-executor model was rate-limited.
