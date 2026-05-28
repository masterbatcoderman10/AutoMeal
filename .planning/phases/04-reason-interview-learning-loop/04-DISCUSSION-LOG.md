# Phase 4: Reason, Interview & Learning Loop - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves alternatives considered.

**Date:** 2026-05-28
**Phase:** 4-Reason, Interview & Learning Loop
**Areas discussed:** Reasoning criteria and process, Interview feel and Telegram flow, /fix correction flow, Segment concurrency and staged writes, Crash recovery and janitor behavior

---

## Reasoning Criteria And Process

| Option | Description | Selected |
|--------|-------------|----------|
| Segment-level reasoning | Reason each segment independently. | |
| Meal-level reasoning | Send original meal image and all crops together. | ✓ |
| Full FoodItem payload | Include nutrition in reasoning input. | |
| Identity-first payload | Include identity/source/verification/match metadata, not nutrition. | ✓ |
| Bucket quantity | Use small/standard/large. | |
| Intelligent quantity | Use grams/ml/count/composite units by food type, with ranges where useful. | ✓ |
| Closed action enum | Parser rejects unknown actions. | |
| Open action taxonomy | Known actions documented; unknown actions route to schema review. | ✓ |
| Prompt-only specificity | Put examples only in prompt. | |
| JSON taxonomy + prompt | Maintain editable taxonomy file and reference it in prompt. | ✓ |
| No Langfuse | Store only app DB reasoning JSON. | |
| Optional Langfuse | Add optional trace IDs and dashboard visibility without hard dependency. | ✓ |

**User's choice:** Meal-level reasoning with original image + all crops; identity-first match payload; intelligent quantity; additive detail; optional Langfuse.

**Notes:** User emphasized broad Asian-cuisine suitability, detailed food specificity, and nutrition-impact-based questioning. Reasoning must know chicken cuts, rice types, roll fillings, meat uncertainty, oiliness, and composite line items. `google/gemini-3.5-flash` replaces earlier Gemini 3 Flash target. Reasoning always runs, even when all segments match.

---

## Interview Feel And Telegram Flow

| Option | Description | Selected |
|--------|-------------|----------|
| Choice-first | Buttons for everything known. | |
| Text-first | Natural free-text chat. | |
| Hybrid | Buttons for known choices, free text for names/details/other. | ✓ |
| Fixed wizard | Always use roadmap interview states. | |
| Reasoning-driven | Only ask model-generated questions. | |
| Hybrid backbone | Roadmap states as fallback, reasoning skips known fields. | ✓ |
| One giant question list | Ask all uncertainties together. | |
| Adaptive sequence | One identity/detail at a time; group simple confirmations. | ✓ |
| No final confirmation | Auto-write after enough answers. | |
| Always final confirmation | Show final meal and allow edits before write. | ✓ |

**User's choice:** Hybrid Telegram UI, DB-backed state, final confirmation before write, brief evidence/context tone.

**Notes:** Free text parsing uses `google/gemini-3.1-flash-lite`, fallback `google/gemini-3.5-flash`. Ignored interviews get one reminder and then remain pending. Final logged result message is sent after confirmed write.

---

## /fix Correction Flow

| Option | Description | Selected |
|--------|-------------|----------|
| `/fix <entry_id>` only | Roadmap exact, less ergonomic. | |
| Bare `/fix` list | Show recent entries only. | |
| Both | Direct ID and recent-entry buttons. | ✓ |
| Identity only | Correct wrong food only. | |
| Full line item | Correct identity, quantity, components, source/detail. | ✓ |
| Mass invalidation | Invalidate many visuals on correction. | |
| Linked visual only | Invalidate only FoodVisual tied to corrected entry/segment. | ✓ |
| Always write new visual | Every correction teaches FoodVisuals. | |
| Useful visual only | Write new FoodVisual only if crop is visually useful. | ✓ |
| Overwrite correction | No history. | |
| Correction event | Append previous/new values and side effects. | ✓ |

**User's choice:** `/fix` supports direct and button selection, full line-item correction, linked-visual invalidation only, and useful-visual write-back only.

**Notes:** Quantity/source/component edits do not invalidate visuals. Unknown corrected foods should ask enough questions first, then create unverified/needs-grounding FoodItem if needed. Cancel leaves original entry unchanged.

---

## Segment Concurrency And Staged Writes

| Option | Description | Selected |
|--------|-------------|----------|
| Meal-level semaphore only | Concurrency across meals, not segments. | |
| Embed/match segment fanout | Parallelize per-meal segment embeddings and vector matches only. | ✓ |
| Full per-segment pipeline | Per-segment reasoning/interview. | |
| Keep match results in memory | Simpler but crash loses work. | |
| Persist match results | Store candidates/scores before reasoning. | ✓ |
| Best match only | One vector candidate. | |
| Top 3 matches | Up to 3 identity-first vector candidates. | ✓ |
| Threshold bypass | Skip reasoning when above threshold. | |
| Trusted prior signal | Threshold informs reasoning but never bypasses it. | ✓ |
| Dedicated worker now | Split bot/pipeline service in Phase 4. | |
| Keep current topology | Bot-owned polling workers remain for now. | ✓ |

**User's choice:** Parallelize only embedding/matching within a meal, default concurrency 4, persist top vector candidates, always run reasoning, keep current worker topology.

**Notes:** Match threshold changes to 0.90. Threshold is trusted prior, not direct write permission. Final writes happen in one transaction after all segments resolve and user confirms when needed.

---

## Crash Recovery And Janitor Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Reset to PENDING | Restart whole meal. | |
| Reset to last incomplete stage | Infer stage from artifacts and metadata. | ✓ |
| Mark failed on first timeout | Safe but brittle. | |
| 10-minute timeout | Original roadmap value. | |
| 5-minute timeout | Shorter active-stage stale detection. | ✓ |
| Per-meal global retry only | One counter. | |
| Hybrid retries | Global janitor cap plus per-stage call retries. | ✓ |
| Sent flags only | Avoid duplicates simply. | |
| Message IDs + sent flags | Editable interactive messages plus simple notification flags. | ✓ |
| FastAPI APScheduler | Run janitor from API scheduler. | ✓ |
| Bot polling task | Run janitor from bot service. | |

**User's choice:** Janitor runs in FastAPI APScheduler every 2 minutes, treats active machine stages stale after 5 minutes, resets to last incomplete stage, max 3 global recoveries.

**Notes:** Stale statuses are `DETECTING`, `SEGMENTING`, `EMBEDDING`, `MATCHING`, and `REASONING`. `INTERVIEWING` is waiting-user state and is not janitor-failed. `/retry` deferred.

---

## The Agent's Discretion

- Exact persistence shape for meal-level reasoning, match results, correction events, and interview sessions.
- Exact top-candidate floor, suggested around 0.65.
- Exact names of nutrition derivation statuses.
- Low-risk worker extraction only if planner sees clear benefit.

## Deferred Ideas

- Full grounding loop with SearXNG/Firecrawl.
- Full observability/custom dashboards beyond optional Langfuse tracing.
- `/retry <meal_id>`.
- Dedicated worker service split.
- Promotion of repeated additive detail into durable FoodItem profile data.
