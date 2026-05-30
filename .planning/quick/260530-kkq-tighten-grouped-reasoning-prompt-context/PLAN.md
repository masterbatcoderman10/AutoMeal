---
quick_id: 260530-kkq
slug: tighten-grouped-reasoning-prompt-context
status: executing
created: 2026-05-30T10:48:53Z
---

# Tighten Grouped Reasoning Prompt Context

## Goal

Fix UAT prompt/context failures:
- Food groups must be isolated foods/components, not compound bread+curry pairings.
- Bread identity must be scrutinized because chapatti/chapati, parota/paratha, khubz, pita, naan, and roti can materially change nutrition.
- When vector matching has no usable candidates, model context must explicitly say so and must not synthesize fake vector candidates.

## Tasks

1. Add prompt tests for isolated food grouping, bread scrutiny, and no-vector context.
2. Update reasoning prompt to state isolated grouping and bread-type policy.
3. Update per-segment reasoning context to include `vector_match_status` and leave `top_3_candidates` empty when no vector candidates exist.
4. Run targeted reasoning/smoke tests in the API container.

## Verification

- `rtk docker compose --env-file .env --env-file .env.langfuse -f docker-compose.yml -f docker-compose.langfuse.yml run --rm -v "$PWD:/work" -w /work api python -m unittest tests.test_reasoning_flow.ReasoningFlowTests.test_reasoning_prompt_includes_meal_image_crops_and_phase_context tests.test_reasoning_flow.ReasoningFlowTests.test_reasoning_prompt_marks_empty_vector_context_without_fake_candidates`
- `rtk docker compose --env-file .env --env-file .env.langfuse -f docker-compose.yml -f docker-compose.langfuse.yml run --rm -v "$PWD:/work" -w /work api python -m unittest tests.test_reasoning_contract tests.test_reasoning_flow tests.test_reasoning_gate tests.test_embed_match_smoke`
