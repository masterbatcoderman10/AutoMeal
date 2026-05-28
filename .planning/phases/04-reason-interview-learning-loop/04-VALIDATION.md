---
phase: 04
slug: reason-interview-learning-loop
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-28
---

# Phase 04 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Python `unittest` via `.venv/bin/python` |
| **Config file** | None; module-based discovery |
| **Quick run command** | `rtk .venv/bin/python -m unittest tests.test_match_flow -q` until Phase 4 targeted modules exist |
| **Full suite command** | `rtk .venv/bin/python -m unittest` |
| **Estimated runtime** | TBD after Wave 0 adds targeted Phase 4 tests |

---

## Sampling Rate

- **After every task commit:** Run the most specific new Phase 4 module for the touched surface.
- **After every plan wave:** Run `rtk .venv/bin/python -m unittest`.
- **Before `/gsd-verify-work`:** Full suite must be green plus one live smoke covering reasoning, interview completion, correction, and janitor recovery.
- **Max feedback latency:** TBD after Wave 0 creates targeted tests.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-W0-01 | TBD | 0 | REASON-01, REASON-04 | T-04-01 | Strict model output parsing; no write on invalid reasoning contract | integration | `rtk .venv/bin/python -m unittest tests.test_reasoning_flow -q` | No - W0 | pending |
| 04-W0-02 | TBD | 0 | REASON-02 | T-04-02 | Top-3 candidates with rationale required before confidence gate | unit | `rtk .venv/bin/python -m unittest tests.test_reasoning_contract -q` | No - W0 | pending |
| 04-W0-03 | TBD | 0 | REASON-03 | T-04-03 | Deterministic gate uses similarity, margin, missing evidence, and nutrition-impact uncertainty | unit | `rtk .venv/bin/python -m unittest tests.test_reasoning_gate -q` | No - W0 | pending |
| 04-W0-04 | TBD | 0 | PIPELINE-01 | T-04-04 | Per-segment async fan-out cannot duplicate final writes or block sibling segments | integration | `rtk .venv/bin/python -m unittest tests.test_parallel_pipeline -q` | No - W0 | pending |
| 04-W0-05 | TBD | 0 | INTERVIEW-01, INTERVIEW-02, INTERVIEW-03, INTERVIEW-04 | T-04-05 | Telegram updates are pinned to the configured chat and DB-owned state | integration | `rtk .venv/bin/python -m unittest tests.test_interview_flow -q` | No - W0 | pending |
| 04-W0-06 | TBD | 0 | INTERVIEW-05, INTERVIEW-06 | T-04-06 | `/fix` invalidates only the offending FoodVisual and appends correction history | integration | `rtk .venv/bin/python -m unittest tests.test_fix_flow -q` | No - W0 | pending |
| 04-W0-07 | TBD | 0 | INFRA-04 | T-04-07 | Stale `*ING` recovery is bounded, retry-aware, and duplicate-notify resistant | integration | `rtk .venv/bin/python -m unittest tests.test_janitor -q` | No - W0 | pending |

---

## Wave 0 Requirements

- [ ] `tests/test_reasoning_contract.py` - strict schema contract, unknown action handling, and retry-on-invalid behavior.
- [ ] `tests/test_reasoning_gate.py` - deterministic gate matrix for similarity, margin, missing evidence, and nutrition-impact uncertainty.
- [ ] `tests/test_reasoning_flow.py` - `MATCHING -> REASONING -> READY_TO_WRITE|PENDING_*` behavior and reasoning trace persistence.
- [ ] `tests/test_parallel_pipeline.py` - bounded per-segment fan-out and meal completion waiting for all segment outcomes.
- [ ] `tests/test_interview_flow.py` - callback plus free-text backbone, final confirmation, reminder behavior, and best-effort unresolved closeout.
- [ ] `tests/test_fix_flow.py` - `/fix` item selection, side-effect diff, invalidation scoping, and correction history.
- [ ] `tests/test_janitor.py` - stale-stage recovery, retry exhaustion, duplicate-notify suppression, and artifact-first reset logic.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live Telegram interview smoke | INTERVIEW-01, INTERVIEW-02, INTERVIEW-03 | PTB update routing and real chat pinning should be verified against the configured bot/chat once | Trigger a low-confidence segment, complete the interview from the pinned chat, confirm DB state advances and no out-of-chat update mutates state |
| Live janitor recovery smoke | INFRA-04 | Requires killing the worker mid-stage and waiting for the stale threshold | Kill the worker while a meal is in a `*ING` state, wait past the configured threshold, restart, and confirm reset or FAILED after retries |
| Live OpenRouter reasoning smoke | REASON-01, REASON-02, REASON-03 | Model/provider behavior and prompt-cache metrics are external | Run one uncertain segment through reasoning, confirm top-3 structured output, trace persistence, and deterministic gate decision |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies.
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify.
- [ ] Wave 0 covers all missing test modules listed above.
- [ ] No watch-mode flags.
- [ ] Feedback latency is measured after Wave 0.
- [ ] `nyquist_compliant: true` set in frontmatter after Wave 0 passes.

**Approval:** pending
