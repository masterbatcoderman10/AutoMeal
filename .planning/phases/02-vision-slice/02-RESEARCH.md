# Phase 2: Vision Slice - Technical Research

**Researched:** 2026-05-27
**Domain:** Vision pipeline for meal ingestion and Telegram result synthesis
**Confidence:** MEDIUM

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
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
- `.planning/REQUIREMENTS.md` — `VISION-01` through `VISION-04`.
- `.planning/PROJECT.md` — project constraints, model-routing expectations, and core product boundaries.
- `.planning/STATE.md` — current project state and known concerns carried forward into Phase 2.
- `.planning/phases/01-foundation-ingest/01-CONTEXT.md` — locked Phase 1 decisions for bot topology, uploads path conventions, and shared-service layout that Phase 2 must build on.

### Relevant Runtime Code
- `app/config.py` — runtime settings already available for uploads and bot polling.
- `app/main.py` — FastAPI lifespan and scheduler wiring.
- `app/routers/ingest.py` — ingest entrypoint and current `MealLog(PENDING)` creation flow.
- `app/services/image_service.py` — image transcoding and file-save utilities that crop saving should extend rather than replace.
- `app/services/llm_client.py` — existing OpenRouter chat client abstraction that detect/segment/label calls should reuse.
- `app/models/meal_log.py` — processing-status state machine that Phase 2 will advance through detect and segment steps.
- `app/models/meal_segment.py` — existing schema for labels, bounding boxes, crop paths, embeddings, and later reasoning fields.
- `bot/messages.py` — current bot message tone and formatting baseline.
- `bot/polling.py` — bot polling loop that currently reacts to `PENDING` meals and advances processing status.
</canonical_refs>

### Deferred Ideas
## Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</deferred>
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| VISION-01 | Detect stage classifies image as food vs not-food | Requires explicit detect contract, conservative threshold policy, and status gate before any segment work |
| VISION-02 | NOT_FOOD photos skip the rest of the pipeline and produce no final result message | Requires explicit pipeline branch policy and final-message suppression path |
| VISION-03 | Segment stage outputs normalized `[y0,x0,y1,x1]` boxes, validation, and IoU dedupe | Requires normalization + full-response validation + pairwise IoU suppression order |
| VISION-04 | Each accepted segment is cropped and persisted to disk | Requires crop persistence function and stable `MealSegment.cropped_image_url` writes |
</phase_requirements>

## Summary

Phase 2 is still best implemented as a **status-driven worker loop inside the bot process** (rather than introducing a separate queue service yet), because Phase 1 already owns durable `MealLog` state transitions and tests currently cover bot polling behavior. This keeps the scope aligned with `DETECTING -> SEGMENTING -> COMPLETED/FAILED` and avoids service sprawl before reliability and matching are in place [CITED: bot/polling.py, app/models/meal_log.py].

The biggest technical risk remains **structured multimodal output at phase boundary edges**: OpenRouter vision calls, strict schema parsing, and box normalization. The safest path is a separate detect call, then segment call, then label call, with **all-or-nothing rejection** of invalid segment outputs and a single, model-upgrading retry [CITED: .planning/phases/02-vision-slice/02-CONTEXT.md, AGENTS stack sources].

**Primary recommendation:** keep `llm_client.py` as the single OpenRouter entrypoint, extend `image_service.py` for crop persistence, and enforce deterministic box normalization/validation before any segment row becomes final [CITED: app/services/llm_client.py, app/services/image_service.py, app/models/meal_segment.py].

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|--------------|----------------|-----------|
| Request intake (ingest acceptance) | API / Backend | DB | Existing `/ingest/photo` endpoint handles validation and enqueue pattern via `MealLog(PENDING)` rows [CITED: app/models/meal_log.py] |
| Food detection | Bot / Processing worker | OpenRouter client | Bot currently claims pending rows; detect should run in worker context [CITED: bot/polling.py, app/services/llm_client.py] |
| Segmentation and crop generation | Bot / Processing worker | File system | Segments/crops are produced only for accepted meals and stored under upload volume mount [CITED: app/services/image_service.py] |
| Human-readable labeling | Bot / Processing worker | OpenRouter client | Separate call after accepted, normalized boxes [CITED: .planning/phases/02-vision-slice/02-CONTEXT.md] |
| Final message formatting | Bot / Processing worker | None | Existing message policy requires simple sentence output with collapsed duplicates [CITED: .planning/phases/02-vision-slice/02-CONTEXT.md, bot/messages.py] |

## Project Constraints (from AGENTS.md)

- Must follow existing stack constraints (FastAPI + Postgres + pgvector + OpenRouter via OpenAI SDK + python-telegram-bot worker topology + docker-compose) [CITED: /Users/mali/Documents/Projects/MealTracker/AGENTS.md].
- Use worktree-isolated execution and do not disable `workflow.use_worktrees` [CITED: /Users/mali/Documents/Projects/MealTracker/AGENTS.md].
- OpenRouter-only LLM access, `base_url` swap only [CITED: /Users/mali/Documents/Projects/MealTracker/AGENTS.md].
- No direct repository edits outside GSD flow when user does not request bypass [CITED: /Users/mali/Documents/Projects/MealTracker/AGENTS.md].
- Keep in mind APScheduler 3.x rule from roadmap context and fast/noisy stack choices [CITED: /Users/mali/Documents/Projects/MealTracker/AGENTS.md].

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.12/3.13 target; environment has 3.14.4 | Runtime for bot/API/services | Existing repo requirements target Py3.x with async stack [ASSUMED: requirements.txt indicates pinned Python ecosystem libraries only and test environment currently runs 3.14.4] |
| FastAPI | 0.115.13 (pinned in requirements) | API + dependency wiring | Stable Pydantic v2 stack and async baseline [CITED: requirements.txt] |
| OpenAI Python SDK | 1.55.3 (locked in requirements) | OpenRouter chat-compatible calls for vision + structured outputs | Current multimodal path already in `llm_client.py` [CITED: requirements.txt, app/services/llm_client.py] |
| python-telegram-bot | 22.7 | Bot polling and handler lifecycle | Existing bot service uses PTB run_polling pattern [CITED: tests/test_bot_contract.py, requirements.txt] |
| SQLAlchemy + asyncpg | 2.0.36 + 0.30.0 | ORM and async DB access for `MealLog` + `MealSegment` state | Existing models and polling code depend on AsyncSession API [CITED: requirements.txt, app/models/meal_log.py, app/models/meal_segment.py, bot/polling.py] |
| APScheduler | 3.10.4 | Phase future scheduling layer | Roadmap locks this major for this project [CITED: requirements.txt] |
| Pillow | 10.4.0 + pillow-heif 0.20.0 | Image decoding/transcoding/cropping | Crop persistence relies on Pillow + HEIC handling [CITED: requirements.txt, app/services/image_service.py] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| httpx | 0.27.2 | Async HTTP for any non-SDK calls and future smoke scripts | Current project uses raw HTTP in `llm_client.embed_multimodal()` [CITED: requirements.txt, app/services/llm_client.py] |
| structlog | 24.4.0 | Structured logging | Logging consistency if/when tracing worker decisions [CITED: requirements.txt] |
| tenacity | 9.0.0 | Retry/backoff | Candidate for bounded retry wrappers on LLM + external calls [CITED: requirements.txt] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Separate detect+segment+label | One combined multi-step model call | Combined calls reduce latency but blur failure boundaries and complicate all-or-nothing validation |
| New dedicated worker queue | Current bot polling loop | Queue adds infra complexity early; worker loop reuses existing DB lock/ownership model |
| In-process ad-hoc JSON parsing | `response_format=json_schema` + strict models | Strict schema reduces parser ambiguity and malformed outputs [ASSUMED from stack claims, verified by OpenRouter docs links] |

**Installation:**
```bash
pip install -r requirements.txt
```

**Version verification:** Before finalizing stack decisions, verify each package on the active ecosystem index:
```bash
python3 -m pip index versions fastapi
python3 -m pip index versions openai
python3 -m pip index versions python-telegram-bot
python3 -m pip index versions sqlalchemy
python3 -m pip index versions asyncpg
python3 -m pip index versions apscheduler
python3 -m pip index versions pgvector
```

## Package Legitimacy Audit

Phase 2 does not introduce new external runtime dependencies beyond the already pinned stack.  
**Packages added by this phase:** none.  
No package slopcheck pass is needed because no new package installs are proposed [CITED: requirements.txt].

## Architecture Patterns

### System Architecture Diagram

`iOS Shortcut` -> `POST /ingest/photo` -> `MealLog(PENDING)` -> `bot.polling` claims row -> `DETECTING`

`DETECTING` -> OpenRouter vision detect call -> `(non-food) -> completed(no final message)`  
`DETECTING` -> `(food)` -> `SEGMENTING`

`SEGMENTING` -> OpenRouter segment call -> normalize/validate boxes -> dedupe -> crop save -> label call -> Telegram message -> `COMPLETED`

`SEGMENTING` -> failed twice -> soft failure message + `FAILED`

### Recommended Project Structure
```
app/
├── services/
│   ├── llm_client.py          # shared OpenRouter chat client
│   ├── image_service.py       # add crop normalization/save helpers (reuses existing transcode)
│   └── vision_service.py      # orchestrate detect/segment/label + policy checks
bot/
├── polling.py                 # add vision-processing loop
├── messages.py                # keep terse sentence format
tests/
├── test_vision_service.py     # new deterministic tests for parser/state
```

### Pattern 1: Separate Stage Calls
**What:** Enforce detect -> segment -> label as explicit stages, each with isolated schema and failure handling.
**When to use:** Any phase that needs bounded deterministic behavior and minimal blast radius.
```python
if status == DETECTING:
    detect = call_gemma_classify(image_content)
    if detect.is_food: status = SEGMENTING
    else: status = COMPLETED (no result message)

if status == SEGMENTING:
    seg = call_gemini_segment(image_content)
    if seg.invalid: retry_with_stronger_model_once()
    segments = normalize_and_validate(seg.boxes)
```
[CITED: .planning/phases/02-vision-slice/02-CONTEXT.md]

### Pattern 2: All-or-nothing segment validation
**What:** Reject the whole segment response when any bounding box is malformed; no partial persistence.
**When to use:** to avoid corrupted pipeline state when model produces mixed-valid boxes [D-09].
```python
valid = all(validate_box(b) for b in candidate_boxes)
if not valid:
    raise RuntimeError("invalid segmentation response")
```
[CITED: .planning/phases/02-vision-slice/02-CONTEXT.md]

### Pattern 3: Normalize coordinate spaces immediately
**What:** Convert provider-native `0..1000` box values to internal normalized `[0,1]` floats at ingress.
**When to use:** whenever provider and app contracts disagree.
```python
def normalize_box(box):
    y0, x0, y1, x1 = [v / 1000.0 for v in box]
    return [y0, x0, y1, x1]
```
[CITED: AGENTS stack notes + .planning/ROADMAP.md]

### Anti-Patterns to Avoid
- **All-or-nothing bypassed:** persisting partial boxes from a mixed segmentation response.
- **Status explosion:** adding `LABELING` just to represent a transient compute step.
- **Path inference from labels:** writing crop paths from model text instead of deterministic segment IDs.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Detect/segment/label orchestration | Third-party orchestration framework | Small dedicated vision service around shared `OpenRouterClient` | Keeps failure/retry policy explicit and easy to test [CITED: app/services/llm_client.py] |
| Box sanity checks | Regex/heuristic text extraction | Pydantic schema + structured output and geometry checks | Improves parser reliability and auditability [CITED: Cited stack sources + local schema assumptions] |
| Async coordination | Separate queue infrastructure | Extend existing DB-driven bot polling loop | Prevents premature architecture complexity in MVP [CITED: bot/polling.py, app/models/meal_log.py] |

**Key insight:** This phase should avoid introducing a new service boundary for vision; schema-controlled outputs + DB-driven status transitions are sufficient and safer for this scope [CITED: bot/polling.py, .planning/phases/01-foundation-ingest/01-CONTEXT.md].

## Runtime State Inventory

Not applicable. This is not a rename/refactor or migration phase.

## Common Pitfalls

### Pitfall 1: Coordinate-space mismatch
**What goes wrong:** treating provider boxes as normalized `[0,1]` when they arrive in `0..1000`.  
**Why it happens:** `Gemini` docs commonly describe the 0-1000 range.  
**How to avoid:** normalize immediately on ingest of each segment response.  
**Warning signs:** boxes like `y0 = 873` causing oversized crops.
[CITED: AGENTS stack notes, .planning/ROADMAP.md]

### Pitfall 2: Partial-segment salvage
**What goes wrong:** persisting only "good" boxes from a partially bad model response.  
**Why it happens:** optimistic fallback implementations hide malformed outputs.  
**How to avoid:** enforce decision D-09 and reject whole response.  
**Warning signs:** intermittent duplicate/missing item count and non-deterministic message output.

### Pitfall 3: Silent non-food completion confusion
**What goes wrong:** sending a skip/skip-reason message for high-confidence non-food images.  
**Why it happens:** older roadmap text conflicted with phase discussion.  
**How to avoid:** explicit branch: skip all final messaging for confident non-food; still keep initial ack path intact [CITED: .planning/phases/02-vision-slice/02-CONTEXT.md].

### Pitfall 4: Retry loops without escalation
**What goes wrong:** repeated identical prompt/model calls with no stronger path.  
**Why it happens:** retry logic reused from generic transient-failure patterns.  
**How to avoid:** one retry only, with stronger model as specified by D-11.

## Code Examples

### OpenRouter client reuse for detect / segment / label
```python
response = await client.chat_completion(
    model="google/gemma-4-31b-it",
    messages=[{"role":"user","content":[...]}],
    response_format={"type":"json_schema","json_schema":{"name":"detect","schema":detect_schema}},
    tools=None,
)
```
[CITED: app/services/llm_client.py, OpenRouter docs: structured-outputs]

### Bounding-box normalize + validate helper
```python
def normalize_and_validate_box(raw: list[float]) -> list[float]:
    if len(raw) != 4:
        raise ValueError("expected 4 coordinates")
    y0, x0, y1, x1 = [float(v) / 1000.0 for v in raw]
    if not (0 <= y0 < y1 <= 1 and 0 <= x0 < x1 <= 1):
        raise ValueError("invalid normalized box")
    return [y0, x0, y1, x1]
```
[CITED: .planning/phases/02-vision-slice/02-CONTEXT.md]

### Crop persistence contract (proposed)
```python
crop_filename = f"/data/uploads/crops/{segment_id}.jpg"
# persist JPEG bytes and then attach to meal_segments.cropped_image_url
```
[CITED: app/services/image_service.py, .planning/phases/02-vision-slice/02-CONTEXT.md]

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Combined detect+label in one call | Three-stage detect/segment/label [split] | Phase 2 decisions | Improved observability and retry control |
| Ad-hoc bbox string parsing | Structured JSON outputs | OpenRouter strict schema availability | Lower parsing failure rate, deterministic validation |
| Single worker process for all LLM calls | Status-aware worker loop | existing bot loop with FOR UPDATE locking | Prevents duplicate claims and state races |

**Deprecated/outdated:**
- Sending Telegram result on non-food from earlier wording; current phase decisions specify suppression [CITED: .planning/phases/02-vision-slice/02-CONTEXT.md].

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `google/gemini-3.5-flash` availability for stronger segmentation retry in this environment | Standard Stack / Alternatives | If unavailable, a model fallback policy is needed before implementation |
| A2 | Current OpenRouter credentials and routing permit both `response_format=json_schema` and vision inputs for selected models | Verification Strategy | If unsupported, phase must fallback to validated alternate model sequence |

## Open Questions (RESOLVED)

1. **Which exact strict JSON schema constraints are accepted by each chosen model in this environment?**
   - Resolved decision: Phase 2 will use only the documented strict subset in production prompts and schemas: `additionalProperties: false`, every returned key listed in `required`, and no reliance on unsupported validation keywords like `minLength`, `pattern`, or numeric range enforcement inside provider schema handling.
   - Bounded fallback: if the detect-stage model (`google/gemma-4-31b-it`) fails the Wave 4 live smoke when paired with vision plus strict structured output, Phase 2 does not reopen research. Instead, detect falls back to `google/gemini-3-flash-preview` for this phase while preserving the same detect/segment/label architecture and validator behavior.
   - Verification closure: Wave 4 smoke coverage remains required, but it now validates an already-made implementation decision instead of carrying unresolved research uncertainty forward.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All services | ✓ | 3.14.4 | pin to 3.13/3.12 per roadmap if needed |
| Docker | API + DB stack | ✓ | 29.4.0 | Manual install required |
| Docker Compose | Service orchestration | ✓ | v5.1.2 | N/A |
| uv | Project toolchain | ✓ | 0.10.0 | pip install still supported |
| pytest | Unit test execution | ✗ | — | use `python -m unittest` (present infra) |
| psql | DB inspection | ✗ | — | install Postgres client package |
| Node | Unused by phase | ✓ | 20.20.2 | none |

**Missing dependencies with no fallback:**
- `pytest` if maintainers require pytest-based CI commands in this phase.

**Missing dependencies with fallback:**
- `psql`/`redis-cli` for local manual checks: can validate via app logs and containerized DB CLI path instead.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `unittest` |
| Config file | `tests/test_*.py` (no project-wide pytest config) |
| Quick run command | `python3 -m unittest tests.test_ingest_contract tests.test_bot_contract` |
| Full suite command | `python3 -m unittest discover tests` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| VISION-01 | detect classify returns is_food / is_food_confidence | unit/parser | `python3 -m unittest tests.test_vision_service` | ✗ |
| VISION-02 | non-food path sets no final message and still acknowledges | integration-style unit | `python3 -m unittest tests.test_vision_service` | ✗ |
| VISION-03 | normalization + area/IoU validation + max-count | unit | `python3 -m unittest tests.test_vision_service` | ✗ |
| VISION-04 | accepted segments stored and crop files written | unit/integration | `python3 -m unittest tests.test_vision_service` | ✗ |

### Wave 0 Gaps
- `tests/test_vision_service.py` not yet present.
- Vision worker contract tests for `polling` pipeline transitions not yet present.
- No openrouter smoke harness exists for structured-output capability proof.
- No fixtures for valid/invalid bbox responses.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | shared-secret header for ingress; bot chat ID pinning |
| V3 Session Management | no | no web sessions in this phase |
| V4 Access Control | yes | row-level visibility and no public endpoints for internal results |
| V5 Input Validation | yes | MIME checks and strict schema parsing for model output |
| V6 Cryptography | no | no new crypto handling in this phase |

### Known Threat Patterns for `python + bot + OpenRouter`
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Prompt injection in image payload metadata | Tampering | Keep parsing strict and ignore free-form labels unless schema-valid |
| Oversized/malformed bounding boxes | DoS | full validation and reject full response [D-09] |
| Crop path confusion | Tampering | deterministic segment UUID file names and fixed storage root |

## Sources

### Primary (HIGH confidence)
- OpenRouter Quickstart / vision / tool-calling / structured outputs (URLs in `AGENTS.md`) — OpenAI-compatible endpoint, multimodal content patterns, structured output behavior.
- Google Gemini API docs referenced in `AGENTS.md` — structured outputs, image understanding, embeddings constraints.
- FastAPI lifecycle + async docs in `AGENTS.md` for integration patterns.
- Local repo source files:
  - `app/services/llm_client.py`
  - `app/services/image_service.py`
  - `app/models/meal_log.py`
  - `app/models/meal_segment.py`
  - `bot/polling.py`
  - `bot/messages.py`

### Secondary (MEDIUM confidence)
- Stack/roadmap/requirements/phase files in this repo for locked phase decisions and model assignment.

### Tertiary (LOW confidence)
- Runtime package availability from `python3 -m pip index versions` output used for environment awareness only.

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM — versions are pinned locally, but environment currently exceeds stack-target Python and has no psql/pytest binaries.
- Architecture: HIGH — status-driven integration and service boundaries are already implemented in phase-1 artifacts.
- Pitfalls: HIGH — explicit failure modes are locked in context and directly traceable to decisions.

**Research date:** 2026-05-27
**Valid until:** 2026-06-27
