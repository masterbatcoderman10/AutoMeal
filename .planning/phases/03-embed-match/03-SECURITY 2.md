---
phase: 03
slug: embed-match
status: draft
threats_open: 3
asvs_level: 1
created: 2026-05-28
---

# Phase 03 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| crop file -> OpenRouter embeddings API | Saved segment crops and calibration inputs leave the host for embedding generation. | image bytes, optional query text |
| OpenRouter response -> application vector storage | Remote embedding payloads cross into ORM-managed storage. | remote JSON, 1536-d vectors |
| sample seed helper -> local database | Smoke-script demo seeding can populate `FoodVisual` and related records. | sample-derived embeddings, demo nutrition rows |
| saved crop -> similarity query | Segment crops become query embeddings used for nearest-neighbor search. | `MealSegment.cropped_image_url`, query embeddings |
| pgvector distance -> application threshold | Database distance results become match-or-escalate business decisions. | cosine distance, similarity threshold result |
| unresolved meal -> Telegram note | Runtime discloses unresolved-match state to the single-user bot chat. | meal status, user-facing note |
| similarity decision -> diary persistence | Match outcomes become durable nutrition history. | `FoodItem` identity, macro fields, portion bucket |
| confirmed match -> `FoodVisual` append | New confirmed visuals enter the reusable visual corpus. | crop path, write embedding, invalidation flag |
| committed DB rows -> later Telegram push | Bot output is rendered from committed rows after match completion. | committed meal entries, verification status |
| formatter -> partial nutrition fields | Completion messages must omit unknown nutrition cleanly. | known calories/macros only |
| manual UAT -> production-like behavior | Human verification must be reproducible from recorded commands and evidence. | smoke commands, sample asset paths, expected output |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-03-01 | Information Disclosure | `scripts/embed_match_smoke.py` | mitigate | Require saved crop artifacts for calibration and seed uploads instead of whole sample inputs. | open |
| T-03-02 | Tampering | `app/services/embedding_service.py` | mitigate | Validate response presence, vector length `== 1536`, and task-type entry points before ORM assignment. | closed |
| T-03-03 | Denial of Service | `app/services/llm_client.py` | mitigate | Retry only transport and retryable upstream failures with explicit timeout; fail closed on validation errors. | closed |
| T-03-04 | Repudiation | `scripts/embed_match_smoke.py` | mitigate | Emit reproducible calibration verdicts and sample-path evidence. | closed |
| T-03-05 | Tampering | `app/services/matching_service.py` | mitigate | Add a boundary test that exercises the real `0.85` threshold branch, not only stubbed below-threshold outcomes. | open |
| T-03-06 | Elevation of Privilege | `bot/polling.py` | mitigate | Restrict `REASONING` transitions to match workers; the embed worker must not set `REASONING` when segments are absent. | open |
| T-03-07 | Information Disclosure | `bot/messages.py` | mitigate | Keep unresolved-match output terse and omit raw scores or debug fields. | closed |
| T-03-08 | Repudiation | `tests/test_match_flow.py` | mitigate | Encode empty-index and below-threshold routing as automated assertions. | closed |
| T-03-09 | Tampering | `app/services/matching_service.py` | mitigate | Persist `DiaryEntry`, `FoodVisual`, and `MealLog.processing_status=COMPLETED` in one transaction. | closed |
| T-03-10 | Integrity | `app/services/matching_service.py` | mitigate | Force `portion_bucket=STANDARD` and copy only existing `FoodItem` nutrition fields. | closed |
| T-03-11 | Tampering | `app/models/food_visual.py` writes | mitigate | Suppress write-back when any segment is unresolved and intentionally allow duplicate confirmations. | closed |
| T-03-12 | Denial of Service | `bot/polling.py` | mitigate | Keep notification send outside the completion transaction. | closed |
| T-03-13 | Information Disclosure | `bot/messages.py` | mitigate | Exclude scores, vector details, and debug traces from completion messages. | closed |
| T-03-14 | Integrity | `bot/messages.py` | mitigate | Sum only known nutrition fields and omit missing values. | closed |
| T-03-15 | Denial of Service | `bot/polling.py` | mitigate | Keep Telegram send failures non-transactional and covered by tests. | closed |
| T-03-16 | Repudiation | `.planning/phases/03-embed-match/03-UAT.md` | mitigate | Record exact commands, sample assets, and expected Telegram content. | closed |
| T-03-SC | Tampering | Python dependency/runtime surface | accept | No new packages were introduced in Phase 03; rely on the locked Phase 1 stack and document the risk acceptance here. | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-03-01 | T-03-SC | Phase 03 introduced no new packages or runtime surfaces; residual supply-chain/runtime risk is accepted under the locked dependency baseline established in Phase 1. | Phase 03 plan record | 2026-05-28 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-05-28 | 16 | 13 | 3 | Codex + `gsd-security-auditor` |

---

## Sign-Off

- [ ] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [ ] `threats_open: 0` confirmed
- [ ] `status: verified` set in frontmatter

**Approval:** pending
