---
status: complete
quick_id: 260601-gf9
slug: add-telegram-other-option-for-determinis
completed: 2026-06-01T07:54:23Z
---

# Quick Task 260601-gf9 Summary

## Result

Added a Telegram `Other` path for deterministic identity-style clarification buttons.

## Changes

- Added shared callback helpers for compact tokens and `Other` eligibility.
- Added `Other` buttons to deterministic `single_choice` identity prompts in both kickoff and follow-up renderers.
- Added callback handling that asks for typed input and records the next text answer against the original question.
- Redeployed the bot and resent the active prompt for meal `923cd810-c507-432a-be37-cc856760914d` as Telegram message `148`.
- Live UAT used `Other` for the flatbread identity, recorded `White khubz`, and advanced the interview to `CONFIRMATION`.

## Verification

- `rtk ./.venv/bin/python -m unittest tests.test_bot_contract.HandlerTests.test_start_meal_interview_turn_adds_other_button_for_single_choice_identity tests.test_bot_contract.HandlerTests.test_interview_callback_other_prompts_for_free_text_on_same_question tests.test_bot_contract.HandlerTests.test_meal_interview_text_after_other_records_custom_answer_for_original_question -q` -> `OK`
- `rtk ./.venv/bin/python -m unittest tests.test_bot_contract tests.test_interview_flow tests.test_interview_schema -q` -> `Ran 92 tests ... OK`
