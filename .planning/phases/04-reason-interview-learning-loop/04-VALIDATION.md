---
phase: 04
slug: reason-interview-learning-loop
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-28
validated: 2026-05-29
---

# Phase 04 - Validation Strategy

> Retroactive Nyquist validation audit for the completed reasoning, interview, correction, and recovery loop.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Python `unittest` via `.venv/bin/python` |
| **Config file** | None; module-based discovery with `tests/__init__.py` |
| **Quick run command** | `rtk .venv/bin/python -m unittest -q tests.test_reasoning_contract tests.test_reasoning_gate tests.test_reasoning_flow tests.test_parallel_pipeline tests.test_interview_flow tests.test_fix_flow tests.test_janitor tests.test_bot_contract tests.test_embed_match_smoke tests.test_match_flow tests.test_matching_threshold` |
| **Full suite command** | `rtk .venv/bin/python -m unittest -q` |
| **Estimated runtime** | ~1.2s for the Phase 4 targeted suite |

---

## Sampling Rate

- **After every task commit:** Run the most specific Phase 4 module for the touched behavior.
- **After every plan wave:** Run the targeted Phase 4 suite listed above.
- **Before `/gsd-verify-work`:** Run `rtk .venv/bin/python -m unittest -q` and the three live manual smokes below.
- **Max feedback latency:** One task commit for targeted modules, one wave merge for the targeted Phase 4 suite.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 04-01 | 0 | REASON-01, REASON-02, REASON-03, REASON-04 | T-04-05, T-04-06 | Strict reasoning schema, top-3 candidate rationale, deterministic gate, unknown-action fallback | unit | `rtk .venv/bin/python -m unittest tests.test_reasoning_contract tests.test_reasoning_gate -q` | `tests/test_reasoning_contract.py`, `tests/test_reasoning_gate.py` | green |
| 04-01-02 | 04-01 | 0 | REASON-04, PIPELINE-01 | T-04-08 | Reasoning persistence and bounded per-segment fan-out before one finalization path | integration | `rtk .venv/bin/python -m unittest tests.test_reasoning_flow tests.test_parallel_pipeline -q` | `tests/test_reasoning_flow.py`, `tests/test_parallel_pipeline.py` | green |
| 04-02-01 | 04-02 | 0 | INTERVIEW-01, INTERVIEW-02, INTERVIEW-03, INTERVIEW-04, D-48, D-49 | T-04-09 | Pinned-chat DB-owned interview flow, confirmation edits, replay, and photo-aware all-wrong branch | integration | `rtk .venv/bin/python -m unittest tests.test_interview_flow tests.test_bot_contract -q` | `tests/test_interview_flow.py`, `tests/test_bot_contract.py` | green |
| 04-02-02 | 04-02 | 0 | INTERVIEW-05, INTERVIEW-06, INFRA-04 | T-04-13, T-04-17 | `/fix` mutation scope, visual invalidation boundaries, correction history, and stale recovery semantics | integration | `rtk .venv/bin/python -m unittest tests.test_fix_flow tests.test_janitor -q` | `tests/test_fix_flow.py`, `tests/test_janitor.py` | green |
| 04-03-01 | 04-03 | 1 | REASON-04, PIPELINE-01, INTERVIEW-01, INTERVIEW-02, INTERVIEW-05, INTERVIEW-06, INFRA-04 | T-04-05, T-04-09, T-04-13, T-04-17 | Phase 4 ORM/migration surfaces exist for reasoning, interview, correction, and recovery state | contract | `rtk .venv/bin/python scripts/check_schema_contract.py` | `scripts/check_schema_contract.py`, `migrations/versions/002_phase4_state_surfaces.py` | green |
| 04-04-01 | 04-04 | 1 | REASON-04, PIPELINE-01, INTERVIEW-03, INTERVIEW-05, INTERVIEW-06, INFRA-04 | T-04-05, T-04-13 | Shared final-write boundary, taxonomy validation, and no-op-safe tracing/config behavior | unit | `rtk .venv/bin/python -m unittest tests.test_reasoning_flow tests.test_fix_flow tests.test_bot_contract -q` | `tests/test_reasoning_flow.py`, `tests/test_fix_flow.py`, `tests/test_bot_contract.py` | green |
| 04-05-01 | 04-05 | 2 | REASON-01, REASON-02, REASON-03, REASON-04, PIPELINE-01 | T-04-05, T-04-06, T-04-08 | Production reasoning service, candidate snapshots, matching threshold, and reasoning-probe path | integration | `rtk .venv/bin/python -m unittest tests.test_reasoning_contract tests.test_reasoning_gate tests.test_reasoning_flow tests.test_parallel_pipeline tests.test_embed_match_smoke tests.test_match_flow tests.test_matching_threshold -q` | `tests/test_reasoning_contract.py`, `tests/test_reasoning_gate.py`, `tests/test_reasoning_flow.py`, `tests/test_parallel_pipeline.py`, `tests/test_embed_match_smoke.py`, `tests/test_match_flow.py`, `tests/test_matching_threshold.py` | green |
| 04-06-01 | 04-06 | 2 | INTERVIEW-01, INTERVIEW-02, INTERVIEW-03, INTERVIEW-04, PIPELINE-01 | T-04-09 | Durable Telegram interview progression, parser fallback, reminders, grounding handoff prep, and final confirmation routing | integration | `rtk .venv/bin/python -m unittest tests.test_interview_flow tests.test_bot_contract -q` | `tests/test_interview_flow.py`, `tests/test_bot_contract.py` | green |
| 04-07-01 | 04-07 | 2 | INTERVIEW-05, INTERVIEW-06 | T-04-13 | `/fix` target resolution, diff preview, confirm/cancel, scoped invalidation, and correction audit trail | integration | `rtk .venv/bin/python -m unittest tests.test_fix_flow tests.test_interview_flow tests.test_bot_contract -q` | `tests/test_fix_flow.py`, `tests/test_interview_flow.py`, `tests/test_bot_contract.py` | green |
| 04-08-01 | 04-08 | 2 | INFRA-04, PIPELINE-01 | T-04-17 | Artifact-first janitor recovery, single-instance scheduler wiring, retry exhaustion, and duplicate notification prevention | integration | `rtk .venv/bin/python -m unittest tests.test_janitor tests.test_bot_contract -q` | `tests/test_janitor.py`, `tests/test_bot_contract.py` | green |

---

## Requirement Coverage

| Requirement | Automated Coverage | Status |
|-------------|--------------------|--------|
| REASON-01 | `tests/test_reasoning_contract.py`, `tests/test_reasoning_flow.py`, `tests/test_embed_match_smoke.py` | covered |
| REASON-02 | `tests/test_reasoning_contract.py`, `tests/test_reasoning_gate.py`, `tests/test_match_flow.py` | covered |
| REASON-03 | `tests/test_reasoning_gate.py` | covered |
| REASON-04 | `tests/test_reasoning_flow.py`, `tests/test_parallel_pipeline.py`, `scripts/check_schema_contract.py` | covered |
| PIPELINE-01 | `tests/test_parallel_pipeline.py`, `tests/test_match_flow.py`, `tests/test_bot_contract.py`, `tests/test_janitor.py` | covered |
| INTERVIEW-01 | `tests/test_interview_flow.py`, `tests/test_bot_contract.py` | covered |
| INTERVIEW-02 | `tests/test_interview_flow.py`, `tests/test_bot_contract.py` | covered |
| INTERVIEW-03 | `tests/test_interview_flow.py`, `tests/test_bot_contract.py` | covered |
| INTERVIEW-04 | `tests/test_interview_flow.py` | covered |
| INTERVIEW-05 | `tests/test_fix_flow.py`, `tests/test_interview_flow.py`, `tests/test_bot_contract.py` | covered |
| INTERVIEW-06 | `tests/test_fix_flow.py` | covered |
| INFRA-04 | `tests/test_janitor.py`, `tests/test_bot_contract.py`, `scripts/recovery_smoke.py` | covered |
| D-48 | `tests/test_interview_flow.py` | covered |
| D-49 | `tests/test_interview_flow.py` | covered |

---

## Generated Test Files

No new test files were generated by this audit. The completed phase already contains the Wave 0 and implementation tests required to cover the discovered requirements.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live Telegram interview smoke | INTERVIEW-01, INTERVIEW-02, INTERVIEW-03, INTERVIEW-04 | PTB routing and real pinned-chat behavior require the configured bot/chat | Trigger a low-confidence segment, answer the structured prompts, use confirmation edit and `all wrong`, confirm replay, then confirm DB state advances only after final approval |
| Live janitor recovery smoke | INFRA-04 | Requires an actual interrupted worker and elapsed stale threshold | Kill the worker while a meal is in a machine stage, wait past the configured threshold, restart, and confirm resume or FAILED after the third recovery without duplicate notifications |
| Live OpenRouter reasoning smoke | REASON-01, REASON-02, REASON-03 | Model/provider behavior and prompt-cache metadata are external | Run one uncertain meal through reasoning twice with the same stable prompt/taxonomy, confirm top-3 structured output, trace persistence, deterministic gate behavior, and any `cached_tokens` metadata |

---

## Validation Audit 2026-05-29

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |
| Automated requirements covered | 14 |
| Manual-only operational smokes | 3 |

Audit notes:

- State A detected: `.planning/phases/04-reason-interview-learning-loop/04-VALIDATION.md` already existed.
- Phase artifacts read: `04-01` through `04-08` plans and summaries, plus `04-VERIFICATION.md`.
- Existing validation was stale (`planned` Wave 0 rows) relative to completed summaries and passing tests.
- Targeted Phase 4 suite passed on 2026-05-29: `Ran 110 tests in 1.138s, OK`.
- Schema contract passed on 2026-05-29: `schema contract ok`.
- Full unittest suite passed on 2026-05-29: `Ran 155 tests in 2.109s, OK`.
- Because no automated coverage gaps were found, the `gsd-nyquist-auditor` test-generation subagent was not spawned.

---

## Validation Sign-Off

- [x] All tasks have automated verify or explicit manual-only operational smoke coverage.
- [x] Sampling continuity: no 3 consecutive tasks without automated verify.
- [x] Wave 0 coverage exists for all discovered requirements.
- [x] No watch-mode flags.
- [x] Feedback latency measured for targeted Phase 4 suite.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** approved 2026-05-29
