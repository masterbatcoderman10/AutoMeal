---
phase: 02-vision-slice
plan: 04
subsystem: verification
tags:
  - vision
  - smoke
  - env
  - uat
  - openrouter

requires:
  - phase: 02-vision-slice
    provides: detect, segment, label, retry, IoU dedupe
provides:
  - Live OpenRouter smoke probe
  - Phase 2 env override docs
  - Phase 2 UAT evidence scaffold
affects:
  - phase: 02-vision-slice

tech-stack:
  added:
    - none
  patterns:
    - Smoke probe imports project services instead of duplicating API calls
    - HEIC samples transcode to local JPEG before smoke execution

key-files:
  created:
    - scripts/vision_smoke.py
    - .planning/phases/02-vision-slice/02-UAT.md
  modified:
    - app/config.py
    - .env.example
    - tests/test_bot_contract.py
    - .planning/phases/02-vision-slice/02-VALIDATION.md
    - .planning/ROADMAP.md
    - .planning/STATE.md

key-decisions:
  - "Smoke probing should fail closed on unusable detect/segment/label outputs."
  - "Local smoke should use temp crop paths, not container-only `/data/uploads/crops/`."
  - "Settings must ignore unrelated env keys so shared `.env` files do not break runtime utilities."

patterns-established:
  - "Phase verification scripts live under `scripts/` and import shared project services directly."
  - "UAT docs record exact evidence notes instead of only pass/fail tallies."

requirements-completed:
  - none

duration: 17m
completed: 2026-05-27
---

# Phase 02: Smoke And UAT Summary

**Implemented live smoke coverage, env override docs, and UAT evidence template**

## Accomplishments

- Added `scripts/vision_smoke.py` with `detect`, `segment`, `label`, and `all` modes using shared project services.
- Fixed a real runtime config bug discovered during smoke execution: `Settings` now ignores unrelated env keys instead of rejecting local `.env` files.
- Documented optional vision-stage model overrides in `.env.example`.
- Added `02-UAT.md` with repeatable checks for non-food silence, crop existence, soft-failure behavior, and grouped sample-image behavior.

## Verification

- `.venv/bin/python -m unittest tests.test_vision_service tests.test_bot_contract`
- `rtk rg -n "DETECT_MODEL|SEGMENT_MODEL|SEGMENT_RETRY_MODEL|LABEL_MODEL|VISION_MAX_SEGMENTS" .env.example`
- `rtk rg -n "IMG_4583|non-food|soft failure|crop" .planning/phases/02-vision-slice/02-UAT.md`
- `.venv/bin/python scripts/vision_smoke.py --mode all --sample sample_images/IMG_4583.HEIC`

## Live Smoke Result

- Sample `IMG_4583.HEIC` completed detect -> segment -> label on shared runtime path.
- Passing rerun produced three grouped segments: pita bread, vegetables, and chicken curry.
- One earlier rerun failed closed at detect with `{is_food: false, confidence: 0.0}`; keep that note as provider-drift evidence, not as a script bug.

## Known Stubs

- Manual Telegram and `/data/uploads/crops/` checks in `02-UAT.md` still need operator evidence.

## Next Phase Readiness

- Ready for end-of-phase review and verification gate.

---
*Phase: 02-vision-slice*
*Completed: 2026-05-27*
