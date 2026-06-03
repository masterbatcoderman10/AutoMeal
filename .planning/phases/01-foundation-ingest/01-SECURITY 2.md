---
status: complete
phase: 01-foundation-ingest
source:
  - .planning/phases/01-foundation-ingest/01-01-PLAN.md
  - .planning/phases/01-foundation-ingest/01-02-PLAN.md
  - .planning/phases/01-foundation-ingest/01-03-PLAN.md
  - .planning/phases/01-foundation-ingest/01-04-PLAN.md
  - .planning/phases/01-foundation-ingest/01-05-PLAN.md
  - .planning/phases/01-foundation-ingest/01-UAT.md
updated: 2026-05-26T20:41:20Z
---

# Phase 01 Security Verification

## Verdict

Phase 01 security controls are verified for the intended v1 deployment model: one trusted user, API reachable only locally or over Tailscale, shared-secret ingest authentication, internal-only grounding services, and gitignored runtime secrets.

No blocker was found for the completed Phase 01 foundation/ingest milestone. The remaining items are hardening follow-ups before broader exposure or before downstream phases parse uploaded image bytes more deeply.

## Threat Mitigation Results

| Area | Threat | Severity | Status | Verification |
|------|--------|----------|--------|--------------|
| Ingest auth | Missing or wrong shared secret allows unauthorized photo submission | HIGH | Verified | `POST /ingest/photo` accepts `X-Ingest-Secret`; missing and wrong secrets return 401 in `tests/test_ingest_contract.py` and live UAT. |
| Secret storage | Runtime secrets committed, inlined in Compose, or baked into image layers | HIGH | Verified | `.env` is ignored and untracked; Compose uses `${VAR}` substitution; `.dockerignore` excludes `.env`. |
| Database credentials | Postgres credentials hardcoded in tracked files or images | HIGH | Verified | `docker-compose.yml` derives app and Firecrawl DB credentials from environment variables. |
| API exposure | Ingest API exposed on all host interfaces by default | MEDIUM | Verified with deployment note | Compose defaults to `${API_HOST_BIND:-127.0.0.1}`; UAT used `0.0.0.0` only to support Tailscale reachability. This is acceptable only on the trusted local/Tailscale host. |
| Grounding services | Firecrawl/SearXNG reachable without auth from host network | MEDIUM | Verified | No host ports are published for Firecrawl, Redis, RabbitMQ, Playwright, Firecrawl Postgres, or SearXNG. They are Compose-internal only. |
| File path traversal | Client filename writes outside upload directory | MEDIUM | Verified | Ingest ignores client filenames and writes generated UUID paths under `UPLOADS_DIR / "meals"`. |
| Duplicate processing | Rapid duplicate upload creates repeated meal processing | LOW | Verified | Raw upload bytes are SHA-256 hashed before transcode; dedup query uses `image_hash` plus the configured time window. UAT confirmed duplicate response reuse. |
| Bot duplicate ack | Multiple bot workers acknowledge the same pending row | LOW | Verified | Bot claims rows with `FOR UPDATE SKIP LOCKED` and advances to `DETECTING` only after `send_message` succeeds. |
| Bot recipient | Bot sends meal acknowledgements to the wrong chat | MEDIUM | Verified for outbound acks | Acknowledgement sends use `settings.TELEGRAM_CHAT_ID`. Phase 1 inbound `/start` is informational only and not pinned yet; see hardening follow-ups. |
| OpenRouter key handling | API key leaked through logs or missing-key delayed failure | HIGH | Verified | Client is initialized from settings only; `get_llm_client()` fails fast when `OPENROUTER_API_KEY` is empty; no LLM calls run in Phase 1. |
| Schema safety | Missing `FAILED` state or wrong vector dimensions create unsafe recovery/match assumptions | HIGH | Verified | `scripts/check_schema_contract.py` passed; schema uses `Vector(1536)`, `FAILED`, TIMESTAMPTZ, and HNSW cosine index parameters. |

## Residual Risks

| Risk | Severity | Status | Notes |
|------|----------|--------|-------|
| Upload size guard is not enforced before reading the full file | MEDIUM | Accepted for Phase 01, harden in Phase 02 | Plan 03 explicitly deferred a 20 MB guard to Phase 2+. Current mitigation relies on single-user auth and typical iOS photo sizes. Add an explicit max-size check before downstream vision work. |
| `image/*` content types are trusted for non-HEIC passthrough | MEDIUM | Accepted for Phase 01, harden in Phase 02 | Non-image payloads with forged `image/jpeg` headers can be saved but are behind the ingest secret and are not parsed by Phase 1 except HEIC decode. Add image sniffing/Pillow verification before crop/vision processing. |
| Ingest secret comparison is ordinary string equality | LOW | Accepted for Phase 01 | Timing attacks are not practical under the local/Tailscale single-user model. Use `secrets.compare_digest()` before any public exposure. |
| Telegram `/start` and future command handlers are not chat-pinned yet | LOW | Accepted for Phase 01 | `/start` only reveals that the bot is active. Phase 6 command surface should reject all inbound updates whose chat ID differs from `TELEGRAM_CHAT_ID`. |
| SearXNG `secret_key` is currently static in `settings.yml` | LOW | Accepted for Phase 01 | SearXNG is internal-only and not an auth boundary. Prefer a non-default generated value if the service is ever exposed. |
| SearXNG settings mount is writable in the current dirty tree | LOW | Accepted for Phase 01 | A compromised SearXNG container could edit the host settings file. Restore `:ro` if compatible with the selected SearXNG image/config workflow. |

## Verification Run

- `.venv/bin/python -m unittest discover tests` -> 12 tests passed.
- `.venv/bin/python scripts/check_schema_contract.py` -> `schema contract ok`.
- `docker compose config` -> rendered successfully.
- `git check-ignore -v .env` -> `.env` ignored by `.gitignore`.
- `git ls-files .env --error-unmatch` -> `.env` is not tracked.

## Required Follow-Ups

These are not Phase 01 blockers, but should be handled before the system accepts less-trusted traffic or before Phase 2 performs image parsing/cropping at scale:

1. Add an upload byte limit, ideally enforced before full in-memory reads.
2. Verify image bytes independently of the client-supplied content type.
3. Use constant-time shared-secret comparison.
4. Add a Telegram chat allowlist guard for every inbound command handler.
5. Restore read-only service config mounts where containers do not need write access.
