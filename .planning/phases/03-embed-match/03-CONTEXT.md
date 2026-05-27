# Phase 3: Embed & Match - Context

**Gathered:** 2026-05-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Embed each accepted `MealSegment` crop at 1536 dimensions, search those per-segment vectors against the `FoodVisuals` HNSW cosine index, and when every segment in a meal reaches the similarity threshold, create `DiaryEntry` rows, append new `FoodVisual` rows, mark the meal `COMPLETED`, and push a Telegram nutrition result. This phase proves the seeded visual-vocabulary loop. It does not embed whole meal images for matching, run LLM reasoning, run Telegram interviews, infer portion size, or populate broad nutrition databases.

</domain>

<decisions>
## Implementation Decisions

### Seed Contract
- **D-01:** Production `FoodVisuals` may start empty. Empty index behavior is valid and should not be treated as infrastructure failure.
- **D-02:** Phase 3 UAT uses existing local `sample_images/*.HEIC` as seed material.
- **D-03:** The planner may segment sample images and create 1-2 hardcoded demo `FoodItem` rows with known nutrition values for smoke/UAT. This is a demo seed path only, not a preloaded food database.
- **D-04:** UAT should include both an exact/self-similarity embedding check and a same-food/different-photo similarity check when the sample images allow it.
- **D-05:** Seed helper placement is at agent discretion. A script under `scripts/`, such as `scripts/seed_demo_foods.py`, is appropriate if the planner wants an operator-run UAT helper; reusable helper code for tests is also acceptable.

### Embedding And Matching Semantics
- **D-06:** Matching is strictly per `MealSegment` crop. Do not embed or match the whole meal image for Phase 3 match logic.
- **D-07:** Use `output_dimensionality=1536` for all embeddings. Use `task_type=RETRIEVAL_DOCUMENT` for `FoodVisual` writes and `task_type=RETRIEVAL_QUERY` for segment searches.
- **D-08:** The auto-match threshold remains `score >= 0.85` for SIMILARITY matches.
- **D-09:** No-match or below-threshold match is an expected branch. It should move the meal to `REASONING`, create no `DiaryEntry`, and leave resolution to Phase 4.
- **D-10:** Tests should cover below-threshold match -> `REASONING` with no `DiaryEntry`; this branch is not a Phase 3 failure.
- **D-11:** On no-match, send one transparent Telegram note that the meal was seen but is not known yet and will need future identification/interview capability.
- **D-12:** If any segment in a meal is unresolved, hold all `DiaryEntry` creation for that meal. Do not create partial diary entries for matched segments while any segment remains unmatched.

### Portion And Nutrition Defaults
- **D-13:** Every Phase 3 similarity-created `DiaryEntry` uses `portion_bucket=STANDARD`.
- **D-14:** Telegram output should not caveat that the portion is defaulted or assumed.
- **D-15:** Treat `FoodItem` calories/macros as standard-portion values directly. Do not scale from `serving_size_g` in Phase 3.
- **D-16:** Telegram nutrition output uses only fields already present on matched `FoodItem` rows. Omit missing nutrition fields and never invent values.

### Telegram Result Shape
- **D-17:** For Phase 3 dev/UAT clarity, include identification method and verified flag in the Telegram meal result. Later UX phases may hide this if it feels noisy.
- **D-18:** Use a two-line per-item style for partial nutrition fields: item identity/status on one line, known nutrition fields on the next.
- **D-19:** Include a total line for known summed fields only. Sum calories/macros when present; omit unavailable totals.
- **D-20:** Keep the result user-facing and terse. Do not expose embedding scores, raw vector details, or debug traces in Telegram.

### FoodVisual Write-Back
- **D-21:** For a fully resolved similarity-matched meal, append a new `FoodVisual` for every auto-matched segment.
- **D-22:** Duplicate confirmations of the same food create multiple `FoodVisual` rows. Do not dedupe same-food visuals in Phase 3.
- **D-23:** If any segment is unmatched and the meal moves to `REASONING`, do not append new `FoodVisual` rows for the matched segments yet.
- **D-24:** For fully matched meals, write `DiaryEntry` rows, write new `FoodVisual` rows, and transition `MealLog.processing_status` to `COMPLETED` in the same database transaction.
- **D-25:** Telegram notification success should not be required for the database transaction to commit.

### Agent Discretion
- The planner may choose the exact seed helper shape and filename.
- The planner may decide whether the embedding/match logic lives in new service modules or in the existing polling module first, as long as the resulting design follows the repo's status-driven worker pattern.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Scope And Prior Decisions
- `.planning/ROADMAP.md` — Phase 3 goal, success criteria, threshold, calibration note, and boundary against reasoning/interview phases.
- `.planning/REQUIREMENTS.md` — `MATCH-02` through `MATCH-04`, plus output and later-phase boundaries.
- `.planning/PROJECT.md` — core product value, OpenRouter-only constraint, and pipeline shape.
- `.planning/STATE.md` — current project decisions and carried concerns, including embedding calibration and raw httpx embedding path.
- `.planning/phases/01-foundation-ingest/01-CONTEXT.md` — locked schema, `vector(1536)`, HNSW index, upload path conventions, and bot/DB coordination pattern.
- `.planning/phases/02-vision-slice/02-CONTEXT.md` — segment semantics, crop persistence, and Phase 2 output decisions that Phase 3 builds on.

### Relevant Runtime Code
- `app/services/llm_client.py` — existing OpenRouter dual path; `embed_multimodal()` is the raw httpx embedding surface to extend/validate.
- `app/models/meal_segment.py` — `MealSegment.embedding`, crop path, bounding box, label, and portion bucket fields.
- `app/models/food_visual.py` — `FoodVisual.embedding`, invalidation flag, and HNSW cosine index configuration.
- `app/models/food_item.py` — nutrition fields and verification flag used by Phase 3 seeded matches.
- `app/models/diary_entry.py` — target diary row schema for similarity-created entries.
- `app/models/meal_log.py` — processing statuses including `EMBEDDING`, `MATCHING`, `REASONING`, `COMPLETED`, and `FAILED`.
- `bot/polling.py` — existing status-driven worker loop pattern for ack, detect, and segment stages.
- `bot/messages.py` — current terse Telegram message style to extend for Phase 3 nutrition/no-match output.
- `migrations/versions/001_initial_schema.py` — concrete database schema and HNSW index DDL.

### UAT Inputs
- `sample_images/*.HEIC` — local sample photos used as demo seed material for Phase 3 smoke/UAT. These are local/untracked and may need copying into isolated worktrees before live UAT.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `OpenRouterClient.embed_multimodal()` already posts to `/embeddings` through `httpx`; Phase 3 should harden/validate this instead of adding a second embedding client.
- `MealSegment.embedding` already uses `Vector(1536)`, so per-crop embeddings can persist without schema changes.
- `FoodVisual` already has the HNSW cosine index and `is_invalidated` flag.
- `FoodItem` already carries the seeded nutrition fields Phase 3 needs for UAT messages.
- `DiaryEntry` already has `portion_bucket`, `identification_method`, and `is_verified` fields for Phase 3 writes.

### Established Patterns
- The bot process currently owns DB-driven worker loops using `SELECT ... FOR UPDATE SKIP LOCKED`; Phase 3 should likely add worker handling for `EMBEDDING`/`MATCHING` rather than introducing a new queue.
- Stored image and crop paths are absolute container paths under `/data/uploads`; embedding should read `MealSegment.cropped_image_url`.
- Phase 2 intentionally created grouped food segments, so Phase 3 should match those grouped constituents rather than split them further.
- Telegram output should remain terse and human-facing, with dev/UAT audit fields included only because Phase 3 needs easier verification.

### Integration Points
- `MealLog.processing_status` is the coordination backbone. Phase 3 needs exact transitions from post-segmentation into embedding/matching, then `COMPLETED` or `REASONING`.
- Similarity search should query non-invalidated `FoodVisual` rows only.
- Fully matched meals should atomically write `DiaryEntry` and new `FoodVisual` rows before setting `MealLog` to `COMPLETED`.
- No-match messages and nutrition result messages should live in `bot/messages.py` or a similarly small formatting surface.

</code_context>

<specifics>
## Specific Ideas

- User explicitly corrected that only segments/constituents get embeddings; whole meal embeddings are not part of match logic.
- Sample photos are acceptable as the seed starting point even though the exact number of generated segments is not known before running segmentation.
- Hardcoded demo nutrition is acceptable only for Phase 3 smoke/UAT; it should not become a broad nutrition source.
- Development output may include method and verified flag now to make UAT easier, even if later user-facing UX hides it.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 3-Embed & Match*
*Context gathered: 2026-05-27*
