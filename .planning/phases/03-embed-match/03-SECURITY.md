---
phase: 03
slug: embed-match
status: verified
threats_open: 0
asvs_level: 1
created: 2026-05-28
updated: 2026-05-28
---

# Phase 03 - Security

> Verified against implemented code, automated tests, and phase artifacts. Documentation alone was not accepted as evidence.

## Threat Verification

| Threat ID | Category | Disposition | Evidence |
|-----------|----------|-------------|----------|
| T-03-01 | Information Disclosure | mitigate | `scripts/embed_match_smoke.py:83-100` rejects non-`crops/` inputs and whole-photo paths such as `sample_images`; crop-only enforcement is used by calibration at `scripts/embed_match_smoke.py:144-155`, demo seeding at `scripts/embed_match_smoke.py:270-275`, unresolved probe at `scripts/embed_match_smoke.py:324-329`, and repeat confirmation at `scripts/embed_match_smoke.py:404-416`. `tests/test_embed_match_smoke.py:35-54` and `tests/test_embed_match_smoke.py:182-233` cover rejection of whole-photo inputs and crop-only seed behavior. |
| T-03-02 | Tampering | mitigate | `app/services/llm_client.py:73-98` rejects missing payloads, missing embeddings, wrong dimensions, and non-finite/non-numeric values before returning a vector. `app/services/embedding_service.py:73-83` re-validates embedding length and numeric values, while `app/services/embedding_service.py:132-163` exposes separate document/query entry points with `RETRIEVAL_DOCUMENT` and `RETRIEVAL_QUERY`. `tests/test_embedding_service.py:35-75`, `tests/test_embedding_service.py:81-97`, `tests/test_embedding_service.py:168-240` cover task types, wrong-length rejection, missing data rejection, and query/document request mapping. |
| T-03-03 | Denial of Service | mitigate | `app/services/llm_client.py:23-37` sets explicit 60s client timeouts; `app/services/llm_client.py:71-98` raises on HTTP status failures and fails closed on invalid payloads. `app/services/embedding_service.py:108-129` retries only `httpx.HTTPError`, so parse/validation failures are not retried. `tests/test_embedding_service.py:98-133` proves retry on transport error and no retry on validation failure. |
| T-03-04 | Repudiation | mitigate | `scripts/embed_match_smoke.py:199-216` returns a calibration report with explicit verdict fields including `mode`, `status`, `sample`, `same_food_peer`, and similarity values; `scripts/embed_match_smoke.py:543-547` prints the report or failure outcome. `tests/test_embed_match_smoke.py:58-159` asserts the calibration path records the resolved crop paths and same-image evidence. |
| T-03-05 | Tampering | mitigate | `app/services/matching_service.py:232-249` computes similarity as `1.0 - distance` and filters `FoodVisual.is_invalidated.is_(False)`. `app/services/matching_service.py:276-285` applies the threshold branch to the computed similarity. The required 0.85 boundary is explicitly covered by `tests/test_matching_threshold.py:9-29` and `tests/test_matching_threshold.py:31-51`, plus the end-to-end corpus path in `tests/test_match_flow.py:92-146`. |
| T-03-06 | Elevation of Privilege | mitigate | Only the segment worker claims `SEGMENTING` meals and hands them to `EMBEDDING` at `bot/polling.py:159-165` and `bot/polling.py:224-225`. Only the embedding worker claims `EMBEDDING` meals and hands them to `MATCHING` at `bot/polling.py:271-304`. Only the match worker sets `REASONING` at `bot/polling.py:375-377` and `bot/polling.py:392-399`. `tests/test_match_flow.py:254-314` and `tests/test_match_flow.py:361-451` cover the `EMBEDDING -> MATCHING` handoff and `MATCHING -> REASONING` unresolved route. |
| T-03-07 | Information Disclosure | mitigate | `bot/messages.py:22-26` keeps the unresolved note terse and limited to the meal ID; it does not include scores, vectors, or debug data. `tests/test_match_flow.py:445-449` verifies the unresolved branch sends only that user-facing note. |
| T-03-08 | Repudiation | mitigate | `tests/test_match_flow.py:148-172` asserts the empty-corpus path returns no match, and `tests/test_match_flow.py:361-451` asserts below-threshold/unresolved routing to `REASONING`, exactly one notification, and no success writes. |
| T-03-09 | Tampering | mitigate | `app/services/matching_service.py:179-224` stages `DiaryEntry` and `FoodVisual` rows without committing. The completion path sets `MealLog.processing_status = COMPLETED` and commits once at `bot/polling.py:404-440`, keeping row writes and status transition in one transaction boundary. `tests/test_match_flow.py:453-577` exercises the fully resolved path that persists all rows before completion notification. |
| T-03-10 | Integrity | mitigate | `app/services/matching_service.py:205-223` writes `DiaryEntry` rows with `portion_bucket="STANDARD"` and appends only the matched food visual embedding. The completion payload copies existing nutrition fields with `getattr` at `bot/polling.py:418-435`. `bot/messages.py:75-125` omits missing nutrition fields instead of inventing values. `tests/test_bot_contract.py:56-95` covers known-only totals and the absence of fabricated/defaulted fields. |
| T-03-11 | Tampering | mitigate | The match worker exits to `REASONING` before any success persistence when a segment is unresolved at `bot/polling.py:381-402`. Confirmed matches intentionally append a fresh `FoodVisual` row per confirmation at `app/services/matching_service.py:216-223`. `tests/test_match_flow.py:361-451` covers suppression of write-back on unresolved meals, and `tests/test_match_flow.py:579-692` proves repeated confirmations append duplicate confirmation visuals intentionally. |
| T-03-12 | Denial of Service | mitigate | Success notification is outside the transaction boundary: commit occurs at `bot/polling.py:439-440` and the Telegram send follows at `bot/polling.py:442-448`. The unresolved send also happens only after the `REASONING` commit at `bot/polling.py:393-401`. |
| T-03-13 | Information Disclosure | mitigate | `bot/messages.py:129-145` formats completion output only from `food_name`, `portion_bucket`, `identification_method`, `is_verified`, and known nutrition fields. `tests/test_bot_contract.py:97-114` asserts internal fields such as `vector`, `embedding`, and `cropped_image_url` are excluded, and `tests/test_bot_contract.py:56-95` asserts scores/debug wording are absent. |
| T-03-14 | Integrity | mitigate | `bot/messages.py:75-88` renders only known item nutrition fields; `bot/messages.py:91-125` sums totals only when the source field is present. `tests/test_bot_contract.py:56-95` verifies missing values are omitted from both per-item output and totals. |
| T-03-15 | Denial of Service | mitigate | The `COMPLETED` transition is committed before notification at `bot/polling.py:439-443`, and send failures are logged without rollback at `bot/polling.py:447-448`. `tests/test_bot_contract.py:723-824` verifies commit-before-send ordering, and `tests/test_bot_contract.py:825-912` verifies a Telegram send failure leaves the meal `COMPLETED`. |
| T-03-16 | Repudiation | mitigate | `.planning/phases/03-embed-match/03-UAT.md:24-47` records exact commands, required sample assets, expected JSON/Telegram outputs, and the observed completion payload needed to reproduce live verification. |
| T-03-SC | Tampering | accept | Accepted risk `AR-03-01` is recorded in the Accepted Risks Log below. |

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-03-01 | T-03-SC | Phase 03 introduced no new packages or runtime surfaces; residual supply-chain/runtime risk remains accepted under the locked dependency baseline established in Phase 1. | Phase 03 plan record | 2026-05-28 |

## Unregistered Flags

None. `03-03-SUMMARY.md:95-97` is the only Phase 03 `## Threat Flags` section present in the supplied summaries, and it records no added flags.

## Verification Commands

- `rtk .venv/bin/python -m unittest tests.test_embedding_service tests.test_match_flow tests.test_matching_threshold tests.test_embed_match_smoke tests.test_embed_worker tests.test_bot_contract`

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-05-28 | 16 | 16 | 0 | Codex + `gsd-security-auditor` |

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified
