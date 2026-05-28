---
phase: 04-reason-interview-learning-loop
reviewed: 2026-05-28T18:24:46Z
depth: standard
files_reviewed: 40
files_reviewed_list:
  - app/main.py
  - app/config.py
  - app/models/__init__.py
  - app/models/meal_log.py
  - app/models/meal_segment.py
  - app/models/diary_entry.py
  - app/models/food_visual.py
  - app/models/interview_session.py
  - app/models/interview_message.py
  - app/models/correction_event.py
  - app/services/matching_service.py
  - app/services/reasoning_schema.py
  - app/services/reasoning_service.py
  - app/services/meal_resolution_service.py
  - app/services/taxonomy_service.py
  - app/services/tracing_service.py
  - app/services/interview_service.py
  - app/services/grounding_stub.py
  - app/services/correction_service.py
  - app/services/recovery_service.py
  - bot/handlers.py
  - bot/main.py
  - bot/messages.py
  - bot/polling.py
  - scripts/assert_reasoning_red.py
  - scripts/assert_interview_red.py
  - scripts/assert_fix_red.py
  - scripts/assert_janitor_red.py
  - scripts/embed_match_smoke.py
  - scripts/recovery_smoke.py
  - tests/test_reasoning_contract.py
  - tests/test_reasoning_gate.py
  - tests/test_reasoning_flow.py
  - tests/test_parallel_pipeline.py
  - tests/test_interview_flow.py
  - tests/test_fix_flow.py
  - tests/test_janitor.py
  - tests/test_bot_contract.py
  - tests/test_match_flow.py
  - tests/__init__.py
findings:
  critical: 4
  warning: 2
  info: 0
  total: 6
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-05-28T18:24:46Z
**Depth:** standard
**Files Reviewed:** 40
**Status:** issues_found

## Summary

The Phase 4 source set has multiple end-to-end gaps in the core flows it claims to ship. The biggest defects are in the Telegram interview path, stale-stage recovery, `/fix` wiring, and grounding-required final writes. The unit tests mostly validate helper functions in isolation and do not exercise the failing runtime handoffs between workers, bot handlers, and persistence.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Meals routed to `INTERVIEWING` have no executable interview path

**Classification:** BLOCKER
**File:** `app/services/reasoning_service.py:691-719`, `bot/polling.py:569-603`, `bot/handlers.py:55-66`
**Issue:** When reasoning cannot auto-confirm, `finalize_meal_from_reasoning()` only flips the meal to `INTERVIEWING` and commits it. The match worker then sends a generic unresolved message, but it never creates an `InterviewSession`, never stores prompt state or pending targets, and the Telegram handlers do not load a session or call `finalize_confirmed_interview()`. `interview_callback()` only answers the callback, and `interview_text()` only sends a canned acknowledgement. In practice, unresolved meals dead-end at `INTERVIEWING` and cannot be completed from Telegram.
**Fix:** Persist an `InterviewSession` and initial `InterviewMessage` when the meal first becomes unresolved, store the pending targets/current prompt, and wire both callback and text handlers to load that session, mutate its state, call `finalize_confirmed_interview()` on confirmation, and mark the session inactive after completion.

### CR-02: Janitor recovery can resume to `REASONING`, but no worker consumes that state

**Classification:** BLOCKER
**File:** `app/services/recovery_service.py:133-137`, `app/services/recovery_service.py:387-449`, `bot/main.py:22-65`, `bot/polling.py:505-620`
**Issue:** `select_recovery_target()` chooses `MealProcessingStatus.REASONING` whenever candidate snapshots exist. `run_meal_janitor()` applies that state change, but the bot only starts pollers for `PENDING`, `DETECTING`, `SEGMENTING`, `EMBEDDING`, `MATCHING`, and interview reminders. There is no worker that selects `REASONING` meals. A stale meal recovered from candidate snapshots therefore just sits in `REASONING` until the janitor sees it again and eventually exhausts retries.
**Fix:** Either add a dedicated `REASONING` poller that executes `run_reasoning_request()`/`finalize_meal_from_reasoning()`, or change janitor recovery so candidate-snapshot meals are resumed from a stage that actually has a consumer, such as `MATCHING`, with an idempotent “reasoning-ready” fast path.

### CR-03: `/fix` is not reachable end-to-end

**Classification:** BLOCKER
**File:** `bot/main.py:101-107`, `bot/handlers.py:43-52`, `bot/handlers.py:62-66`
**Issue:** The bot never registers `fix_command`, so `/fix` cannot be invoked. Even if it were registered, `fix_command()` only echoes a target and depends on `context.bot_data["recent_entries"]`, but no reviewed code populates that key. The generic text handler is also hard-wired to the interview stub and never routes replies into `apply_confirmed_entry_correction()`. The correction service exists, but there is no live path that applies it.
**Fix:** Register `CommandHandler("fix", fix_command)`, persist or load recent diary entries for the pinned chat, and implement a correction conversation state that parses the patch, shows the confirmation preview, calls `apply_confirmed_entry_correction()`, commits it, and returns the formatted summary.

### CR-04: Grounding-required confirmations are written as completed meals without any grounding step

**Classification:** BLOCKER
**File:** `app/services/interview_service.py:206-276`, `app/services/meal_resolution_service.py:221-247`, `app/services/grounding_stub.py:18-32`
**Issue:** `final_resolution_from_confirmation()` marks packaged/restaurant answers as `needs_grounding=True`, but `finalize_confirmed_interview()` still writes them through `apply_final_meal_resolution(..., meal_status=COMPLETED)`. `resolve_or_create_food_item()` then persists a `FoodItem` with `llm_reasoning="NEEDS_GROUNDING"` and missing nutrition instead of running a grounding tool call or leaving the meal pending. That breaks the project contract that completed diary entries have resolved nutrition and makes the model/tool boundary a no-op.
**Fix:** Introduce a non-terminal pending-grounding state and defer final completion until grounding finishes, or block completion for `needs_grounding` segments and explicitly run the grounding pipeline before creating `DiaryEntry` rows.

## Warnings

### WR-01: Janitor failure notifications are marked as sent before Telegram delivery succeeds

**Classification:** WARNING
**File:** `app/services/recovery_service.py:185-194`, `app/services/recovery_service.py:434-447`
**Issue:** `enqueue_recovery_notification()` stamps `last_recovery_notified_at` before any Telegram API call happens. `run_meal_janitor()` commits that timestamp and only then sends the message. If `bot.send_message()` fails, the error is logged, but future janitor passes will suppress retries because the meal already looks notified.
**Fix:** Record `last_recovery_notified_at` only after a successful send, or clear/retry the notification marker on failure. A small outbox table is the safest pattern if notification delivery must survive process crashes.

### WR-02: Reasoning fallback model settings are dead configuration

**Classification:** WARNING
**File:** `app/config.py:19-22`, `app/services/reasoning_service.py:380-410`, `app/services/reasoning_service.py:431-509`
**Issue:** The settings define `REASONING_FALLBACK_MODEL` and `REASONING_PARSER_FALLBACK_MODEL`, but the reasoning path never uses them. `_run_reasoning_model()` and `_run_reasoning_parser_retry()` always call a single model, and `run_reasoning_request()` turns any exception into `FAILED_UNCLEAR` instead of retrying the configured fallback. This makes the advertised model boundary less robust than the configuration implies.
**Fix:** On chat-completion or parser failure, retry once with the configured fallback model before returning `FAILED_UNCLEAR`, or remove the unused settings so operators are not misled into thinking fallback is active.

---

_Reviewed: 2026-05-28T18:24:46Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
