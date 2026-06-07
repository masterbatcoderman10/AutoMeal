---
phase: 05-agentic-grounding
secured: 2026-06-05
asvs_level: 1
status: secured
threats_total: 7
threats_closed: 7
threats_open: 0
block_on: open
---

# Phase 05: Agentic Grounding Security Audit

Security audit of the Plan 07 and Plan 08 gap-closure threat register. This audit verifies only declared threats and their declared dispositions. Implementation files were treated as read-only.

## Threat Verification

| Threat ID | Category | Component | Disposition | Status | Evidence |
|-----------|----------|-----------|-------------|--------|----------|
| T-05-22 | DoS | `bot/polling.py` detect worker | mitigate | CLOSED | `bot/polling.py:423-443` selects a `DETECTING` meal with `FOR UPDATE SKIP LOCKED`, runs `detect_food_photo()` inside the owning session, transitions to `SEGMENTING` or `COMPLETED`, then commits only after the meal leaves the stage. Exception handling marks claimed meals `FAILED` at `bot/polling.py:446-456`. |
| T-05-23 | Integrity | `bot/polling.py` segment worker | mitigate | CLOSED | `bot/polling.py:484-542` selects a `SEGMENTING` meal with `FOR UPDATE SKIP LOCKED`, runs segmentation, dedupes segments, persists crop rows, transitions to `EMBEDDING`, and commits after crop persistence. The no-segment path fails immediately at `bot/polling.py:507-517`; exception handling marks the meal `FAILED` and removes created crops at `bot/polling.py:546-561`. |
| T-05-24 | Availability | `bot/polling.py` matching branch | mitigate | CLOSED | `bot/polling.py:859-866` checks segment rows for a `MATCHING` meal and transitions directly to `FAILED` when none exist. The previous zero-segment `REASONING` park is not present in this branch. |
| T-05-25 | Integrity | `app/services/interview_schema.py` | mitigate | CLOSED | `ConfirmationItem.source_type` and `FinalizedGroupResult.source_type` are typed as `Literal["HOME", "PACKAGED", "RESTAURANT"]` at `app/services/interview_schema.py:20` and `app/services/interview_schema.py:232`. Their validators call `parse_authoritative_source_type()` at `app/services/interview_schema.py:82-85` and `app/services/interview_schema.py:315-318`; that helper raises on malformed values at `app/services/grounding_stub.py:19-24`. |
| T-05-26 | Integrity | `app/services/grounding_stub.py` | mitigate | CLOSED | `build_grounding_prep(..., strict=True)` uses `parse_authoritative_source_type()` before deciding whether grounding is required at `app/services/grounding_stub.py:27-34`. The successful finalizer path passes `strict_source_type=True` at `app/services/interview_service.py:1662-1669`, and `final_resolution_from_confirmation()` threads that into strict parsing and strict grounding prep at `app/services/interview_service.py:1261-1278`. |
| T-05-27 | Repudiation | `app/services/interview_service.py` | mitigate | CLOSED | Malformed finalizer output raises `InterviewTurnValidationError` through `parse_group_finalizer_result()` at `app/services/interview_schema.py:394-400`. `_finalize_group_input()` records failed attempts and classifies the exception at `app/services/interview_service.py:1628-1637`, then returns `_degraded_group_finalizer_outcome()` at `app/services/interview_service.py:1642-1647`. The degraded audit state records `status: "DEGRADED"`, `error`, and `grounding_failure` at `app/services/interview_service.py:1715-1724`; the final save records `grounding_status: "DEGRADED_SAVED"` and `grounding_failure` at `app/services/interview_service.py:1406-1428`. |
| T-05-SC | Tampering | package-manager installs | accept | CLOSED | Accepted risk documented below. Plan summaries report no added tech stack: `.planning/phases/05-agentic-grounding/05-07-SUMMARY.md` frontmatter `tech-stack.added: []` and `.planning/phases/05-agentic-grounding/05-08-SUMMARY.md` frontmatter `tech-stack.added: []`. |

## Accepted Risks Log

| Threat ID | Category | Accepted Risk | Rationale | Review Trigger |
|-----------|----------|---------------|-----------|----------------|
| T-05-SC | Tampering | No package-manager install mitigation was implemented for this gap-closure slice. | The declared Plan 07 and Plan 08 scope did not include npm, pip, cargo, or other package-manager installs, and both summaries report `tech-stack.added: []`. | Reopen if a package-manager install, dependency change, lockfile update, or package execution step is introduced for this phase. |

## Unregistered Flags

None. No `## Threat Flags` section was present in `05-07-SUMMARY.md` or `05-08-SUMMARY.md`.

## Result

Threats closed: 7/7.
Threats open: 0.
ASVS Level: 1.
