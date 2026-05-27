# Phase 2: Vision Slice - Context

**Gathered:** 2026-05-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Prove the computer-vision path end-to-end for accepted meal photos: classify food vs non-food, segment distinct visible food regions, save accepted crops to disk, run a separate human-readable labeling call for the detected regions, and send a simple Telegram sentence describing what the system sees. This phase does not attempt vector matching, nutrition, grounded reasoning, interview resolution, or final `DiaryEntry` creation.

</domain>

<decisions>
## Implementation Decisions

### Vision Pipeline Shape
- **D-01:** Phase 2 uses **separate model calls** for detect, segment, and human-readable label assignment. Label generation is not bundled into the segmentation response.
- **D-02:** Detect stage is **conservative**. When the classifier is unsure, bias toward skipping rather than processing.
- **D-03:** Non-food images with high-confidence non-food detection **stop silently** — no Telegram message is sent.
- **D-04:** Non-food clutter around a meal is acceptable. If the meal is clearly present anywhere in the image, the pipeline should continue.

### Segment Semantics
- **D-05:** A `MealSegment` represents a **distinct visible food region or container**, not each physical piece. Do not count every chicken piece, grain of rice, or individual bread.
- **D-06:** The same food appearing in two clearly separate places produces **two segments**. Later stages may cluster those segments under the same food label.
- **D-07:** Mixed foods use **dish-level labels** (for example, `chicken curry`, `mixed vegetables`). Simple isolated foods may use **ingredient-level labels** when visually obvious.
- **D-08:** Tiny garnish, small sauces, and other minor extras are **ignored by default** unless they are substantial enough to read as a meaningful side.

### Segmentation Validation & Recovery
- **D-09:** Invalid or partially invalid box sets are treated as a **failed segmentation response**. If any boxes in a response are invalid, reject the whole response rather than keeping the valid subset.
- **D-10:** Segmentation gets **one retry maximum** after a failed or unusable response.
- **D-11:** The retry path should **escalate to a stronger segmentation setup/model**, not merely reuse the same setup with a stricter prompt. The preferred retry model is `google/gemini-3.5-flash`.
- **D-12:** If detect says food but segmentation still produces nothing usable after the stronger-model retry, send a **soft failure message** rather than silently dropping the meal.

### Telegram Result Behavior
- **D-13:** Success output is a **single plain sentence** such as `I see 3 items: pita bread, chicken curry, mixed vegetables.`
- **D-14:** When labels are weak or uncertain, **hedge only those items inline** rather than exposing confidence numbers or debug detail.
- **D-15:** If the same food appears in multiple separate segments, **collapse duplicates in the final sentence** instead of mentioning counts or regions.
- **D-16:** Non-food photos produce **no Telegram message at all**.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Scope & Prior Decisions
- `.planning/ROADMAP.md` — Phase 2 goal, success criteria, and phase note about validating OpenRouter vision + structured output behavior during this phase.
- `.planning/REQUIREMENTS.md` — `VISION-01` through `VISION-04`, plus the wider requirement boundaries showing that match, reasoning, and output phases are later work.
- `.planning/PROJECT.md` — project constraints, model-routing expectations, and core product boundaries.
- `.planning/STATE.md` — current project state and known concerns carried forward into Phase 2.
- `.planning/phases/01-foundation-ingest/01-CONTEXT.md` — locked Phase 1 decisions for bot topology, uploads path conventions, and shared-service layout that Phase 2 must build on.

### Relevant Runtime Code
- `app/config.py` — runtime settings already available for uploads and bot polling.
- `app/main.py` — FastAPI lifespan and scheduler wiring; current app integration surface.
- `app/routers/ingest.py` — ingest entrypoint and current `MealLog(PENDING)` creation flow.
- `app/services/image_service.py` — image transcoding and file-save utilities that crop saving should extend rather than replace.
- `app/services/llm_client.py` — existing OpenRouter chat client abstraction that detect/segment/label calls should reuse.
- `app/models/meal_log.py` — processing-status state machine that Phase 2 will advance through detect and segment steps.
- `app/models/meal_segment.py` — existing schema for labels, bounding boxes, crop paths, embeddings, and later reasoning fields.
- `bot/messages.py` — current bot message tone and formatting baseline.
- `bot/polling.py` — bot polling loop that currently reacts to `PENDING` meals and establishes the DB-driven coordination pattern.

### Example Input
- `sample_images/IMG_4583.HEIC` — concrete user-referenced example of desired grouping behavior: stacked bread as one food, chicken curry as one dish, and sauteed vegetables as one side despite multiple visible pieces.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/services/llm_client.py`: existing chat-completions wrapper for OpenRouter; Phase 2 can add detect, segmentation, and labeling calls without introducing a second chat client.
- `app/services/image_service.py`: existing JPEG transcode and save helpers; crop persistence should extend this module or mirror its path-writing pattern.
- `app/models/meal_segment.py`: already has `label`, `bounding_box`, and `cropped_image_url`, so Phase 2 can populate current schema instead of inventing new tables.
- `bot/messages.py`: current message formatting is intentionally terse; Phase 2 result text should stay simple and human-readable.

### Established Patterns
- Separate bot service with DB-driven coordination from Phase 1 remains the operating pattern; Phase 2 should continue to communicate pipeline outcomes through state transitions and stored data, not service-to-service RPC.
- Upload paths are already container-absolute and volume-backed. Crop paths should follow the locked convention from Phase 1: `/data/uploads/crops/{segment_id}.jpg`.
- The project already distinguishes OpenRouter chat calls from later raw-HTTP embedding calls. Phase 2 should stay on the chat-completions path only.

### Integration Points
- `MealLog.processing_status` is the coordination backbone. Phase 2 planning should define exact transitions through detect/segment/label success and failure states.
- `MealSegment` rows are the natural place to persist accepted boxes, crop paths, and provisional labels before later phases add embeddings and reasoning.
- Telegram result composition should build on the existing bot messaging layer rather than introducing a new output mechanism.

</code_context>

<specifics>
## Specific Ideas

- User wants **grouped food regions**, not atomic object detection. In the sample meal image, stacked bread should read as one food group, the curry plate as one dish, and the vegetable bowl as one side.
- If the same food appears in multiple separate places, separate those as multiple segments first and let downstream logic cluster them later by label.
- Human-readable labels are a **separate concern from segmentation**. Planners should treat label assignment as its own call after boxes/crops are accepted.
- Retry behavior for bad segmentation output should explicitly upgrade the model/setup rather than endlessly polishing the first response.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 2-Vision Slice*
*Context gathered: 2026-05-27*
