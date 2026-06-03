# Phase 2: Vision Slice — Technical Research

**Researched:** 2026-05-27
**Status:** Complete

This document answers the implementation questions needed to plan Phase 2. It resolves how the existing Phase 1 ingest/bot architecture should host the vision pipeline, how OpenRouter multimodal structured-output calls fit the current client abstraction, how Gemini-style `0..1000` boxes should be normalized and validated, how crops should be persisted, and how the phase should be verified against the user-discussed behavior.

---

## 1. Recommended Runtime Topology

### Keep DB-driven coordination in the bot service

Phase 1 already established a reliable coordination pattern:

- `app/routers/ingest.py` creates `MealLog(PENDING)` rows quickly and returns `202`
- `bot/polling.py` claims pending rows, sends the acknowledgement, then advances the row to `DETECTING`
- Telegram delivery already lives in the bot process, so the bot service is the natural place to continue the detect -> segment -> label -> notify workflow

For Phase 2, the lowest-risk extension is:

1. Keep the acknowledgement loop intact for `PENDING -> DETECTING`
2. Add a second background processor in the bot service for `DETECTING` and `SEGMENTING` meals
3. Persist all intermediate state in Postgres so the API still does no heavy work

This avoids adding a new queue or worker role before the project needs one, and it preserves the Phase 1 rule that request handling stays lightweight.

### Reuse existing statuses instead of adding a LABELING enum

The current schema already has:

- `PENDING`
- `DETECTING`
- `SEGMENTING`
- `COMPLETED`
- `FAILED`

Phase 2 does not need a migration just to model the separate label call. The simplest state contract is:

- `PENDING` -> `DETECTING` after ack succeeds
- `DETECTING` -> `COMPLETED` for confident non-food skips
- `DETECTING` -> `SEGMENTING` for accepted meal photos
- `SEGMENTING` -> `COMPLETED` after crops are saved, labels assigned, and Telegram result sent
- `DETECTING` or `SEGMENTING` -> `FAILED` for unrecoverable pipeline failures

The label-assignment call remains a separate step in code, but it happens under the broader `SEGMENTING` status to avoid needless schema churn in this phase.

---

## 2. OpenRouter Vision Call Shape

### Existing client can support Phase 2 with a small extension

`app/services/llm_client.py` already wraps OpenRouter chat completions through `AsyncOpenAI`. Phase 2 needs three capabilities from the same abstraction:

- multimodal `messages` content arrays with image input
- strict `response_format=json_schema` structured outputs
- Gemini provider-specific tuning passed through `extra_body` for thinking level and similar options

The current wrapper already accepts `messages`, `response_format`, and `tools`. The missing piece for Phase 2 is an optional `extra_body` passthrough so detect, segment, and label stages can set provider options without bypassing the shared client.

### Use separate calls for detect, segment, and label

The discuss-phase decisions explicitly require separate model calls:

- detect decides whether the image should continue
- segment proposes distinct food regions
- label assigns human-readable names after accepted crops exist

That split is still the right design even if the provider could theoretically combine some steps. It keeps validation boundaries clear:

- detect can be conservative without entangling box generation
- segment output can be rejected/retried without inventing partial labels
- label can run crop-by-crop on already accepted regions

### Recommended model assignment for this phase

- Detect primary: `google/gemma-4-31b-it`
- Segment primary: `google/gemini-3-flash-preview`
- Segment retry: `google/gemini-3.5-flash`
- Label primary: `google/gemini-3-flash-preview`

The retry-model preference comes from the Phase 2 discussion log and should override the generic roadmap wording for this phase.

---

## 3. Bounding-Box Contract and Validation

### Resolve the `0..1000` vs `[0,1]` mismatch by normalizing immediately

The project docs contain both of these ideas:

- Gemini/OpenRouter box output is expected in normalized `0..1000` coordinates
- Phase 2 success criteria say the application validates boxes within `[0,1]`

These are compatible if the service treats provider output as a raw transport format and immediately converts it to persisted application coordinates:

- raw provider response: `[y0, x0, y1, x1]` in `0..1000`
- stored/validated application box: `[y0, x0, y1, x1]` as floats in `[0,1]`

That gives the planner a clean rule:

1. parse raw integers/floats from the model
2. divide by `1000.0`
3. validate/store only the normalized `[0,1]` values

### Validation rules to enforce

For each normalized box:

- exactly four numeric values
- `0.0 <= y0 < y1 <= 1.0`
- `0.0 <= x0 < x1 <= 1.0`
- area `(y1 - y0) * (x1 - x0) > 0.01`
- count capped at 8 accepted segments per image

If any returned box is invalid, reject the entire segmentation response. The discuss-phase decision explicitly rejects "keep the valid subset" behavior.

### IoU dedupe policy

To satisfy the roadmap success criteria without double-counting distinct placements of the same food:

- compute pairwise IoU on normalized boxes
- if IoU is greater than `0.5`, keep the higher-confidence box
- run dedupe before crop persistence and before label generation

This still allows two separate placements of the same food when they are visually distinct and non-overlapping.

---

## 4. Crop Persistence Strategy

### Extend `image_service.py` rather than creating a parallel image utility

`app/services/image_service.py` already owns:

- raw-byte hashing
- HEIC decoding
- JPEG transcoding
- volume-backed image writes

Phase 2 should add crop-specific helpers there so image handling remains centralized:

- load JPEG bytes into Pillow
- convert normalized box coordinates to pixel bounds
- crop and save JPEGs
- ensure parent directories exist

### Persist crop paths using the Phase 1 convention

The locked convention from Phase 1 context is container-absolute upload paths. For segments, use:

`/data/uploads/crops/{segment_id}.jpg`

This avoids inventing nested per-meal path semantics mid-project and matches the existing `MealSegment.cropped_image_url` field.

### Persist `MealSegment` rows before labeling finishes

Recommended write order:

1. create `MealSegment` row with `meal_log_id` and normalized `bounding_box`
2. save crop and set `cropped_image_url`
3. run label assignment for that segment
4. update `MealSegment.label`

That order is robust against mid-stage crashes and gives later phases a persisted segment record even when labeling fails after crop creation.

---

## 5. User-Facing Output Rules

### Non-food behavior

There is a direct conflict between earlier roadmap wording and the user’s discuss-phase decisions:

- roadmap/requirements say non-food should send a polite skip message
- discuss-phase says confident non-food should stop silently with no Telegram output

For execution, the discuss-phase context should win. That is the more recent, explicit user instruction. Plans should therefore implement:

- acknowledgement still happens earlier in Phase 1 (`Received, processing...`)
- final Phase 2 result message is suppressed for confident non-food images
- no `MealSegment` rows are created for the skip path

### Food result message

Success output should remain a single sentence:

`I see 3 items: pita bread, chicken curry, mixed vegetables.`

Rules derived from context:

- collapse duplicate labels in the final sentence even if multiple segment rows share a label
- hedge weak labels inline only for those items
- do not expose confidence numbers or debug notes
- ignore garnish/minor sauces unless visually substantial

### Soft failure after bad segmentation retry

If detect passes but segmentation fails twice:

- send a short soft-failure message
- mark the meal `FAILED`
- avoid partial result messages built from a corrupted response

This matches the user’s preference for explicit escalation to a stronger model followed by a bounded stop.

---

## 6. Testing and Verification Approach

### Keep using `unittest` for Phase 2

The repo already has working `unittest` suites in `tests/test_ingest_contract.py` and `tests/test_bot_contract.py`. Phase 2 should continue with that test harness instead of introducing pytest mid-stream.

Recommended new coverage:

- `tests/test_vision_service.py`
  - detect-stage schema parsing
  - raw `0..1000` box normalization to `[0,1]`
  - invalid-box rejection
  - IoU dedupe
  - label-collapse helpers
- `tests/test_bot_contract.py`
  - detect worker state transitions
  - non-food silent completion
  - segmentation retry escalation
  - soft-failure message path
  - final sentence delivery for accepted segments

### Capability smoke script belongs in this phase

The roadmap phase note explicitly asks for model-capability verification. Add a live smoke script that exercises:

1. detect call with image + strict schema
2. segment call with image + strict schema
3. label call on one saved crop

The script should print the raw model IDs used, whether structured output parsed cleanly, and the resulting boxes/labels for a sample image. This creates concrete evidence before Phase 3 depends on the same client path.

---

## 7. Validation Architecture

Phase 2 has good Nyquist coverage potential because most logic is deterministic once model responses are mocked or fixture-backed.

### Fast feedback path

- quick command: `.venv/bin/python -m unittest tests.test_vision_service tests.test_bot_contract`
- full suite: `.venv/bin/python -m unittest discover tests`
- target feedback latency: under 20 seconds for the quick path

### Manual-only checks that still matter

- live sample-photo run against the pinned OpenRouter models
- inspection that crop files exist under `/data/uploads/crops/`
- final Telegram wording for the sample image and non-food image

### Wave strategy

- Wave 1 verifies the detect skip path
- Wave 2 verifies crop persistence and simple food-label success
- Wave 3 verifies retry/dedupe/hardening behavior
- Wave 4 verifies the real-model smoke script and updates UAT evidence

---

## 8. Planning Implications

The phase should be planned as four sequential MVP slices:

1. non-food detect gate with silent completion
2. simple food happy path with saved crops and single-sentence result
3. segmentation hardening with retry, IoU dedupe, and duplicate-label collapse
4. live capability smoke coverage and UAT scaffolding

That sequencing respects the project’s MVP mode while avoiding same-wave file conflicts in `bot/polling.py`, `bot/main.py`, `app/services/vision_service.py`, and `tests/test_bot_contract.py`.

---

*Phase: 02-vision-slice*
*Research completed: 2026-05-27*
