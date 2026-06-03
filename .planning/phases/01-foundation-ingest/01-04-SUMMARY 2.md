---
phase: 01-foundation-ingest
plan: 04
status: complete
completed: 2026-05-25
requirements: [INGEST-03]
---

# Plan 04 Summary: Telegram Bot Ack

## Completed

- Added separate Telegram bot service entry point using `Application.run_polling()`.
- Added `/start` and `/help` handlers.
- Added DB polling loop that claims `PENDING` meals with `FOR UPDATE SKIP LOCKED`.
- Added acknowledgement message formatting.
- Poll loop advances acknowledged meals to `DETECTING`.
- Poll loop re-raises `CancelledError` and disposes its engine on shutdown.

## Verification

- Bot imports pass in the project virtualenv.
- Bot image builds successfully.
- Container smoke with a fake Telegram bot object confirmed:
  - pending meal is found.
  - ack text is sent to configured chat id.
  - meal status advances from `PENDING` to `DETECTING`.

## Notes

- Real Telegram delivery requires replacing placeholder `.env` values with the actual bot token and chat id.
