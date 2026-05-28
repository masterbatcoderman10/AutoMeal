---
phase: 03
slug: embed-match
status: finalized
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-27
updated: 2026-05-28
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
| 03-W0-01 | 03-01 | 0 | MATCH-02 | T-03-01 | Embedding responses are validated for model, shape, and 1536 dimensions before any DB write. | unit + smoke | `rtk .venv/bin/python -m unittest tests.test_embedding_service` | Yes | green |
| 03-W0-02 | 03-01 | 0 | MATCH-02 | T-03-02 | Same-image self-similarity >= 0.99, `calibrate` requires a distinct same-food peer crop, and the cross-modal `rice and lentils` sanity check ranks the daal chawal target above random food before threshold matching is trusted. | smoke/manual | `rtk .venv/bin/python -m unittest tests.test_embedding_service` plus `rtk .venv/bin/python scripts/embed_match_smoke.py --mode calibrate --sample /data/uploads/crops/meal-a-seg-1.jpg --same-food-peer /data/uploads/crops/meal-b-seg-1.jpg --cross-modal-text "rice and lentils" --random-food /data/uploads/crops/random-seg-1.jpg` | Yes | unit green; live rerun pending |
| 03-MATCH-01 | 03-02 | 1 | MATCH-02, MATCH-03 | T-03-03 | Similarity uses `1 - cosine_distance`, only accepts score >= 0.85 from seeded `FoodVisual` rows, and persists the 1536-dimension `RETRIEVAL_QUERY` vector onto `MealSegment.embedding` before search. | integration | `rtk .venv/bin/python -m unittest tests.test_match_flow` | Yes | green |
| 03-MATCH-02 | 03-02 | 1 | MATCH-03 | T-03-04 | Any below-threshold segment moves meal to `REASONING` and creates no `DiaryEntry` or new `FoodVisual`. | integration | `rtk .venv/bin/python -m unittest tests.test_match_flow` | Yes | green |
| 03-MATCH-03 | 03-02 | 1 | MATCH-03 | T-03-05 | `FoodVisual.embedding` stays `Vector(1536)` and both ORM metadata plus the initial schema migration create the required PostgreSQL HNSW cosine index with `vector_cosine_ops`, `m=16`, and `ef_construction=64`. | unit | `rtk .venv/bin/python -m unittest tests.test_food_visual_contract` | Yes | green |
| 03-VISUAL-01 | 03-03 | 2 | MATCH-04 | T-03-05 | Confirmed paths append a new `FoodVisual` row with a fresh `RETRIEVAL_DOCUMENT` write embedding; confirming same food twice creates two rows. | integration | `rtk .venv/bin/python -m unittest tests.test_match_flow` | Yes | green |
| 03-BOT-01 | 03-04 | 2 | Phase 3 SC-4 | T-03-06 | Telegram completion push is best-effort after committed meal completion and cannot roll back DB writes. | unit | `rtk .venv/bin/python -m unittest tests.test_bot_contract` | Yes | green |

*Status: `green` = automated evidence recorded; `unit green; live rerun pending` = local tests are green but fresh crop-based smoke evidence is still tracked in `03-UAT.md`.*

---

## Wave 0 Requirements

- `tests/test_embedding_service.py` exists and now covers wrapper request shape, retry/error handling, vector-length validation, task type constants, and calibration helper behavior.
- `tests/test_match_flow.py` exists and now covers seeded `FoodVisual` search, `MealSegment.embedding` persistence for `RETRIEVAL_QUERY`, all-or-nothing below-threshold routing, duplicate `FoodVisual` append behavior, `RETRIEVAL_DOCUMENT` write-back separation, verified-flag persistence, and atomic completion behavior.
- `tests/test_embed_match_smoke.py` now covers the hardened smoke-helper contract: crop-only input enforcement, required same-food peer validation, and removal of the old whole-photo copy path.
- No dedicated DB fixture or checked-in crop fixture was added in Phase 03; automated coverage stays session-mocked, and live smoke evidence now depends on operator-supplied crop artifacts plus the reusable `scripts/embed_match_smoke.py` helper.
- Live/manual calibration evidence must now use real crop artifacts, and `calibrate` rejects both missing peers and byte-identical peer copies. The old `sample_images/*.HEIC` command is intentionally no longer valid; refreshed human evidence is tracked in `03-UAT.md`.
- The stop condition remains enforced operationally: calibration runs fail closed on embedding-contract or ranking regression before match work should be trusted.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Same-food re-photo match from seeded visuals | MATCH-03 | Needs real local food photos and live embedding behavior. | Seed a `FoodItem`/`FoodVisual`, process a different crop from a second photo of the same food, verify SIMILARITY score >= 0.85 and `DiaryEntry` creation without LLM/interview. |
| Cross-modal sanity check | MATCH-02 | OpenRouter/Gemini multimodal alignment must be verified against live provider response. | Embed text query `rice and lentils`, a daal chawal crop artifact, and a random-food crop artifact; verify the daal chawal crop ranks closer than random food. |
| Telegram message content | Phase 3 SC-4 | Human-readable formatting and single-user chat delivery are easier to confirm against a real bot/chat. | Complete a meal and confirm message includes food name, portion bucket, macros, and verification status. |

---

## Validation Sign-Off

- [x] All tasks have automated verify commands or resolved Wave 0 dependencies.
- [x] Sampling continuity maintained: no 3 consecutive tasks without automated verification.
- [x] Wave 0 now covers the missing smoke-helper tests and hardened crop-only command contract.
- [x] No watch-mode flags were introduced.
- [x] Feedback latency remains under 30 seconds for the local test loop.
- [x] `nyquist_compliant: true` is now set in frontmatter because Wave 0 tests exist and pass.

**Approval:** automated hardening is complete; fresh crop-based smoke/UAT reruns are still tracked in `03-UAT.md`.
