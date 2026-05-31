# Phase 04 Security Audit

- Phase: `04` - `reason-interview-learning-loop`
- Audit date: `2026-05-29`
- ASVS level: `1`
- Threats total: `38`
- Threats closed: `32`
- Threats open: `6`
- Summary threat flags: `none`

## Closed Threats

| Threat ID | Component | Category | Disposition | Evidence |
|---|---|---|---|---|
| T-04-05 | `tests/test_reasoning_contract.py` | Tampering | mitigate | Open-string `action` and unknown-action downgrade asserted at `tests/test_reasoning_contract.py:22-55` and `tests/test_reasoning_contract.py:78-101`. |
| T-04-06 | `tests/test_reasoning_gate.py` | Tampering | mitigate | Deterministic gate matrix over similarity, margin, missing evidence, and nutrition impact asserted at `tests/test_reasoning_gate.py:50-94` and `tests/test_reasoning_gate.py:97-194`. |
| T-04-08 | `tests/test_parallel_pipeline.py` | Denial of Service | mitigate | Bounded semaphore fan-out and sibling progress assertions at `tests/test_parallel_pipeline.py:47-149`. |
| T-04-SC | `scripts/embed_match_smoke.py` | Information Disclosure | mitigate | Smoke output emits normalized `action`, `meal_state`, `gate_reason`, `decision_rationale`, `trace_id`, `cached_tokens`, and stored snapshots only; no provider raw payload or secrets are printed at `scripts/embed_match_smoke.py:180-203`. |
| T-04-13 | `tests/test_fix_flow.py` | Tampering | mitigate | Identity-only invalidation, quantity-only no-invalidation, confirm/cancel, and visual-learning gating asserted at `tests/test_fix_flow.py:78-184`. |
| T-04-17 | `tests/test_janitor.py` | Denial of Service | mitigate | Artifact-first resume, three-recovery ceiling, stale exclusion list, and single notification assertions at `tests/test_janitor.py:43-123`. |
| T-04-SC | `Wave 0 targeted tests` | Repudiation | mitigate | Named regression files exist and encode D-48/D-49, `/fix`, and janitor semantics in `tests/test_interview_flow.py`, `tests/test_fix_flow.py`, and `tests/test_janitor.py`. |
| T-04-01 | `migrations/versions/002_phase4_state_surfaces.py` | Tampering | mitigate | Explicit JSON/timestamp/audit columns and new `interview_sessions`, `interview_messages`, and `correction_events` tables added at `migrations/versions/002_phase4_state_surfaces.py:20-151`. |
| T-04-02 | `app/models/correction_event.py` | Repudiation | mitigate | Durable `before_json`, `after_json`, `visual_learning_eligible`, `trace_id`, and `created_at` fields defined at `app/models/correction_event.py:18-39`. |
| T-04-03 | `app/models/interview_message.py` | Information Disclosure | mitigate | Model surface is limited to `role`, `payload`, `message_id`, and `created_at` at `app/models/interview_message.py:15-29`; usage stores prompts/answers only in handlers at `bot/handlers.py:397-408` and `bot/handlers.py:427-446`. |
| T-04-04 | `scripts/check_schema_contract.py` | Denial of Service | mitigate | Contract script asserts actual SQLAlchemy types/tables plus migration presence, not just marker strings, at `scripts/check_schema_contract.py:57-143` and `scripts/check_schema_contract.py:146-205`. |
| T-04-SC | `recovery metadata` | Tampering | mitigate | Exact recovery counter and notification timestamp fields are persisted on `MealLog` at `app/models/meal_log.py:45-55` and added in migration at `migrations/versions/002_phase4_state_surfaces.py:24-51`. |
| T-04-03 | `config/reasoning_taxonomy.json` | Information Disclosure | mitigate | Taxonomy file contains policy thresholds and question-budget data only at `config/reasoning_taxonomy.json:1-81`. |
| T-04-04 | `app/services/tracing_service.py` | Denial of Service | mitigate | Tracing degrades to `TraceHandle(trace=None, trace_id=None, ...)` on disabled/misconfigured/error paths at `app/services/tracing_service.py:46-62` and `app/services/tracing_service.py:144-183`. |
| T-04-SC | `requirements.txt` | Tampering | mitigate | `langfuse` is pinned to `4.7.0` at `requirements.txt:20`. |
| T-04-05 | `app/services/reasoning_schema.py` | Tampering | mitigate | Strict JSON schema, open-string `action`, and explicit unknown-action routing to `NEEDS_SCHEMA_REVIEW` are implemented at `app/services/reasoning_schema.py:21-88` and `app/services/reasoning_schema.py:227-264`. |
| T-04-06 | `app/services/reasoning_service.py` | Tampering | mitigate | Auto-confirm gate uses threshold, top-1/top-2 margin, missing evidence, and nutrition impact checks at `app/services/reasoning_service.py:214-294`. |
| T-04-07 | `bot/polling.py` | Repudiation | mitigate | Candidate snapshots are persisted and committed before the reasoning/final-write call chain at `bot/polling.py:1084-1095`; reasoning persistence happens before final write in `app/services/reasoning_service.py:552-638` and `app/services/reasoning_service.py:722-778`. |
| T-04-08 | `semaphore fan-out` | Denial of Service | mitigate | Configurable bounded concurrency uses `asyncio.Semaphore` at `bot/polling.py:908-932` and `bot/polling.py:1071-1082`; batch failure aborts closed through the outer exception path at `bot/polling.py:1143-1155`. |
| T-04-SC | `tracing wrapper and model client` | Tampering | mitigate | Trace IDs are propagated from API payloads and tracing is no-op on failure at `app/services/reasoning_service.py:119-137`, `app/services/reasoning_service.py:169-196`, `app/services/reasoning_service.py:440-496`, and `app/services/tracing_service.py:151-183`. |
| T-04-09 | `bot/handlers.py` | Elevation of Privilege | mitigate | Non-pinned chats are rejected at `bot/handlers.py:117-126`; callbacks are resolved by loading the active `InterviewSession` for `chat_id` and `meal_id`, not by trusting client state, at `bot/handlers.py:248-269`. |
| T-04-12 | `app/services/grounding_stub.py` | Information Disclosure | mitigate | Only minimal `NEEDS_GROUNDING` prep fields are stored and no live grounding loop exists at `app/services/grounding_stub.py:6-32`. |
| T-04-13 | `app/services/correction_service.py` | Tampering | mitigate | Identity changes are separated from quantity changes and only the linked visual is invalidated on confirmed identity fixes at `app/services/correction_service.py:102-142` and `app/services/correction_service.py:255-280`. |
| T-04-14 | `app/models/correction_event.py` | Repudiation | mitigate | Correction history is append-oriented via a dedicated table with immutable event rows and timestamps at `app/models/correction_event.py:18-39`. |
| T-04-15 | `bot/handlers.py` | Elevation of Privilege | mitigate | `/fix` targets are resolved server-side, then loaded from `DiaryEntry` by ID before any mutation at `bot/handlers.py:63-95`. |
| T-04-16 | `bot/messages.py` | Information Disclosure | mitigate | User-facing diff and summary messages expose changed fields and side effects only, without reasoning traces or raw model payloads, at `bot/messages.py:40-78` and `bot/messages.py:190-221`. |
| T-04-SC | `corrected visual write-back` | Tampering | mitigate | Correction flow gates write-back intent on `visual_learning_eligible` and keeps quantity-only fixes from enabling visual writes at `app/services/correction_service.py:132-142` and `app/services/correction_service.py:304-316`; no corrected visual append path is present in the correction flow. |
| T-04-17 | `app/main.py scheduler wiring` | Denial of Service | mitigate | Janitor is registered with `max_instances=1`, `coalesce=True`, and explicit interval/misfire settings at `app/main.py:31-40`. |
| T-04-18 | `app/services/recovery_service.py` | Tampering | mitigate | Recovery resumes from interview session, candidate snapshots, embeddings, or crops rather than resetting blindly, and active interview state is handled explicitly at `app/services/recovery_service.py:118-165` and `app/services/recovery_service.py:226-274`. |
| T-04-19 | `tests/test_janitor.py` | Repudiation | mitigate | Tests lock exact three-recovery exhaustion, stale exclusions, and one-notification behavior at `tests/test_janitor.py:43-123`. |
| T-04-20 | `scripts/recovery_smoke.py` | Information Disclosure | mitigate | Smoke output reports only stage, resume basis, action, and counters at `scripts/recovery_smoke.py:100-113` and `scripts/recovery_smoke.py:139-170`. |
| T-04-SC | `duplicate prompt or write surface` | Denial of Service | mitigate | Exhausted meals are moved to `FAILED` and excluded from future janitor scans, while duplicate failure notices are suppressed by `last_recovery_notified_at`, at `app/services/recovery_service.py:185-194`, `app/services/recovery_service.py:247-255`, and `app/services/recovery_service.py:399-460`. |

## Open Threats

| Threat ID | Component | Category | Mitigation Expected | Files Searched |
|---|---|---|---|---|
| T-04-07 | `tests/test_reasoning_flow.py` | Repudiation | Explicit assertions that persisted segment traces land on `MealSegment.ai_reasoning` and meal-level traces land on `MealLog.reasoning_state_json` before any final-write-ready result is accepted. Current test only checks returned dictionaries and readiness flags. | `tests/test_reasoning_flow.py` |
| T-04-09 | `tests/test_interview_flow.py` | Elevation of Privilege | Test coverage for rejecting callback-payload-as-truth by proving the handler resolves confirmation state from persisted `InterviewSession` rows instead of trusting callback contents. Current file only checks pinned-chat rejection. | `tests/test_interview_flow.py` |
| T-04-07 | `app/services/meal_resolution_service.py` | Repudiation | A single shared final-write boundary for all downstream write paths. `correction_service` bypasses `apply_final_meal_resolution()` and mutates `DiaryEntry` / `CorrectionEvent` directly, so later plans did fork the write path. | `app/services/meal_resolution_service.py`, `app/services/correction_service.py`, `app/services/interview_service.py`, `app/services/reasoning_service.py` |
| T-04-10 | `app/services/interview_service.py` | Tampering | Service-layer evidence that each interview step is persisted to `InterviewSession` and `InterviewMessage` before state advances. The service advances one question at a time and finalizes only after confirmation, but per-step persistence lives in handlers instead of the cited service component. | `app/services/interview_service.py`, `bot/handlers.py` |
| T-04-11 | `tests/test_interview_flow.py` | Repudiation | Test coverage for `is_verified=false` best-effort closeout. The file covers backbone, edit branches, reminder rule, and best-effort closeout count, but does not assert unverified finalization semantics. | `tests/test_interview_flow.py` |
| T-04-SC | `parser-model surface` | Tampering | Parser fallback pinned to `google/gemini-3.5-flash` after `google/gemini-3.1-flash-lite`, with local validation before mutation. Code validates locally, but the configured fallback is `google/gemini-3-flash-preview`, not `google/gemini-3.5-flash`. | `app/config.py`, `app/services/reasoning_service.py`, `tests/test_reasoning_flow.py` |

## Unregistered Flags

None. No `## Threat Flags` sections were present in `04-01-SUMMARY.md` through `04-08-SUMMARY.md`.

## Accepted Risks

None recorded.
