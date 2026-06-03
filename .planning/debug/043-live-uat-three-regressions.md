---
status: fixed
trigger: "04.3 live UAT surfaced three regressions: malformed choice options, grounding queued unexpectedly, and final Telegram result showed Unknown food entries."
created: 2026-06-01T08:16:13Z
updated: 2026-06-01T09:36:00Z
---

# Debug Session: 04.3 Live UAT Three Regressions

## Symptoms

- Expected: Deterministic Telegram options are short, distinct food choices; no option should be the whole question text.
- Actual: Vegetable curry and khubz options collapsed to one long option, and one option was the question itself.
- Expected: After confirmation, the meal should either finalize with named diary entries or explicitly remain pending for actual grounding work without sending Unknown food results.
- Actual: Bot sent `Meal 65f24c6b still needs brand or restaurant grounding...` and later sent three `Unknown food` entries.
- Reproduction: Blank-state 04.3 live UAT meal `65f24c6b-719a-4ec5-877f-604e9641bbd9`.

## Current Focus

- hypothesis: Clarification choice normalization is too trusting of model-emitted `choices`, finalizer/grounding handoff loses confirmation item names, and completion formatting falls back to `Unknown food` from missing/anonymous FoodItems.
- test: Inspect persisted meal reasoning state, interview answers, confirmation items, diary entries, and bot logs.
- expecting: Evidence should show whether names are missing before finalization, lost during grounding, or lost during completion formatting.
- next_action: Gather current DB/log evidence, then add focused regressions before code changes.

## Evidence

- DB state for meal `65f24c6b-719a-4ec5-877f-604e9641bbd9` showed interview `confirmation_items` had specific names:
  `Chicken Drumstick Curry (Phaal)`, `Egg and Bottle Gourd Curry`, and `White Khubz / Pita`.
- The final `food_items`/`diary_entries` were written with generic names:
  `Chicken drumstick curry`, `Egg and gourd curry`, and `Khubz / Pita Bread`.
- Langfuse trace `7d620f12ba509f3bb129a6bcbb886dee` showed the original reasoning model emitted usable
  `clarification_schema.choices`, but the persisted deterministic prompts used `question_examples` as choices.
- Langfuse trace `b0a2fad63e379a05baab946abdeebf7f` showed the interview resolver preserved the corrected names.
- Langfuse trace `e2f36d6b0c3c5af07ec6deafc9f168d7` showed post-interview grounding received confirmed candidate labels,
  but `reasoning_service._prefer_reasoning_group_labels` replaced the selected candidate label with the generic group label before final write.
- Warm-embedding resend `24673c12-a59c-4c3f-8d45-c5f42e6071d6` auto-completed with no interview, but final diary rows collapsed
  to generic `egg and vegetable curry`, `flatbread`, and `chicken curry`; the reasoning state had selected the specific vector labels.
- The bad auto-confirm write mutated the learned `food_items` behind the vector IDs to generic `vector_match` identities.
- Warm-embedding resend `e1de5710-aaf4-405f-b05f-c9b13a10be74` then entered interview because duplicate active visuals for the same
  learned food made the gate compare top-1 vs top-2 duplicate identities and treat the margin as too narrow. The first prompt also had
  duplicate choices such as two identical `chicken drumstick in a curry called phaal` buttons.

## Eliminated

- Completion-message formatting was not the primary cause of generic rows; the persisted `food_items` were already generic.
- The interview resolver did not lose the user's corrections.
- The vector matcher had the correct embeddings and labels; the remaining issues were final-write mutation and gate/choice handling
  of duplicate learned visual rows.

## Resolution

- root_cause: Reasoning gate discarded model-provided clarification choices and derived choices from `question_examples`.
  Post-interview grounding then overwrote authoritative confirmed candidate labels with generic group labels. Warm vector re-use also let
  final writes mutate learned `food_items`, and the confidence-margin gate did not collapse duplicate candidate identities before comparing margin.
- fix: Preserve model `clarification_schema` when present, prefer `top_3` labels over question examples for fallback choices,
  and do not overwrite high-confidence HOME/PACKAGED/RESTAURANT candidate labels during finalization. Preserve more-specific vector-match
  labels over generic group labels, do not mutate direct learned food items on vector-match reuse, compare confidence margin against
  distinct candidate identities, and dedupe clarification choices. Updated grounding handoff text to say packaged/restaurant grounding.
- verification: Added regressions and ran `python -m unittest tests.test_reasoning_gate tests.test_match_flow tests.test_interview_flow tests.test_bot_contract -q` successfully.
  `uvx ruff check` also passed for the changed Python files. A follow-up live run showed the completion message still rendered
  `Unknown food` because Telegram formatting read from stale match results instead of written diary-entry food relationships, and blank-state
  no-vector visual-only candidates could still auto-confirm. Added regressions for both, fixed them, rebuilt/restarted API and bot on blank
  `mealttracker_uat_042_clean`, and resent `IMG_4646.HEIC` as meal `e6519fc1-9732-451d-ae40-188614ab1787`. The meal is now `INTERVIEWING`
  with real choices for vegetable curry and bread. After warm-embedding fixes, rebuilt API image `693bd1a924f...` and bot image
  `a16194ccca...`, repaired the three learned UAT food-item identities in place, and resent `IMG_4646.HEIC` as
  `9c89ca2b-3ee0-42c6-87b7-46f47c66e720`; it completed with zero interview sessions and three specific `AUTO_CONFIRM` diary rows.
- files_changed: `app/services/reasoning_service.py`, `app/services/meal_resolution_service.py`, `bot/messages.py`, `bot/polling.py`,
  `tests/test_reasoning_gate.py`, `tests/test_match_flow.py`, `tests/test_bot_contract.py`.
