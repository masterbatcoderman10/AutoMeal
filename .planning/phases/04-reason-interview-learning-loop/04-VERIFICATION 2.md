---
phase: 04-reason-interview-learning-loop
verified_at: 2026-05-28T19:35:11Z
status: issues_found
summary: "Reasoning, correction, post-interview grounding, and janitor plumbing exist, but Phase 04's goal is not fully achieved because the live interview flow skips the promised structured roadmap, `/fix` does not reopen an interview session, and the per-meal portion output contract is not met."
findings:
  - severity: blocker
    title: "Structured interview flow is not implemented in the live handler path"
    evidence:
      - "app/services/interview_service.py:88 advances directly to `CONFIRMATION` after the last target answer."
      - "app/services/interview_service.py:236-264 initializes only `INITIAL_QUESTION` state; no runtime transition code exists for `FOOD_NAME`, `SOURCE_TYPE`, `BRAND_NAME`, `RESTAURANT_NAME`, or `PORTION_CONTEXT`."
      - "bot/handlers.py:397-418 only asks `current_target_question()` and then either repeats that prompt or shows confirmation."
      - "Custom probe: `rtk .venv/bin/python -c ...` returned `next_step='CONFIRMATION'` immediately after a single answer."
    impact: "Phase 04 success criterion 4 and INTERVIEW-02/03 are not delivered by the current bot flow."
    recommended_fix: "Implement real step transitions for SOURCE_TYPE, branch-specific BRAND/RESTAURANT questions, and PORTION_CONTEXT before confirmation, and persist the structured answers into InterviewSession/InterviewMessage payloads."
  - severity: blocker
    title: "`/fix` applies a separate pending patch flow instead of reopening the interview flow"
    evidence:
      - "bot/handlers.py:71 stores `context.bot_data['pending_fix']` instead of creating or resuming an InterviewSession."
      - "bot/handlers.py:207-252 consumes free-text corrections through `_handle_pending_fix()` and previews a direct patch confirmation."
      - "app/services/correction_service.py:207-280 directly mutates the DiaryEntry/FoodVisual path through `apply_confirmed_entry_correction()`."
      - "No `/fix` path imports or creates `InterviewSession` in bot/handlers.py."
    impact: "Phase 04 success criterion 6 and OUTPUT-07 are not met as specified; the user can correct entries, but not by re-entering the structured interview loop for that segment."
    recommended_fix: "Route `/fix` through the same InterviewSession-backed state machine used for unresolved meals, seeded with the existing segment/entry context."
  - severity: blocker
    title: "Per-meal portion output does not match the discrete bucket UX contract"
    evidence:
      - "bot/messages.py:172-189 renders `portion=SMALL|STANDARD|LARGE` and passes through arbitrary `qty=` text."
      - "Custom probe: `format_match_completion_message([CompletionItem(..., portion_bucket='SMALL', quantity_label='0.63x')])` produced `Dal | portion=SMALL | method=INTERVIEW | verified=true | qty=0.63x`."
      - "No formatter emits the roadmap wording `~small portion`."
    impact: "Phase 04 success criterion 5 is not delivered in the user-facing meal result message."
    recommended_fix: "Normalize completion messaging to bucket phrasing (`~small portion`, `~standard portion`, `~large portion`) and stop surfacing free-form multiplier strings in the result message."
  - severity: warning
    title: "Janitor default stale threshold is 5 minutes, not the roadmap's 10 minutes"
    evidence:
      - "app/config.py:28-30 sets `STALE_TIMEOUT_MINUTES = 5`."
      - "app/services/recovery_service.py:396 reads that 5-minute default."
      - "tests/test_janitor.py:25 and 48-80 encode `stale_minutes=5` / 6-minute stale fixtures."
    impact: "Recovery exists and will still trigger by 10 minutes, but the shipped default behavior diverges from the stated contract."
    recommended_fix: "Align the default env/config and tests to the promised 10-minute threshold, or explicitly amend the roadmap/requirements if 5 minutes is intentional."
  - severity: warning
    title: "Phase metadata is marked MVP, but the phase goal is not a valid user story"
    evidence:
      - "`gsd-sdk query user-story.validate --story \"<Phase 04 goal>\"` returned `valid=false` with errors `Must begin with \"As a \"`, `Must contain \", I want to \"`, and `Must contain \", so that \".`"
    impact: "The formal MVP user-flow verifier contract cannot be applied cleanly to this phase metadata."
    recommended_fix: "Either convert the Phase 04 goal to a real user story or remove `mode: mvp` for this roadmap entry."
tests_run:
  - "rtk .venv/bin/python -m unittest -q tests.test_reasoning_gate tests.test_fix_flow tests.test_janitor tests.test_bot_contract.PollingTests.test_post_interview_grounding_worker_runs_reasoning_and_closes_completed_handoff tests.test_bot_contract.PollingTests.test_interview_reminder_worker_skips_grounding_pending_sessions  # Ran 23 tests, OK"
  - "rtk .venv/bin/python -m unittest -q tests.test_interview_flow tests.test_bot_contract.HandlerTests.test_interview_text_confirm_finishes_confirmation_state tests.test_bot_contract.HandlerTests.test_interview_text_confirm_queues_grounding_handoff  # Ran 15 tests, OK"
  - "rtk .venv/bin/python -c \"from bot import handlers; ...\"  # Confirmed live interview state jumps from INITIAL_QUESTION to CONFIRMATION after one answer"
  - "rtk .venv/bin/python -c \"from bot.messages import CompletionItem, format_match_completion_message; ...\"  # Confirmed user-facing output still shows `portion=SMALL` and `qty=0.63x`"
  - "rtk gsd-sdk query user-story.validate --story \"<Phase 04 goal>\"  # Returned valid=false"
---

# Phase 04 Verification

## Verdict

Phase 04 is **not complete** against its roadmap contract.

The current codebase does contain substantial Phase 04 infrastructure:

- meal-level reasoning exists and persists `top_3`/gate output into `MealSegment.ai_reasoning` and `MealLog.reasoning_state_json` (`app/services/reasoning_service.py:509-778`);
- bounded per-segment match fan-out exists via a configurable semaphore (`bot/polling.py:1071-1082`, `bot/polling.py:920-932`);
- post-interview grounding handoffs now have a live consumer that rebuilds candidate context and re-enters reasoning/finalization (`bot/polling.py:483-645`);
- correction application invalidates the linked `FoodVisual` and appends a `CorrectionEvent` (`app/services/correction_service.py:207-280`);
- APScheduler janitor wiring and stale-meal recovery logic exist (`app/main.py:17-47`, `app/services/recovery_service.py:387-460`).

Those pieces are real, but they do **not** add up to the promised end-user loop because the live interview and fix flows are still materially short of the contract.

## What Verified

### Reasoning and state persistence

- `evaluate_reasoning_gate()` uses similarity, top-1/top-2 margin, missing evidence, and nutrition impact rather than raw self-reported confidence alone (`app/services/reasoning_service.py:214-294`).
- `persist_reasoning_results()` writes structured reasoning state to both meal and segment records, including `top_3`, `decision_rationale`, `gate_reason`, and `trace_id` (`app/services/reasoning_service.py:552-638`).

### Parallel continuation and post-interview grounding

- Matching runs one task per segment behind a semaphore (`bot/polling.py:1071-1082`, `bot/polling.py:920-932`), so sibling segments can progress independently.
- Grounding handoffs are acknowledged separately and then consumed by `poll_post_interview_grounding()` (`bot/polling.py:406-480`, `bot/polling.py:483-645`).

### Correction and janitor plumbing

- Identity corrections invalidate only the linked visual and log a correction event (`app/services/correction_service.py:228-280`).
- Janitor recovery reuses artifacts in priority order: active interview, candidate snapshots, embeddings, then crops (`app/services/recovery_service.py:118-165`, `205-275`).
- Janitor scheduling is wired once inside FastAPI lifespan with `max_instances=1` and `coalesce=True` (`app/main.py:31-40`).

## Findings

### 1. Structured interview flow is still a placeholder state machine

The roadmap requires `INITIAL_QUESTION -> FOOD_NAME -> SOURCE_TYPE -> (RESTAURANT_NAME | BRAND_NAME) -> PORTION_CONTEXT -> CONFIRMATION`.

What the live code does:

- `prepare_interview_session()` starts at `INITIAL_QUESTION` (`app/services/interview_service.py:236-264`).
- `complete_target_question()` only increments `current_target_index` and, once targets are exhausted, sets `roadmap_step = "CONFIRMATION"` (`app/services/interview_service.py:72-89`).
- `interview_text()` either asks `current_target_question()` again or renders confirmation; it has no branch that asks for `SOURCE_TYPE`, `BRAND_NAME`, `RESTAURANT_NAME`, or `PORTION_CONTEXT` (`bot/handlers.py:397-418`).

Probe evidence:

```python
{'first_prompt': {'segment_id': 'seg-1', 'label': 'Dal', 'prompt': 'What is Dal?'},
 'next_step': 'CONFIRMATION',
 'current_target_index': 1,
 'messages': [{'role': 'user', 'payload': {'segment_id': 'seg-1', 'value': 'Dal'}}]}
```

That is a direct contradiction of the promised interview flow.

### 2. `/fix` does not reopen the interview flow

The roadmap says `/fix <entry_id>` should reopen the interview for the segment.

What the live code does:

- `fix_command()` records `pending_fix` in `context.bot_data` and asks for free-text correction (`bot/handlers.py:60-76`).
- `_handle_pending_fix()` parses the next text as a patch preview, then `confirm` calls `apply_confirmed_entry_correction()` directly (`bot/handlers.py:207-252`).
- No `/fix` path creates, resumes, or mutates `InterviewSession`.

So correction exists, but it is a separate lightweight patch flow, not a reopened InterviewSession-backed interview.

### 3. User-facing portion output contract is unmet

The roadmap requires discrete bucket phrasing like `~small portion`, never raw multiplier wording like `0.63x`.

Current formatter behavior:

- `format_match_completion_message()` emits `portion=SMALL|STANDARD|LARGE` plus any arbitrary `qty=` string (`bot/messages.py:172-189`).
- A direct probe produced:

```text
Dal | portion=SMALL | method=INTERVIEW | verified=true | qty=0.63x
Nutrition: unavailable
```

That is not the promised UX.

### 4. Janitor threshold default diverges from the contract

Recovery is implemented, but the default stale timeout is `5` minutes, not `10` (`app/config.py:28-30`). The janitor tests also encode the 5-minute assumption (`tests/test_janitor.py:25`, `48-80`).

This is not the main reason Phase 04 fails, but it is still contract drift.

## Commands Run

- `rtk .venv/bin/python -m unittest -q tests.test_reasoning_gate tests.test_fix_flow tests.test_janitor tests.test_bot_contract.PollingTests.test_post_interview_grounding_worker_runs_reasoning_and_closes_completed_handoff tests.test_bot_contract.PollingTests.test_interview_reminder_worker_skips_grounding_pending_sessions`
  Result: `Ran 23 tests ... OK`
- `rtk .venv/bin/python -m unittest -q tests.test_interview_flow tests.test_bot_contract.HandlerTests.test_interview_text_confirm_finishes_confirmation_state tests.test_bot_contract.HandlerTests.test_interview_text_confirm_queues_grounding_handoff`
  Result: `Ran 15 tests ... OK`
- `rtk .venv/bin/python -c "from bot import handlers; ..."`
  Result: confirmed the live interview state advances straight to `CONFIRMATION`
- `rtk .venv/bin/python -c "from bot.messages import CompletionItem, format_match_completion_message; ..."`
  Result: confirmed user-facing output still allows `qty=0.63x`
- `rtk gsd-sdk query user-story.validate --story "<Phase 04 goal>"`
  Result: `valid=false`

## Overall Assessment

Phase 04 has real implementation progress and the recent janitor/post-grounding fixes are present in code, but the current codebase still misses core observable truths from the phase contract. The phase should **not** be treated as complete until the live interview flow, `/fix` routing, and portion-output behavior are brought in line with the roadmap.
