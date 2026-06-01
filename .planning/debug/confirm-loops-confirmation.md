---
status: resolved
trigger: "Typing confirm at the 04.3 Telegram confirmation message repeats the confirmation request instead of saving the meal."
created: 2026-06-01T08:00:00Z
updated: 2026-06-01T09:52:00Z
---

# Debug Session: Confirm Loops Confirmation

## Symptoms

- Expected: Typing `confirm` while the meal interview is at `CONFIRMATION` finalizes the meal and closes the active interview.
- Actual: The bot sends the same confirmation request again and again.
- Error messages: No bot container error observed.
- Timeline: Started during live 04.3 UAT after deterministic clarification reached `CONFIRMATION`.
- Reproduction: Meal `923cd810-c507-432a-be37-cc856760914d`, active session in `mealttracker_uat_042_clean`, type `confirm` in Telegram.

## Current Focus

- hypothesis: `interview_text()` routes deterministic meal sessions to `_handle_deterministic_meal_text()` before checking `roadmap_step == "CONFIRMATION"`, so `confirm` is parsed as another deterministic answer/edit instead of finalization.
- test: Add a bot contract regression where a deterministic `QUESTION_BATCH` state has advanced to `CONFIRMATION` and `confirm` must call `finalize_confirmed_interview()`.
- expecting: Current code repeats confirmation and does not call the finalizer.
- next_action: Write RED regression, then move/narrow routing so confirmation finalization wins over deterministic question handling.

## Evidence

- timestamp: 2026-06-01T08:00:00Z
  observation: Live DB shows meal `923cd810-c507-432a-be37-cc856760914d` at `INTERVIEWING`, session `CONFIRMATION`, `is_active=true`, last bot message id `151`.
- timestamp: 2026-06-01T08:00:00Z
  observation: Confirmation state still contains deterministic `question_order`, `questions_by_id`, and `answers_by_question_id`, so `_is_deterministic_meal_interview(state)` remains true.

## Eliminated

- hypothesis: Telegram transport failed.
  reason: Bot sent repeated confirmation messages and logs show no runtime error.

## Resolution

- root_cause: `interview_text()` routed deterministic meal sessions through `_handle_deterministic_meal_text()` before checking `roadmap_step == "CONFIRMATION"`. Deterministic confirmation state still includes `questions_by_id`, so `confirm` was treated as text inside the deterministic flow and the confirmation message was re-rendered.
- fix: Narrow deterministic text routing to non-confirmation states: `state.get("roadmap_step") != "CONFIRMATION" and _is_deterministic_meal_interview(state)`.
- verification: `tests.test_bot_contract.HandlerTests.test_interview_text_confirm_finalizes_deterministic_confirmation_state` fails before the fix and passes after; broader `tests.test_bot_contract tests.test_interview_flow tests.test_interview_schema` passes with 93 tests. Live handler invocation finalized meal `923cd810-c507-432a-be37-cc856760914d`.
- files_changed:
  - `bot/handlers.py`
  - `tests/test_bot_contract.py`

## Follow-Up: Optional Approval Prompt Skipped

- timestamp: 2026-06-01T09:43:04Z
  observation: Partial-match meal `d883c4a4-91c1-4501-839a-dfdfe4a55154` reached `QUESTION_BATCH` with
  `pending_question_ids=["chicken_curry_group:confirm"]` and `remaining_required_question_ids=[]`.
- symptom: Bot sent `I couldn't safely apply that answer yet. Please answer the same meal question again:
  I likely have Chicken Curry with Drumstick. Is that right?` without visible Yes/No buttons.
- evidence: `last_turn_error` was `ready_to_confirm approved group chicken_curry_group without explicit user confirmation`.
- root_cause: deterministic text/callback handlers called `_resolve_deterministic_confirmation()` when required questions were empty,
  even if optional approval questions were still pending.
- fix: resolve only when all `pending_question_ids` are empty; otherwise render the next pending prompt with its inline keyboard.
- verification: Added `test_interview_callback_rerenders_pending_optional_confirm_after_required_choice`; targeted callback tests pass,
  full affected suite passes with 119 tests, and ruff passes.
- live recovery: Rebuilt/restarted bot image `b2e5485060cb...`, sent a fresh Telegram Yes/No prompt for
  `chicken_curry_group:confirm`, and updated `last_bot_message_id` to `217`.
