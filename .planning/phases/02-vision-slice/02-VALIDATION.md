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
| 02-01-01 | 01 | 1 | VISION-01 | T-02-01 / transport drift | shared client forwards multimodal arrays and `extra_body` unchanged to the provider client | async contract | `.venv/bin/python -m unittest tests.test_bot_contract` | ✅ | ✅ green |
| 02-01-02 | 01 | 1 | VISION-01, VISION-02 | T-02-02 / model spoofing | detect path skips malformed or uncertain payloads but still continues when a meal is clearly present amid clutter | unit | `.venv/bin/python -m unittest tests.test_vision_service` | created in task 02-01-02 | ✅ green |
| 02-01-03 | 01 | 1 | VISION-02 | T-02-03 / false final message | non-food completion sends no final result message and detect worker lifecycle is clean | async contract | `.venv/bin/python -m unittest tests.test_bot_contract` | ✅ | ✅ green |
| 02-02-01 | 02 | 2 | VISION-03 | T-02-04 / bad coordinates | normalized boxes follow grouped-region rules and reject invalid ranges before persistence | unit | `.venv/bin/python -m unittest tests.test_vision_service` | created in 02-01-02 | ✅ green |
| 02-02-02 | 02 | 2 | VISION-04 | T-02-05 / wrong crop path | accepted segments persist crop JPEGs under `/data/uploads/crops/{segment_id}.jpg` | unit | `.venv/bin/python -m unittest tests.test_vision_service tests.test_bot_contract` | created in 02-01-02 | ✅ green |
| 02-02-03 | 02 | 2 | VISION-01, VISION-03 | T-02-06 / misleading labels | successful segment labeling uses dish-level labels for mixed foods, suppresses garnish noise, and emits one plain sentence | async contract | `.venv/bin/python -m unittest tests.test_bot_contract` | ✅ | ✅ green |
| 02-03-01 | 03 | 3 | VISION-03 | T-02-07 / partial invalid acceptance | any invalid box causes full-response rejection and stronger-model retry | unit | `.venv/bin/python -m unittest tests.test_vision_service` | created in 02-01-02 | ✅ green |
| 02-03-02 | 03 | 3 | VISION-03 | T-02-08 / double counting | IoU > 0.5 keeps only the stronger region before crop generation | unit | `.venv/bin/python -m unittest tests.test_vision_service` | created in 02-01-02 | ✅ green |
| 02-03-03 | 03 | 3 | VISION-02 | T-02-09 / user confusion | second segmentation failure sends one soft-failure message and marks the meal failed | async contract | `.venv/bin/python -m unittest tests.test_bot_contract` | ✅ | ✅ green |
| 02-04-01 | 04 | 4 | VISION-01, VISION-03, VISION-04 | T-02-10 / provider drift | smoke script exercises detect, segment, and label through shared runtime code and fails closed on parse or validator errors | script | `.venv/bin/python scripts/vision_smoke.py --mode all --sample sample_images/IMG_4583.HEIC` | created in task 02-04-01 | ⬜ pending |
| 02-04-02 | 04 | 4 | VISION-01 | T-02-11 / config drift | env template documents all optional vision settings and default behavior | source check | `rtk rg -n \"DETECT_MODEL|SEGMENT_MODEL|SEGMENT_RETRY_MODEL|LABEL_MODEL|VISION_MAX_SEGMENTS\" .env.example` | ✅ | ⬜ pending |
| 02-04-03 | 04 | 4 | VISION-03, VISION-04 | T-02-12 / unverifiable slice | UAT evidence records grouped sample-image behavior, crop files, and final Telegram output | doc check | `rtk rg -n \"IMG_4583|grouped|crop|non-food\" .planning/phases/02-vision-slice/02-UAT.md` | created in task 02-04-03 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

No standalone Wave 0 plan is required for Phase 2.

- `tests/test_vision_service.py` is created in Plan `02-01`, Task `2` before later verify steps depend on it
- `scripts/vision_smoke.py` is created in Plan `02-04`, Task `1`, and its first verify runs in that same task

Existing infrastructure covers the rest of the validation stack.

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
- [x] No standalone Wave 0 is required; every generated test/script artifact is created before its first dependent verify step
- [x] No watch-mode flags
- [x] Feedback latency < 20s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
