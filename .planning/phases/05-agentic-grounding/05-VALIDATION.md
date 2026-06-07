---
phase: 05
slug: agentic-grounding
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-04
last_audited: 2026-06-05
---

# Phase 05 - Validation Strategy

Per-phase validation contract for bounded grounding, runtime ownership caps, and authoritative finalizer/source handling.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Python `unittest` modules under `tests/` |
| **Config file** | none |
| **Quick run command** | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_bot_contract tests.test_match_flow tests.test_interview_schema tests.test_interview_flow -q` |
| **Full suite command** | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_contract tests.test_reasoning_flow tests.test_grounding_service tests.test_interview_flow tests.test_match_flow tests.test_bot_contract -q` |
| **Estimated runtime** | ~2-5 seconds for targeted Phase 05 slices in the container |

## Sampling Rate

- **After every task commit:** Run the smallest affected Phase 05 slice.
- **Runtime-cap slice:** `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_bot_contract tests.test_match_flow -q`
- **Authoritative-source slice:** `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_interview_schema tests.test_interview_flow -q`
- **After every plan wave:** Run the full Phase 05 targeted suite.
- **Before `/gsd-verify-work`:** Re-run the full targeted suite, then execute live compose-backed probes for real SearXNG/Firecrawl behavior.
- **Max feedback latency:** under 10 seconds for the targeted containerized suite.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-06-01 | 06 | 6 | GROUND-01, GROUND-02 | T-05-19, T-05-20, T-05-21 | Failed reasoning cannot become a save-ready fallback, and EMBEDDING/MATCHING workers keep exclusive ownership until the stage advances or fails. | unit/regression | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_flow tests.test_match_flow tests.test_bot_contract -q` | yes | green |
| 05-06-02 | 06 | 6 | GROUND-01, GROUND-02, GROUND-03 | T-05-19, T-05-20, T-05-21 | Shared bounded grounding finalizer, loop budgets, allowlist enforcement, degraded-save behavior, and grounding trace persistence remain intact after the gap fix. | targeted integration regression | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_contract tests.test_reasoning_flow tests.test_grounding_service tests.test_interview_flow tests.test_match_flow tests.test_bot_contract -q` | yes | green |
| 05-07-01 | 07 | 7 | GROUND-02 | T-05-22, T-05-23, T-05-24 | DETECTING and SEGMENTING workers keep the meal claim through slow work, and zero-segment MATCHING meals fail closed instead of stranding in bare `REASONING`. | unit/regression | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_bot_contract tests.test_match_flow -q` | yes | green |
| 05-08-01 | 08 | 7 | GROUND-01 | T-05-25, T-05-26, T-05-27 | Finalizer-facing `source_type` values are strict, and malformed authoritative output degrades explicitly instead of silently becoming `HOME`. | unit/integration regression | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_interview_schema tests.test_interview_flow -q` | yes | green |

*Status: `green` = automated evidence recorded on the current codebase.*

## Wave 0 Requirements

Existing `unittest` infrastructure covers all Phase 05 requirements and later gap-closure slices:

- `tests/test_reasoning_contract.py` - structured grounding/finalizer contract coverage.
- `tests/test_reasoning_flow.py` - fail-closed reasoning and grouped finalizer behavior.
- `tests/test_grounding_service.py` - bounded search/scrape budgets, allowlist, and duplicate-call handling.
- `tests/test_interview_flow.py` - inline grounding, degraded-save routing, trace persistence, and invalid authoritative finalizer output handling.
- `tests/test_interview_schema.py` - strict authoritative schema validation.
- `tests/test_match_flow.py` - verified-only matching, reasoning/final-write behavior, and matching-edge regressions.
- `tests/test_bot_contract.py` - runtime ownership, no-handoff bot behavior, and poller-side failure ordering.

No new framework, fixture family, or watch-mode workflow is required for Phase 05.

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live SearXNG/Firecrawl grounding against a real compose stack | GROUND-01, GROUND-02, GROUND-03 | Requires populated local `.env`, running services, and real HTTP behavior that unit tests mock. | Bring up the Phase 05 compose stack, run one packaged or restaurant meal through reasoning or post-interview grounding, and confirm `/search` -> allowlisted scrape -> bounded finalization completes without timeout or unbounded retries. |
| Telegram delivery and operator-facing grounding trace readability | GROUND-03 | Human-readable bot output and single-user chat delivery are easier to validate against the real bot/chat than with mocks alone. | Complete one grounded meal end-to-end and confirm the Telegram push includes the expected resolved item(s), provenance-friendly wording, and no duplicate completion messages. |

## Validation Sign-Off

- [x] All task slices have automated verification or documented live manual-only probes.
- [x] Sampling continuity is maintained across the executed gap-closure plans.
- [x] Wave 0 coverage already exists for every referenced Phase 05 test module.
- [x] No watch-mode flags or unstable long-running harnesses are required.
- [x] Feedback latency stays under 10 seconds for the targeted Phase 05 suite.
- [x] `nyquist_compliant: true` is set in frontmatter.

**Approval:** approved 2026-06-05

## Validation Audit 2026-06-05

| Metric | Count |
|--------|-------|
| Gaps found in current codebase | 0 |
| Resolved during this audit | 0 |
| Escalated | 0 |

- The existing `05-VERIFICATION.md` report is stale relative to the later executed gap-closure plans `05-07` and `05-08`; the live code and tests already close the three blockers it reported.
- Fresh automated evidence on the current codebase:
  - `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_bot_contract tests.test_match_flow -q` -> `Ran 100 tests ... OK`
  - `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_interview_schema tests.test_interview_flow -q` -> `Ran 66 tests ... OK`
  - `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_contract tests.test_reasoning_flow tests.test_grounding_service tests.test_interview_flow tests.test_match_flow tests.test_bot_contract -q` -> `Ran 192 tests ... OK`
- Critical regressions now present in the repository include:
  - `tests/test_bot_contract.py` coverage preventing duplicate DETECTING and SEGMENTING ownership.
  - `tests/test_interview_schema.py` coverage rejecting invalid authoritative `source_type` values such as `takeout?`.
  - `tests/test_interview_flow.py` coverage forcing malformed finalizer source typing into explicit degraded handling.
