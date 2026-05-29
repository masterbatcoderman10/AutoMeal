---
status: resolved
phase: 04-reason-interview-learning-loop
source:
  - 04-05-SUMMARY.md
  - 04-06-SUMMARY.md
  - 04-07-SUMMARY.md
started: 2026-05-29T10:54:47Z
updated: 2026-05-29T20:29:59Z
---

## Current Test

number: 1
name: Unknown Meal Starts Interview
expected: |
  Send a meal photo that the system is unlikely to know yet. In Telegram, the meal should not be silently guessed and completed. It should ask a clear follow-up question for the uncertain item.
awaiting: retest response

## Tests

### 1. Unknown Meal Starts Interview
expected: Send a meal photo that the system is unlikely to know yet. In Telegram, the meal should not be silently guessed and completed. It should ask a clear follow-up question for the uncertain item.
result: issue
reported: "it's been over 2 minutes, other than initial ack, I have received nothing"
severity: major

### 2. Structured Interview Reaches Confirmation
expected: Answer the Telegram prompts for food name, source type, brand or restaurant when applicable, and portion context. The bot should walk forward one question at a time and then show a confirmation instead of completing early.
result: [pending]

### 3. Confirmation Supports Edits
expected: At the confirmation step, change one answer instead of approving immediately. The bot should replay the updated confirmation with your edit reflected, then let you approve it.
result: [pending]

### 4. Completed Meal Uses Portion Words
expected: After approving the interview, the meal result should use discrete wording such as "~small portion", "~standard portion", or "~large portion". It should not show raw multipliers such as "0.63x".
result: [pending]

### 5. Fix Command Reopens Correction Flow
expected: Send `/fix <entry_id>` for the completed meal. Telegram should reopen a correction interview for that entry, show a preview of the change, let you confirm or cancel, and then send a concise correction confirmation.
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps

- truth: "Send a meal photo that the system is unlikely to know yet. In Telegram, the meal should not be silently guessed and completed. It should ask a clear follow-up question for the uncertain item."
  status: resolved
  reason: "User reported: it's been over 2 minutes, other than initial ack, I have received nothing"
  resolution: "Resolved by Phase 04.1 grouped reasoning/interview correction: unresolved food groups now create JSON-safe interview sessions and Telegram receives the active grouped follow-up prompt."
  severity: major
  test: 1
  root_cause: "The matching worker created an InterviewSession with current_prompt_payload.last_prompted_at as a Python datetime. SQLAlchemy JSON serialization rejected it, so the interview session insert rolled back before Telegram could send the follow-up. After that fix, the worker still sent only the generic unresolved placeholder, not the active interview question."
  artifacts:
    - path: "app/services/interview_service.py"
      issue: "Interview JSON payloads contained raw datetime objects."
    - path: "bot/polling.py"
      issue: "Unresolved handoff message omitted current_target_question prompt."
  missing:
    - "Normalize interview payloads to JSON-safe values before persistence."
    - "Include the active interview question in the unresolved Telegram message."
  debug_session: "inline-live-debug-2026-05-29"
