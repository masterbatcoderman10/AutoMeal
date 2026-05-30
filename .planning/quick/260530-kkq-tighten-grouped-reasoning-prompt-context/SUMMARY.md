---
quick_id: 260530-kkq
slug: tighten-grouped-reasoning-prompt-context
status: complete
completed: 2026-05-30T10:50:36Z
---

# Summary

Updated grouped reasoning context so model receives stronger task boundaries:
- Isolated food groups only; bread+curry compound grouping is explicitly disallowed unless physically integrated.
- Bread-type scrutiny is mandatory for chapatti/chapati, parota/paratha, khubz, pita, naan, and roti.
- Empty vector context now emits `vector_match_status=NO_VECTOR_CANDIDATES`, an explanatory note, and `top_3_candidates=[]` instead of fake `candidate-0` vector candidates.
- Segmentation prompt now asks for isolated food/component boxes and explicitly forbids compound boxes such as bread+curry or eggs+curry.
- Bot workers release DB transactions before external LLM/Telegram calls, and matching fan-out uses isolated sessions so pgvector queries can run in parallel without sharing one `AsyncSession`.
- Failed reminder sends are marked attempted so stale bad-chat interview sessions stop hammering the logs.

## Live UAT Follow-up

After rebuilding/restarting, meal `bf22787e-b8dd-4f1a-be6e-802bac6d5c45` progressed from stuck `DETECTING` through segmentation, embedding, matching, and reasoning to `INTERVIEWING`.

Observed current caveat: this database is not empty (`food_items=5`, `food_visuals=20`, `diary_entries=14`, `meal_logs=31`), so vector candidates still appear. A clean empty-DB UAT needs truncating/resetting the app tables before the next upload.

## Files Changed

- `app/services/reasoning_service.py`
- `app/services/vision_service.py`
- `bot/polling.py`
- `tests/test_bot_contract.py`
- `tests/test_embed_worker.py`
- `tests/test_match_flow.py`
- `tests/test_reasoning_flow.py`
- `tests/test_vision_service.py`

## Verification

- Targeted prompt tests passed in API container.
- Broader reasoning/smoke suite passed in API container: `tests.test_reasoning_contract tests.test_reasoning_flow tests.test_reasoning_gate tests.test_embed_match_smoke`.
- Bot/matching/vision regression suite passed in API container: `tests.test_bot_contract tests.test_match_flow tests.test_parallel_pipeline tests.test_embed_worker tests.test_reasoning_contract tests.test_reasoning_flow tests.test_reasoning_gate tests.test_embed_match_smoke tests.test_vision_service`.
- Rebuilt and restarted `api` and `bot` with Docker Compose.

## Commit

Not committed here because the worktree already contained unrelated uncommitted execution changes. Only the files above belong to this quick task.
