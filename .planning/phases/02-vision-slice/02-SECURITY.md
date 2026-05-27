---
status: verified
phase: 02-vision-slice
threats_open: 0
asvs_level: 1
source:
  - .planning/phases/02-vision-slice/02-01-PLAN.md
  - .planning/phases/02-vision-slice/02-02-PLAN.md
  - .planning/phases/02-vision-slice/02-03-PLAN.md
  - .planning/phases/02-vision-slice/02-04-PLAN.md
  - .planning/phases/02-vision-slice/02-01-SUMMARY.md
  - .planning/phases/02-vision-slice/02-02-SUMMARY.md
  - .planning/phases/02-vision-slice/02-03-SUMMARY.md
  - .planning/phases/02-vision-slice/02-04-SUMMARY.md
  - .planning/phases/02-vision-slice/02-UAT.md
updated: 2026-05-27T00:00:00Z
---

# Phase 02 Security Verification

## Verdict

Phase 02 security controls are verified for the vision slice that detect, segment, crop, label, and report meal photos.

All four Phase 02 plan-time threat models were audited against the current implementation, tests, and recorded UAT evidence. No open threat remained after verification, and no accepted-risk entry was needed for this phase.

Phase 02 summary threat flags were also reviewed. `02-01-SUMMARY.md` and `02-02-SUMMARY.md` explicitly report `None`, and the later summaries do not introduce additional unresolved security flags.

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Ingest photo -> vision pipeline | Uploaded meal photos move from the trusted ingest path into detect and segmentation workers. | User image bytes, meal IDs, processing state |
| App -> OpenRouter vision models | Structured multimodal prompts and model responses cross the external LLM boundary. | Base64 image data, structured detect/segment/label JSON |
| App -> upload storage | Accepted segments become crop JPEGs on the configured uploads volume. | Local file paths, crop image bytes |
| Bot worker -> Telegram | Final user-facing meal results and soft-failure notices leave the app boundary. | Chat ID, one-line meal result text |
| Verification scripts -> runtime services | Smoke and UAT flows probe the same production code paths to validate runtime behavior. | Sample images, structured detect/segment/label outputs |

## Threat Mitigation Results

| Threat ID | Source | Threat | Severity | Disposition | Status | Verification |
|-----------|--------|--------|----------|-------------|--------|--------------|
| T-02-01 | 02-01 | Wrong model or malformed multimodal payload silently bypasses the detect gate | HIGH | Mitigate | Closed | `app/services/vision_service.py` uses strict detect JSON schema plus fail-closed parsing, and `tests/test_bot_contract.py` verifies multimodal payloads and `extra_body` reach the shared client unchanged. |
| T-02-02 | 02-01 | Borderline non-food photo continues deeper into the meal pipeline | MEDIUM | Mitigate | Closed | Detect decisions require both `is_food=true` and confidence above threshold before advancing to segmentation; `tests/test_vision_service.py` covers conservative skip behavior for weak payloads. |
| T-02-03 | 02-01 | Final Telegram output is sent for confident non-food images | MEDIUM | Mitigate | Closed | `bot/polling.py` marks confident non-food meals `COMPLETED` without sending a final result message, and `tests/test_bot_contract.py` asserts `send_message` is not awaited on that path. |
| T-02-04 | 02-01 | Bot background worker leaks on shutdown | LOW | Mitigate | Closed | `bot/main.py` registers detect and segment tasks and cancels them in `post_shutdown()`, with lifecycle coverage in `tests/test_bot_contract.py`. |
| T-02-05 | 02-02 | Raw Gemini-style box coordinates are stored without normalization | HIGH | Mitigate | Closed | `app/services/vision_service.py` normalizes provider `0..1000` boxes into `[0,1]` floats before persistence, and `tests/test_vision_service.py` covers normalization plus invalid-range rejection. |
| T-02-06 | 02-02 | Crop files are written outside the uploads volume or with inconsistent paths | MEDIUM | Mitigate | Closed | `app/services/image_service.py` writes crops under `UPLOADS_DIR / "crops"` with `{segment_id}.jpg`; production settings use `/data/uploads`, and tests confirm the configured root is honored. |
| T-02-07 | 02-02 | Labeling is attempted on unvalidated regions | MEDIUM | Mitigate | Closed | Segment parsing rejects invalid boxes before `MealSegment` creation or crop writes, and `bot/polling.py` labels only accepted persisted segments after crop save succeeds. |
| T-02-08 | 02-02 | Result message exposes debugging detail or counts every tiny item | LOW | Mitigate | Closed | `bot/messages.py` formats a single plain result sentence from accepted labels only, while validation rules reject tiny boxes and tests assert the `I see ...` contract. |
| T-02-09 | 02-03 | Partial invalid model output becomes partially accepted and corrupts downstream crops | HIGH | Mitigate | Closed | `segment_food_photo_with_retry()` rejects unusable segment payloads wholesale and retries once with the stronger model; tests cover mixed valid/invalid responses. |
| T-02-10 | 02-03 | Same food item is double-counted due to overlapping regions | MEDIUM | Mitigate | Closed | `dedupe_overlapping_segments()` removes overlaps above IoU `0.5` before persistence, and `tests/test_vision_service.py` keeps only the higher-confidence region. |
| T-02-11 | 02-03 | Retry logic loops indefinitely or silently reuses the same weak prompt | MEDIUM | Mitigate | Closed | The segmentation path hard-caps retries at one and explicitly switches to `SEGMENT_RETRY_MODEL`; test coverage asserts the second call uses `google/gemini-3.5-flash`. |
| T-02-12 | 02-03 | Weak labels clutter the result sentence with repeated or uncertain noise | LOW | Mitigate | Closed | `bot/messages.py` collapses duplicate labels and hedges only weak ones inline, with contract tests for mixed-confidence output. |
| T-02-13 | 02-04 | Shared runtime path works only in mocks and not against real OpenRouter payloads | HIGH | Mitigate | Closed | `scripts/vision_smoke.py` imports shared project services rather than issuing ad hoc requests, and `02-UAT.md` records successful end-to-end smoke evidence on `2026-05-27`. |
| T-02-14 | 02-04 | Phase 2 model settings are added in code but not documented for operators | MEDIUM | Mitigate | Closed | `.env.example` documents `DETECT_MODEL`, `SEGMENT_MODEL`, `SEGMENT_RETRY_MODEL`, `LABEL_MODEL`, and `VISION_MAX_SEGMENTS` as optional overrides. |
| T-02-15 | 02-04 | Manual verification is forgotten or unrepeatable | MEDIUM | Mitigate | Closed | `02-UAT.md` provides repeatable checks plus evidence slots for non-food completion, crop existence, soft failure, and grouped sample-image behavior. |
| T-02-16 | 02-04 | Smoke script drifts away from the production code path | LOW | Mitigate | Closed | `scripts/vision_smoke.py` runs detect, segment, and label through `app/services/vision_service.py` and the shared settings/client path instead of duplicating request logic. |

## Accepted Risks Log

No accepted risks.

## Verification Run

- Plan-time threat models reviewed from `02-01-PLAN.md` through `02-04-PLAN.md`.
- Summary threat flags reviewed from `02-01-SUMMARY.md` through `02-04-SUMMARY.md`.
- UAT evidence reviewed in `02-UAT.md`, including crop-path confirmation and end-to-end smoke verification on `2026-05-27`.
- Implementation evidence reviewed in `app/config.py`, `app/services/llm_client.py`, `app/services/vision_service.py`, `app/services/image_service.py`, `bot/main.py`, `bot/polling.py`, `bot/messages.py`, and `scripts/vision_smoke.py`.
- Test evidence reviewed in `tests/test_vision_service.py` and `tests/test_bot_contract.py`.

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-05-27 | 16 | 16 | 0 | Codex `gsd-secure-phase` |

## Sign-Off

- [x] All threats have a disposition.
- [x] Accepted risks documented when needed.
- [x] `threats_open: 0` confirmed.
- [x] Frontmatter status set to `verified`.

**Approval:** verified 2026-05-27
