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
| **Quick run command** | `rtk .venv/bin/python -m unittest tests.test_reasoning_contract -q` once Wave 0 lands |
| **Full suite command** | `rtk .venv/bin/python -m unittest` |
| **Estimated runtime** | Recalculate after Wave 0 modules exist and run once |

---

## Sampling Rate

- **After every task commit:** Run the most specific targeted Phase 4 module for the touched surface.
- **After every plan wave:** Run `rtk .venv/bin/python -m unittest`.
- **Before `/gsd-verify-work`:** Full suite must be green plus one live smoke covering reasoning, confirmation edits, and janitor recovery.
- **Max feedback latency:** One task commit for targeted modules, one wave merge for the full suite.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-W0-01 | 04-01 | 0 | REASON-01, REASON-04 | T-04-05 | Strict model output parsing; no write on invalid reasoning contract | integration | `rtk .venv/bin/python -m unittest tests.test_reasoning_flow -q` | Planned in 04-01 | planned |
| 04-W0-02 | 04-01 | 0 | REASON-02 | T-04-05 | Top-3 candidates with rationale required before confidence gate | unit | `rtk .venv/bin/python -m unittest tests.test_reasoning_contract -q` | Planned in 04-01 | planned |
| 04-W0-03 | 04-01 | 0 | REASON-03 | T-04-06 | Deterministic gate uses similarity, margin, missing evidence, and nutrition-impact uncertainty | unit | `rtk .venv/bin/python -m unittest tests.test_reasoning_gate -q` | Planned in 04-01 | planned |
| 04-W0-04 | 04-01 | 0 | PIPELINE-01 | T-04-08 | Per-segment async fan-out cannot duplicate final writes or block sibling segments | integration | `rtk .venv/bin/python -m unittest tests.test_parallel_pipeline -q` | Planned in 04-01 | planned |
| 04-W0-05 | 04-02 | 0 | INTERVIEW-01, INTERVIEW-02, INTERVIEW-03, INTERVIEW-04 | T-04-09 | Telegram updates are pinned to the configured chat and DB-owned state | integration | `rtk .venv/bin/python -m unittest tests.test_interview_flow -q` | Planned in 04-02 | planned |
| 04-W0-06 | 04-02 | 0 | INTERVIEW-05, INTERVIEW-06 | T-04-13 | `/fix` invalidates only the offending `FoodVisual` and appends correction history | integration | `rtk .venv/bin/python -m unittest tests.test_fix_flow -q` | Planned in 04-02 | planned |
| 04-W0-07 | 04-02 | 0 | INFRA-04 | T-04-17 | Stale `*ING` recovery is bounded, retry-aware, and duplicate-notify resistant | integration | `rtk .venv/bin/python -m unittest tests.test_janitor -q` | Planned in 04-02 | planned |

---

## Wave 0 Requirements

- `04-01-PLAN.md` must create `tests/test_reasoning_contract.py`, `tests/test_reasoning_gate.py`, `tests/test_reasoning_flow.py`, `tests/test_parallel_pipeline.py`, and a live smoke path that reports prompt-cache and tracing metadata without making Phase 4 depend on either.
- `04-02-PLAN.md` must create `tests/test_interview_flow.py`, `tests/test_fix_flow.py`, and `tests/test_janitor.py`.
- `04-02-PLAN.md` must encode D-48 and D-49 in `tests/test_interview_flow.py`: item-specific confirmation edits, free-text bulk correction before write, updated confirmation replay, and the photo-aware `all wrong` branch.
- Plans `04-03` through `04-08` must all depend on Wave 0 before implementation begins.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live Telegram interview smoke | INTERVIEW-01, INTERVIEW-02, INTERVIEW-03 | PTB update routing and real chat pinning should be verified against the configured bot/chat once | Trigger a low-confidence segment, use confirmation edit and `all wrong`, confirm the updated confirmation is replayed, then confirm DB state advances only after final approval |
| Live janitor recovery smoke | INFRA-04 | Requires killing the worker mid-stage and waiting for the stale threshold | Kill the worker while a meal is in a machine stage, wait past the configured threshold, restart, and confirm reset or FAILED after the third recovery |
| Live OpenRouter reasoning smoke | REASON-01, REASON-02, REASON-03 | Model/provider behavior and prompt-cache metrics are external | Run one uncertain meal through reasoning twice with the same stable prompt/taxonomy, confirm top-3 structured output, trace persistence, deterministic gate behavior, and report any `cached_tokens` metadata |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or explicit Wave 0 ownership.
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify.
- [ ] Wave 0 coverage is mapped to concrete plan IDs and executable commands.
- [ ] No watch-mode flags.
- [ ] Feedback latency is measured after Wave 0 passes.
- [ ] `nyquist_compliant: true` is set only after Wave 0 executes successfully.

**Approval:** pending
