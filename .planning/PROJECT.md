# MealTracker

## What This Is

A photo-based personal meal tracker. An iOS Shortcut posts the most recently taken photo to a self-hosted endpoint; a Python pipeline runs detect → segment → embed → vector-match against a growing visual library, then reasons with web-grounding tools (SearXNG + Firecrawl) when uncertain, and falls back to a Telegram interview when its self-reported confidence stays below threshold. Confirmed items become DiaryEntries with pre-calculated nutrition; the Telegram bot pushes per-meal results, a daily summary, and answers slash-command queries.

## Core Value

Lowest-friction meal logging for one person: snap a photo, get logged nutrition with zero manual entry, and have the system get faster and more accurate the more I use it.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] iOS Shortcut posts the last-taken photo to an authenticated endpoint and receives an immediate ack
- [ ] Pipeline runs detect → segment → embed → pgvector match for every meal photo
- [ ] Self-improving food library: every confirmed segment writes a `FoodVisual` so future matches hit similarity threshold
- [ ] LLM stages self-report confidence; below threshold flags a segment for Telegram interview
- [ ] Reasoning and post-interview stages can call SearXNG and Firecrawl tools to ground branded/restaurant items
- [ ] Structured Telegram interview captures food name, source type, restaurant/brand, portion context, confirmation
- [ ] Bot pushes a per-meal result message once a `MealLog` is fully resolved
- [ ] Daily summary message at a configurable time (default 03:00 local) covering the previous day
- [ ] On-demand slash commands: `/today`, `/week`, `/summary`
- [ ] User can override an identification post-hoc (sets `USER_CORRECTED`)
- [ ] Entire stack runs as a single `docker-compose` on the Mac mini and is portable to a VM
- [ ] All LLM calls go through OpenRouter via the OpenAI SDK with a swapped `base_url`

### Out of Scope

- Mobile app — Telegram + iOS Shortcut covers the entry/output surface without app dev cost
- Real-time / sub-minute latency — async pipeline is fine for this use case
- Multi-user / OAuth — single-user personal tool; auth is a shared secret on the endpoint
- Manual food search UI — interview flow is the manual path
- Calorie goals, streaks, gamification — logging only for v1
- Recipe builder / meal planning — out of scope; this is a logger, not a planner
- Direct image input via Telegram — photos arrive only via the iOS Shortcut → endpoint path

## Context

- **Pre-work done:** Database schema designed in `MealTracker_Schema.mermaid` and `MealTracker_Schema_Types.ts` — entities (FoodItems, FoodVisuals, MealLogs, MealSegments, DiaryEntries, InterviewSessions, InterviewMessages), enums, and the pgvector setup notes. This schema is the starting contract.
- **Pipeline shape:** Detect (is-food binary) → Segment (bounding boxes per food item) → Embed (per-crop multimodal vector) → Vector match against `FoodVisuals` → if below confidence: LLM reason with tools → if still below: Telegram interview → optional re-grounding → `DiaryEntry` written, `FoodVisual` appended to grow vocabulary.
- **Interview is also the results channel:** the bot does push (per-meal + daily), interview (when uncertain), and on-demand queries. No app, by design.
- **Confidence-driven gating:** every LLM stage emits a brutally-honest confidence number; one threshold (configurable) decides whether to escalate to interview.
- **Hosting:** Mac mini for v1; docker-compose-clean so it lifts to any VM later.
- **LLM gateway:** OpenRouter is the single inference vendor; we use the OpenAI SDK and only change `base_url`. Model assignments per stage are pinned as Key Decisions below.
- **Grounding stack:** local SearXNG (search) + local Firecrawl (fetch & extract) exposed to LLMs as tools — used agentically when the model isn't confident about a brand or restaurant menu item.

## Constraints

- **Tech stack:** Python + FastAPI backend; Postgres + pgvector; python-telegram-bot (or equivalent async lib); APScheduler for daily-summary cron; all orchestrated via docker-compose.
- **LLM access:** OpenRouter only, via OpenAI SDK with swapped `base_url`. Forces verification of SDK feature parity (vision input, tool/function calling, structured outputs, streaming) through the OpenRouter compatibility layer.
- **Model pins (initial — verify in research):**
  - `google/gemma-4-31b-it` — classification (is-food)
  - `google/gemini-3-flash-preview` — segmentation, reasoning, interview
  - `google/gemini-3.1-flash-lite` — alternate cheaper interview tier
  - `google/gemini-embedding-2-preview` — multimodal embedding (dimensionality to confirm; schema currently assumes `vector(1024)`, may need adjustment)
- **Deployment:** single `docker-compose.yml` covering FastAPI app, Postgres+pgvector, SearXNG, Firecrawl, and any required worker/scheduler service. Mac mini today, VM-portable tomorrow.
- **Single user:** endpoint authentication is a shared secret; Telegram chat is hard-pinned to one chat ID.
- **Latency:** no hard SLA. Async pipeline; minutes is fine.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Pure FastAPI backend (no n8n) | Domain logic and interview state are tightly coupled; single codebase, one DB, one log stream is simpler than two services for solo dev | — Pending |
| OpenRouter as single LLM gateway via OpenAI SDK + base_url swap | One key, one billing surface, model swaps without code change; standard SDK surface | — Pending |
| Telegram is the entire output + clarification channel; no app for v1 | Avoids mobile app effort; Telegram already supports rich text, slash commands, conversational flows | — Pending |
| iOS Shortcut → POST endpoint as photo entry (not inbound Telegram) | Photos arrive automatically from camera roll without user action in chat | — Pending |
| Confidence-driven interview gating (LLM self-reports honestly, single threshold) | Avoids brittle hand-coded rules; same gate works for reasoning and post-grounding stages | — Pending |
| SearXNG + Firecrawl run locally as part of the stack, exposed as agentic tools | Keeps grounding self-contained, no third-party search API spend, brand/restaurant nutrition lookups stay reproducible | — Pending |
| Tool access scoped to reasoning + post-interview stages | Detection and segmentation don't need search; keeps prompts and costs lean | — Pending |
| Best-effort commit when post-interview grounding still below threshold (mark `is_verified=false`, no infinite loop) | Avoids annoying the user; manual override remains the escape hatch | — Pending |
| Daily summary at 03:00 local by default, configurable | Covers prior day cleanly without interrupting current-day logging | — Pending |
| Single `docker-compose.yml` for the whole stack | Mac mini → VM portability without rewrites | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-24 after initialization*
