---
phase: 02
slug: vision-slice
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-27
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Python `unittest` |
| **Config file** | none - standard library harness |
| **Quick run command** | `.venv/bin/python -m unittest tests.test_vision_service tests.test_bot_contract` |
| **Full suite command** | `.venv/bin/python -m unittest discover tests` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m unittest tests.test_vision_service tests.test_bot_contract`
- **After every plan wave:** Run `.venv/bin/python -m unittest discover tests`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | VISION-01 | T-02-01 / model spoofing | detect path only advances obvious meals and conservatively skips borderline input | unit | `.venv/bin/python -m unittest tests.test_vision_service` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | VISION-02 | T-02-02 / false final message | non-food completion sends no final result message and creates no segments | async contract | `.venv/bin/python -m unittest tests.test_bot_contract` | ✅ | ⬜ pending |
| 02-01-03 | 01 | 1 | VISION-01 | T-02-03 / orphaned workers | detect worker registration and shutdown are symmetrical | async contract | `.venv/bin/python -m unittest tests.test_bot_contract` | ✅ | ⬜ pending |
| 02-02-01 | 02 | 2 | VISION-03 | T-02-04 / bad coordinates | raw `0..1000` boxes normalize into valid `[0,1]` boxes before persistence | unit | `.venv/bin/python -m unittest tests.test_vision_service` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 2 | VISION-04 | T-02-05 / wrong crop path | accepted segments persist crop JPEGs under `/data/uploads/crops/{segment_id}.jpg` | unit | `.venv/bin/python -m unittest tests.test_vision_service` | ❌ W0 | ⬜ pending |
| 02-02-03 | 02 | 2 | VISION-01 | T-02-06 / misleading labels | successful segment labeling results in one plain-sentence Telegram message | async contract | `.venv/bin/python -m unittest tests.test_bot_contract` | ✅ | ⬜ pending |
| 02-03-01 | 03 | 3 | VISION-03 | T-02-07 / partial invalid acceptance | any invalid box causes full-response rejection and retry escalation | unit | `.venv/bin/python -m unittest tests.test_vision_service` | ❌ W0 | ⬜ pending |
| 02-03-02 | 03 | 3 | VISION-03 | T-02-08 / double counting | IoU > 0.5 keeps only the stronger region before crop generation | unit | `.venv/bin/python -m unittest tests.test_vision_service` | ❌ W0 | ⬜ pending |
| 02-03-03 | 03 | 3 | VISION-02 | T-02-09 / user confusion | second segmentation failure sends one soft-failure message and marks the meal failed | async contract | `.venv/bin/python -m unittest tests.test_bot_contract` | ✅ | ⬜ pending |
| 02-04-01 | 04 | 4 | VISION-01 | T-02-10 / provider drift | live smoke script fails closed when structured detect output cannot be parsed | script | `.venv/bin/python scripts/vision_smoke.py --mode detect --sample sample_images/IMG_4583.HEIC` | ❌ W0 | ⬜ pending |
| 02-04-02 | 04 | 4 | VISION-03 | T-02-11 / provider drift | live smoke script prints segment boxes and exits non-zero on invalid format | script | `.venv/bin/python scripts/vision_smoke.py --mode segment --sample sample_images/IMG_4583.HEIC` | ❌ W0 | ⬜ pending |
| 02-04-03 | 04 | 4 | VISION-04 | T-02-12 / unverifiable slice | UAT evidence records crop-file and Telegram-output checks for the sample image | doc check | `rtk rg -n \"Phase 2\" .planning/phases/02-vision-slice/02-UAT.md` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_vision_service.py` - add deterministic service-level fixtures for detect, segment, normalization, IoU, and label collapse
- [ ] `scripts/vision_smoke.py` - create the live OpenRouter smoke probe used by Wave 4

*Existing infrastructure covers all other phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Non-food photo produces no final Phase 2 result message | VISION-02 | requires live Telegram observation in the real bot chat | Submit a screenshot or receipt through the ingest path, confirm the existing Phase 1 ack appears, and confirm no follow-up result sentence appears after processing settles |
| Sample meal photo saves crop files and reports the expected grouped labels | VISION-03, VISION-04 | depends on live model output and real filesystem volume paths | Submit `sample_images/IMG_4583.HEIC`, then confirm one or more files exist under `/data/uploads/crops/` and confirm the Telegram result sentence groups bread, curry, and vegetables per the discussion context |

---

## Validation Sign-Off

- [x] All tasks have automated verify or explicit Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all missing references
- [x] No watch-mode flags
- [x] Feedback latency < 20s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
