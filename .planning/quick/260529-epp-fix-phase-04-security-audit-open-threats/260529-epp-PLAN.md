---
quick_id: 260529-epp
slug: fix-phase-04-security-audit-open-threats
status: in_progress
created: 2026-05-29
---

# Quick Task 260529-epp: Fix Phase 04 Security Audit Open Threats

## Goal

Close the six open Phase 04 security-auditor findings without changing user-facing meal reasoning, Telegram interview, correction, or recovery behavior.

## Scope

1. Strengthen tests that provide missing mitigation evidence:
   - persisted segment and meal reasoning traces before final write
   - callback state loaded from `InterviewSession`, not callback payload truth
   - `is_verified=false` best-effort closeout finalization
   - parser model fallback order
2. Adjust implementation only where the auditor found a real boundary gap:
   - route confirmed entry corrections through the shared meal-resolution boundary
   - keep interview step persistence in the interview service layer
   - align parser fallback config to `google/gemini-3.5-flash`
3. Rerun targeted tests, then rerun Phase 04 security verification.

## Verification

- `python -m unittest tests.test_reasoning_flow tests.test_interview_flow tests.test_fix_flow tests.test_bot_contract -q`
- `python -m py_compile app/services/correction_service.py app/services/interview_service.py app/config.py bot/handlers.py`
- `$gsd-secure-phase 4` equivalent auditor rerun must return `threats_open: 0` or identify only new genuine issues.
