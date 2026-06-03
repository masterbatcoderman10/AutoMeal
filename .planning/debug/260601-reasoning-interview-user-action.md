---
status: fixed
trigger: "Live photo advanced past ack but user did not receive the expected classification prompt."
created: 2026-06-01T18:20:00Z
updated: 2026-06-01T18:19:30Z
---

# Debug Session: Reasoning Unsupported Interview Action

## Symptoms

- Expected: After photo ack, the bot should classify/segment/reason and send a useful Telegram confirmation prompt.
- Actual: The live meal reached `INTERVIEWING`, but the user did not see the expected classification/affirmation flow.

## Current Focus

- hypothesis: The meal reasoning contract is too permissive for action fields and the interview state builder treats required
  affirmation prompts as optional approval prompts.
- test: Inspect live DB state and add regressions around unsupported reasoning actions and affirmation question ordering.
- expecting: The model should be constrained to known action values, and `AFFIRMATION_REQUIRED` questions should be asked before
  source-origin follow-ups.
- next_action: Patch schema/prompt and interview question normalization, then rerun affected tests.

## Evidence

- Live meal `a8ba61b5-dc53-4cda-864a-5e287e908f69` accepted the photo and later reached `INTERVIEWING` with 3 segments.
- Direct detect call against the uploaded image returned `{"is_food": true, "confidence": 1.0, "next_action": "segment"}` in 10.40s.
- Reasoning state contained `decision_rationale: "Unsupported action field: INTERVIEW_USER"`.
- The latest interview session had only chicken curry pending; vegetable curry and flatbread were in `NEEDS_SCHEMA_REVIEW`.
- The current prompt was source origin for chicken curry, while `group-2:affirmation` remained pending but was marked `required: false`.

## Resolution

- root_cause: The compressed reasoning contract left routing fields too permissive (`action`, `group_action`, `kind`,
  `question_kind`), so the model emitted unsupported `INTERVIEW_USER`. The interview question normalizer also treated
  `AFFIRMATION` as optional, which allowed required source-origin questions to jump ahead of the required Yes/No affirmation.
- fix: Enumerated model-facing routing fields, explicitly banned legacy action labels in the prompt, preserved required
  `AFFIRMATION` prompts, and normalized confirm choices to deterministic `approve`/`correct` callback ids.
- verification: Full unit suite passed (`247 tests`), ruff passed for changed files, API and bot images rebuilt, and live meal
  `a8ba61b5-dc53-4cda-864a-5e287e908f69` was reset to `MATCHING` and reprocessed. It is now `INTERVIEWING` with message
  `255`, prompt `I think this is Vegetable and egg curry. Is that right?`, all expected required questions pending, and no
  `NEEDS_SCHEMA_REVIEW` groups.
- files_changed: `app/services/reasoning_schema.py`, `app/services/reasoning_service.py`,
  `app/services/interview_service.py`, `tests/test_reasoning_contract.py`, `tests/test_interview_flow.py`.

## Follow-Up: Group Actions Must Compose

- timestamp: 2026-06-01T18:45:00Z
  observation: Treating `group_action` as a scalar collapsed different clarification axes. Only `AFFIRMATION_REQUIRED` and
  `IDENTITY_CLARIFICATION_REQUIRED` are mutually exclusive; source-origin and quantity can be additive.
- fix: Changed model-facing reasoning output to `group_actions: [...]`, added `ASK_SOURCE_ORIGIN`, kept a derived internal
  `group_action` for existing pipeline routing, and expanded the prompt policy to distinguish clear-label affirmation from
  nutrition-relevant identity clarification.
- verification: Full unit suite passed (`249 tests`), ruff passed for changed files, `git diff --check` passed, running API and
  bot containers were hot-patched/restarted through the Docker socket because the Docker CLI was being SIGKILLed by OrbStack,
  and `mealtracker-api:latest` / `mealtracker-bot:latest` image tags were rebuilt through the Docker API.
- live result: Reprocessed meal `a8ba61b5-dc53-4cda-864a-5e287e908f69` now has:
  `Chicken Curry -> AFFIRMATION_REQUIRED`, `Egg and Vegetable Curry -> IDENTITY_CLARIFICATION_REQUIRED`,
  `Flatbread -> IDENTITY_CLARIFICATION_REQUIRED`.

## Follow-Up: Telegram Must Loop Group Actions

- timestamp: 2026-06-01T19:15:00Z
  observation: A scalar `group_action` is only safe as a compatibility projection. Telegram needs to process each food group
  as `food_group -> clarification_actions[]`, because identity/affirmation are mutually exclusive but quantity and source can
  be paired with either.
- fix: Preserved additive `ASK_QUANTITY` and `ASK_SOURCE_ORIGIN` when the primary group action is identity or affirmation,
  and made interview routing consult `group_actions`/`clarification_actions` instead of relying on the scalar projection.
- verification: Added regressions for `IDENTITY_CLARIFICATION_REQUIRED + ASK_QUANTITY + ASK_SOURCE_ORIGIN` on one group and
  for Telegram question ordering across those three actions. Focused reasoning/interview tests passed (`71 tests`), full unit
  suite passed (`250 tests`), ruff passed, `git diff --check` passed, running API/bot containers were hot-patched and restarted,
  image tags `mealtracker-api:latest` and `mealtracker-bot:latest` were rebuilt, and API health returned `{"status":"ok"}`.
