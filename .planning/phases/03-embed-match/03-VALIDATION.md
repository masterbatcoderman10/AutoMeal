---
phase: 03
slug: embed-match
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-27
---

# Phase 03 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Python `unittest` modules under `tests/` |
| **Config file** | none |
| **Quick run command** | `rtk .venv/bin/python -m unittest tests.test_bot_contract` |
| **Full suite command** | `rtk .venv/bin/python -m unittest discover -s tests -p 'test_*.py'` |
| **Estimated runtime** | ~10-30 seconds locally, excluding live OpenRouter smoke checks |

---

## Sampling Rate

- **After every task commit:** Run the smallest relevant Phase 3 test target plus `rtk .venv/bin/python -m unittest tests.test_bot_contract`.
- **After every plan wave:** Run `rtk .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`.
- **Before `/gsd-verify-work`:** Full suite must be green and manual/live calibration evidence must be recorded.
- **Max feedback latency:** 30 seconds for automated local tests; live embedding smoke checks may exceed this and should be isolated to Wave 0 and phase sign-off.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-W0-01 | TBD | 0 | MATCH-02 | T-03-01 | Embedding responses are validated for model, shape, and 1536 dimensions before any DB write. | unit + smoke | `rtk .venv/bin/python -m unittest tests.test_embedding_service` | No - W0 | pending |
| 03-W0-02 | TBD | 0 | MATCH-02 | T-03-02 | Same-image self-similarity >= 0.99 and the cross-modal `rice and lentils` sanity check rank the daal chawal target above random food before threshold matching is trusted. | smoke/manual | `rtk .venv/bin/python -m unittest tests.test_embedding_service` plus `rtk .venv/bin/python scripts/embed_match_smoke.py --mode calibrate --sample sample_images/IMG_4583.HEIC --same-food-peer sample_images/IMG_4584.HEIC --cross-modal-text "rice and lentils" --random-food sample_images/IMG_4585.HEIC` | No - W0 | pending |
| 03-MATCH-01 | TBD | 1 | MATCH-02, MATCH-03 | T-03-03 | Similarity uses `1 - cosine_distance`, only accepts score >= 0.85 from seeded `FoodVisual` rows, and persists the 1536-dimension `RETRIEVAL_QUERY` vector onto `MealSegment.embedding` before search. | integration | `rtk .venv/bin/python -m unittest tests.test_match_flow` | No - W0 | pending |
| 03-MATCH-02 | TBD | 1 | MATCH-03 | T-03-04 | Any below-threshold segment moves meal to `REASONING` and creates no `DiaryEntry` or new `FoodVisual`. | integration | `rtk .venv/bin/python -m unittest tests.test_match_flow` | No - W0 | pending |
| 03-VISUAL-01 | TBD | 2 | MATCH-04 | T-03-05 | Confirmed paths append a new `FoodVisual` row with a fresh `RETRIEVAL_DOCUMENT` write embedding; confirming same food twice creates two rows. | integration | `rtk .venv/bin/python -m unittest tests.test_match_flow` | No - W0 | pending |
| 03-BOT-01 | TBD | 2 | Phase 3 SC-4 | T-03-06 | Telegram completion push is best-effort after committed meal completion and cannot roll back DB writes. | unit | `rtk .venv/bin/python -m unittest tests.test_bot_contract` | Yes | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_embedding_service.py` - wrapper request shape, retry/error handling, vector-length validation, task type constants, and calibration helper behavior.
- [ ] `tests/test_match_flow.py` - seeded `FoodVisual` search, `MealSegment.embedding` persistence for `RETRIEVAL_QUERY`, all-or-nothing below-threshold branch, duplicate `FoodVisual` append, `RETRIEVAL_DOCUMENT` write-back, and atomic completion behavior.
- [ ] DB test helper or fixture for seeded `FoodItem`, `FoodVisual`, `MealLog`, and accepted `MealSegment` rows.
- [ ] Live or manually recorded calibration using local `sample_images/*.HEIC`, including same-image self-similarity >= 0.99, an operator-selected same-food/different-photo pair, and the `rice and lentils` text-vs-image sanity ranking.
- [ ] Explicit stop condition: if live calibration is degenerate, stop Phase 3 execution and evaluate alternate embedding model/dimensionality before implementing match flow.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Same-food re-photo match from seeded visuals | MATCH-03 | Needs real local food photos and live embedding behavior. | Seed a `FoodItem`/`FoodVisual`, process a different photo of same food, verify SIMILARITY score >= 0.85 and `DiaryEntry` creation without LLM/interview. |
| Cross-modal sanity check | MATCH-02 | OpenRouter/Gemini multimodal alignment must be verified against live provider response. | Embed text query `rice and lentils`, a daal chawal photo, and a random food photo; verify the daal chawal photo ranks closer than random food. |
| Telegram message content | Phase 3 SC-4 | Human-readable formatting and single-user chat delivery are easier to confirm against a real bot/chat. | Complete a meal and confirm message includes food name, portion bucket, macros, and verification status. |

---

## Validation Sign-Off

- [ ] All tasks have automated verify commands or Wave 0 dependencies.
- [ ] Sampling continuity: no 3 consecutive tasks without automated verification.
- [ ] Wave 0 covers all missing test files and live calibration prerequisites.
- [ ] No watch-mode flags.
- [ ] Feedback latency < 30 seconds for local test loop.
- [ ] `nyquist_compliant: true` set in frontmatter after Wave 0 tests exist and pass.

**Approval:** pending
