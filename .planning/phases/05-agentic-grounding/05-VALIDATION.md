---
phase: 05
slug: agentic-grounding
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-04
---

# Phase 05 - Validation Strategy

Per-phase validation contract for feedback sampling during Phase 05 gap closure.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Python unittest |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_flow tests.test_match_flow tests.test_bot_contract -q` |
| **Full suite command** | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_contract tests.test_reasoning_flow tests.test_grounding_service tests.test_interview_flow tests.test_match_flow tests.test_bot_contract -q` |
| **Estimated runtime** | ~60 seconds targeted, ~90 seconds full targeted suite |

## Sampling Rate

- **After every task commit:** Run the quick targeted Phase 05 gap suite.
- **After every plan wave:** Run the full Phase 05 targeted suite.
- **Before `/gsd-verify-work`:** Full unit discovery must remain green.
- **Max feedback latency:** 90 seconds for the Phase 05 targeted suite.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-06-01 | 06 | 6 | GROUND-01, GROUND-02 | T-05-19, T-05-20, T-05-21 | Failed reasoning cannot become save-ready fallback groups; concurrent workers cannot duplicate expensive stage work. | unit/regression | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_flow tests.test_match_flow tests.test_bot_contract -q` | yes | pending |
| 05-06-02 | 06 | 6 | GROUND-01, GROUND-02, GROUND-03 | T-05-19, T-05-20, T-05-21 | The gap fixes do not regress the previously verified grounding loop, trace, allowlist, degraded-save, and verified-only matching behavior. | targeted integration regression | `rtk docker run --rm -v "$PWD":/app -w /app mealttracker-plan05-test python -m unittest tests.test_reasoning_contract tests.test_reasoning_flow tests.test_grounding_service tests.test_interview_flow tests.test_match_flow tests.test_bot_contract -q` | yes | pending |

## Wave 0 Requirements

Existing Phase 05 test infrastructure covers this gap closure:

- `tests/test_reasoning_flow.py` - reasoning failure and grouped flow regressions.
- `tests/test_match_flow.py` - matching/final-write and worker-claim regressions.
- `tests/test_bot_contract.py` - polling/runtime contract regressions.
- `tests/test_grounding_service.py` - loop budget and allowlist regressions.
- `tests/test_interview_flow.py` - grounded finalizer and degraded-save regressions.
- `tests/test_reasoning_contract.py` - structured reasoning contract regressions.

## Manual-Only Verifications

All gap-closure behaviors have automated verification. Manual UAT remains the broader Phase 05 verification workflow after execution.

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or existing Wave 0 dependencies.
- [x] Sampling continuity: no 3 consecutive tasks without automated verify.
- [x] Wave 0 covers all missing references for the gap closure.
- [x] No watch-mode flags.
- [x] Feedback latency target is under 90 seconds for the Phase 05 targeted suite.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** pending execution
