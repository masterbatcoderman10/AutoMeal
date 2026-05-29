---
phase: 04
slug: reason-interview-learning-loop
status: verified
threats_open: 0
asvs_level: 1
created: 2026-05-29
verified: 2026-05-29
---

# Phase 04 Security Audit

- Phase: `04` - `reason-interview-learning-loop`
- Audit date: `2026-05-29`
- ASVS level: `1`
- Threats total: `38`
- Threats closed: `38`
- Threats open: `0`
- Summary threat flags: `none`

## Threat Verification

| Threat ID | Component | Category | Disposition | Evidence |
|---|---|---|---|---|
| T-04-05 | `tests/test_reasoning_contract.py` | Tampering | mitigate | Open-string `action` and unknown-action downgrade are asserted at `tests/test_reasoning_contract.py:24-57` and `tests/test_reasoning_contract.py:78-100`. |
| T-04-06 | `tests/test_reasoning_gate.py` | Tampering | mitigate | Deterministic gate coverage over similarity, candidate margin, missing evidence, and nutrition impact is asserted at `tests/test_reasoning_gate.py:52-77` and `tests/test_reasoning_gate.py:82-194`. |
| T-04-07 | `tests/test_reasoning_flow.py` | Repudiation | mitigate | The test requires persisted segment and meal reasoning traces before ready-to-write acceptance at `tests/test_reasoning_flow.py:80-134` and `tests/test_reasoning_flow.py:140-187`. |
| T-04-08 | `tests/test_parallel_pipeline.py` | Denial of Service | mitigate | Bounded fan-out and sibling-progress expectations are asserted at `tests/test_parallel_pipeline.py:52-167`. |
| T-04-SC | `scripts/embed_match_smoke.py` | Information Disclosure | mitigate | Reasoning smoke output reports normalized gate fields plus `trace_id` and `cached_tokens`, then prints only the assembled report at `scripts/embed_match_smoke.py:137-203` and `scripts/embed_match_smoke.py:613-635`. |
| T-04-09 | `tests/test_interview_flow.py` | Elevation of Privilege | mitigate | Pinned-chat rejection and persisted-session callback resolution are asserted at `tests/test_interview_flow.py:23-42` and `tests/test_interview_flow.py:239-272`. |
| T-04-13 | `tests/test_fix_flow.py` | Tampering | mitigate | Confirm-or-cancel, identity-only invalidation, quantity-only no-invalidation, and visual-learning gating are asserted at `tests/test_fix_flow.py:88-191`. |
| T-04-17 | `tests/test_janitor.py` | Denial of Service | mitigate | Artifact-first recovery, three-recovery exhaustion, stale-state exclusion, and duplicate-notify suppression are asserted at `tests/test_janitor.py:49-151`. |
| T-04-SC | `Wave 0 targeted tests` | Repudiation | mitigate | Named regression files encode D-48/D-49, `/fix`, and janitor semantics in `tests/test_interview_flow.py:275-336`, `tests/test_fix_flow.py:307-435`, and `tests/test_janitor.py:49-151`. |
| T-04-01 | `migrations/versions/002_phase4_state_surfaces.py` | Tampering | mitigate | The migration adds explicit JSON/timestamp/audit columns and creates `interview_sessions`, `interview_messages`, and `correction_events` at `migrations/versions/002_phase4_state_surfaces.py:20-151`. |
| T-04-02 | `app/models/correction_event.py` | Repudiation | mitigate | Durable `before_json`, `after_json`, `visual_learning_eligible`, `trace_id`, and timestamp fields are defined at `app/models/correction_event.py:21-38`. |
| T-04-03 | `app/models/interview_message.py` | Information Disclosure | mitigate | The DB surface is limited to `role`, `payload`, `message_id`, and `created_at` at `app/models/interview_message.py:19-30`, and interview writes store prompt or answer payloads only at `app/services/interview_service.py:410-419`, `app/services/interview_service.py:485-494`, and `app/services/interview_service.py:511-528`. |
| T-04-04 | `scripts/check_schema_contract.py` | Denial of Service | mitigate | The contract script imports live models and asserts concrete SQLAlchemy types, defaults, and migration wiring at `scripts/check_schema_contract.py:39-205`. |
| T-04-SC | `recovery metadata` | Tampering | mitigate | Exact recovery counters and notification timestamps are stored on `MealLog` at `app/models/meal_log.py:45-60`, added in the migration at `migrations/versions/002_phase4_state_surfaces.py:20-51`, and merged into janitor metadata at `app/services/recovery_service.py:311-328`. |
| T-04-03 | `config/reasoning_taxonomy.json` | Information Disclosure | mitigate | The taxonomy file contains threshold and question-budget policy data only at `config/reasoning_taxonomy.json:1-93`. |
| T-04-04 | `app/services/tracing_service.py` | Denial of Service | mitigate | Tracing degrades to `TraceHandle(trace=None, trace_id=None, ...)` on disabled, client-init, and trace-create failures at `app/services/tracing_service.py:46-82` and `app/services/tracing_service.py:144-183`. |
| T-04-07 | `app/services/meal_resolution_service.py` | Repudiation | mitigate | `apply_final_meal_resolution()` centralizes diary-entry writes, food-visual mutation, and correction-event creation at `app/services/meal_resolution_service.py:304-428`, and all three downstream callers route through it at `app/services/interview_service.py:638-649`, `app/services/reasoning_service.py:759-766`, and `app/services/correction_service.py:231-271`. |
| T-04-SC | `requirements.txt` | Tampering | mitigate | `langfuse` is pinned to `4.7.0` at `requirements.txt:20`. |
| T-04-05 | `app/services/reasoning_schema.py` | Tampering | mitigate | The reasoning schema is strict, keeps `action` as an open string, and routes unknown actions to `NEEDS_SCHEMA_REVIEW` at `app/services/reasoning_schema.py:21-88` and `app/services/reasoning_schema.py:227-264`. |
| T-04-06 | `app/services/reasoning_service.py` | Tampering | mitigate | The auto-confirm gate checks threshold, top-1/top-2 margin, missing evidence, and nutrition impact before permitting write-through at `app/services/reasoning_service.py:214-294`. |
| T-04-07 | `bot/polling.py` | Repudiation | mitigate | Match candidate snapshots are persisted before reasoning at `bot/polling.py:1067-1088`, and reasoning traces/state are persisted before final write in `app/services/reasoning_service.py:552-638` and `app/services/reasoning_service.py:722-778`. |
| T-04-08 | `semaphore fan-out` | Denial of Service | mitigate | Matching concurrency is bounded with `asyncio.Semaphore` at `bot/polling.py:908-932` and `bot/polling.py:1067-1082`, while segment embedding retries stop after a fixed ceiling at `app/services/matching_service.py:22` and `app/services/matching_service.py:247-268`; batch failure aborts closed at `bot/polling.py:1143-1155`. |
| T-04-SC | `tracing wrapper and model client` | Tampering | mitigate | Trace IDs are propagated from payload or metadata at `app/services/reasoning_service.py:119-137` and `app/services/reasoning_service.py:169-196`, while tracing failures stay no-op at `app/services/tracing_service.py:151-183` without altering gate or write behavior. |
| T-04-09 | `bot/handlers.py` | Elevation of Privilege | mitigate | Non-pinned chats are rejected at `bot/handlers.py:116-125`, and confirmation callbacks are resolved by loading the active `InterviewSession` for `chat_id` plus `meal_id` at `bot/handlers.py:128-141` and `bot/handlers.py:247-309`. |
| T-04-10 | `app/services/interview_service.py` | Tampering | mitigate | The service advances one targeted step at a time at `app/services/interview_service.py:70-186`, persists each step to `InterviewSession` and `InterviewMessage` at `app/services/interview_service.py:499-535`, and only reaches `apply_final_meal_resolution()` from confirmed finalization at `app/services/interview_service.py:599-653`. |
| T-04-11 | `tests/test_interview_flow.py` | Repudiation | mitigate | Backbone, D-48/D-49 edit branches, one-reminder behavior, persisted steps, and `is_verified=false` best-effort closeout are asserted at `tests/test_interview_flow.py:46-272` and `tests/test_interview_flow.py:275-420`. |
| T-04-12 | `app/services/grounding_stub.py` | Information Disclosure | mitigate | The grounding stub stores only minimal packaged/restaurant prep fields and `NEEDS_GROUNDING` status, with no live tool loop, at `app/services/grounding_stub.py:6-32`. |
| T-04-SC | `parser-model surface` | Tampering | mitigate | Parser repair uses `google/gemini-3.1-flash-lite` then a single fallback to `google/gemini-3.5-flash` in config and retry logic at `app/config.py:21-22` and `app/services/reasoning_service.py:380-421`, then coerces the result locally before mutation at `app/services/reasoning_service.py:469-496` and `app/services/reasoning_service.py:542-549`. |
| T-04-13 | `app/services/correction_service.py` | Tampering | mitigate | Identity changes and quantity changes are separated, and only the linked visual is invalidated for confirmed identity fixes at `app/services/correction_service.py:106-146` and `app/services/correction_service.py:211-273`. |
| T-04-14 | `app/models/correction_event.py` | Repudiation | mitigate | The append-only correction-event table stores before/after JSON, visual-learning flag, trace ID, and timestamp at `app/models/correction_event.py:18-42`, and new rows are appended from the shared final-write path at `app/services/meal_resolution_service.py:344-371`. |
| T-04-15 | `bot/handlers.py` | Elevation of Privilege | mitigate | `/fix` targets are resolved server-side from recent-entry context or explicit IDs, then loaded from `DiaryEntry` before mutation at `bot/handlers.py:62-95` and `bot/handlers.py:157-185`. |
| T-04-16 | `bot/messages.py` | Information Disclosure | mitigate | User-facing confirmation and fix summaries expose changed fields and side effects only, without hidden reasoning traces or raw model internals, at `bot/messages.py:40-77` and `bot/messages.py:190-221`. |
| T-04-SC | `corrected visual write-back` | Tampering | mitigate | Visual re-learning intent is gated on `visual_learning_eligible` at `app/services/correction_service.py:136-145`, and the confirmed correction path does not append a new visual row because it passes `create_food_visual=False` at `app/services/correction_service.py:253-261`. |
| T-04-17 | `app/main.py` scheduler wiring | Denial of Service | mitigate | The janitor job is registered once with `max_instances=1`, `coalesce=True`, and explicit interval/misfire configuration at `app/main.py:27-40`. |
| T-04-18 | `app/services/recovery_service.py` | Tampering | mitigate | Recovery resumes from interview session, candidate snapshots, embeddings, or crops instead of resetting to `PENDING`, and machine-stage handling excludes active interview/terminal states at `app/services/recovery_service.py:56-165` and `app/services/recovery_service.py:205-274`. |
| T-04-19 | `tests/test_janitor.py` | Repudiation | mitigate | The test suite locks the three-recovery ceiling, stale-stage exclusion list, and one-notification rule at `tests/test_janitor.py:83-151`. |
| T-04-20 | `scripts/recovery_smoke.py` | Information Disclosure | mitigate | Recovery smoke output renders stage transitions, retry counters, resume basis, and janitor outcome only at `scripts/recovery_smoke.py:100-113` and `scripts/recovery_smoke.py:139-170`. |
| T-04-SC | `duplicate prompt or write surface` | Denial of Service | mitigate | Duplicate prompts are suppressed by reusing active interview sessions at `app/services/interview_service.py:370-381` and `app/services/interview_service.py:431-448`; duplicate finalization is cut off by deactivating sessions after confirmation at `bot/handlers.py:271-309` and `bot/handlers.py:339-381`; duplicate janitor notices are suppressed by `last_recovery_notified_at` at `app/services/recovery_service.py:185-194` and `app/services/recovery_service.py:439-455`. |

## Unregistered Flags

None. No `## Threat Flags` sections were present in `04-01-SUMMARY.md` through `04-08-SUMMARY.md`.

## Accepted Risks

None recorded.

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-05-29 | 38 | 38 | 0 | gsd-security-auditor |

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-05-29
