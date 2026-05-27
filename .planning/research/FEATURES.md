# Feature Research

**Domain:** Personal photo-based meal tracker (single-user, Telegram-only surface, iOS Shortcut entry)
**Researched:** 2026-05-24
**Confidence:** MEDIUM-HIGH

## Executive Summary

The 2026 photo-meal-tracking landscape (Cal AI, Foodvisor, SnapCalorie, MyFitnessPal Premium, Cronometer Photo Logging, Bitesnap) converges on a common pipeline: **detect → segment → identify → estimate portion → confirm**. State-of-the-art accuracy sits around ±16–25% MAPE on calorie estimation for plated meals, dropping further for mixed/saucy dishes (±25–40%). This is the realistic accuracy bar — not perfection.

The single-user + Telegram-only + iOS Shortcut constraint dramatically narrows the feature surface. Most mainstream features (food search UI, barcode scanner UI, recipe builder, social/sharing, goals, gamification, on-device camera capture) are either out of scope per PROJECT.md or impossible without a mobile app surface. What remains is a tightly-scoped logger whose competitive edge is **the self-improving food vocabulary** (FoodVisuals growing per confirmed segment) — something Cal AI and SnapCalorie do not expose to users.

## Feature Landscape

### Table Stakes (Users Expect These)

Features the developer-as-user will expect from a credible 2026 photo meal tracker.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Photo → identified food with macros | Core promise of the product class | HIGH | Detect → segment → embed → match → reason pipeline already specified in PROJECT.md |
| Per-segment identification on multi-item plates | A plate of "salmon + rice + broccoli" must be three logged items, not one blob | HIGH | Schema already supports this (MealSegment[] per MealLog). Cal AI, Foodvisor, SnapCalorie all do per-item segmentation |
| Portion / quantity estimation | Calories without portion are meaningless | HIGH | Schema uses `quantity_multiplier` against `standard_quantity`. No depth sensor available (iOS Shortcut sends still photo, not LiDAR), so this is visual estimation only — accept ±20–30% error |
| Confirmation / clarification when uncertain | Industry-standard: confidence < ~0.7 → ask the user | MEDIUM | Telegram interview flow with structured `InterviewMessageKey` turns already designed |
| Per-meal nutrition feedback (calories + macros) | Without immediate feedback, logging feels invisible | LOW | Telegram push message once `MealLog` reaches COMPLETED status |
| Daily summary | "Did I eat reasonably yesterday?" is the core question a logger answers | LOW | APScheduler-driven message at 03:00 local, per PROJECT.md |
| Editing/correcting past entries | All major apps (MFP, Cronometer, Fitbit) support edit/delete of historical entries | MEDIUM | Via slash commands (`/edit`, `/delete`) targeting specific log IDs. Sets `IdentificationMethod.USER_CORRECTED` |
| Historical query (today, week) | Recall is the second core question a logger answers | LOW | `/today`, `/week`, `/summary` already specified |
| Restaurant / branded item handling | Real-world eating is not all generic foods | MEDIUM | Schema supports `FoodSourceType.RESTAURANT` / `PACKAGED` with `restaurant_name`/`brand_name`; grounded via SearXNG + Firecrawl tools |
| Acknowledgement on photo receipt | iOS Shortcut user needs immediate confirmation the photo arrived | LOW | Sync 200 + Telegram "processing…" message before async pipeline kicks off |
| Graceful "not food" handling | Camera roll inevitably contains non-food photos (screenshots, receipts, pets) | LOW | `MealProcessingStatus.NOT_FOOD` already in schema; bot sends a brief "not a meal — skipped" message |
| Meal category inference (breakfast/lunch/dinner/snack) | Daily summaries are unreadable without category buckets | LOW | Time-of-day heuristic; `MealCategory.UNKNOWN` as safe fallback (already in schema) |

### Differentiators (Competitive Advantage)

Features that make THIS build better than Cal AI / SnapCalorie *for this user*, given the constraints.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Self-improving visual vocabulary (FoodVisuals)** | After ~5–10 confirmations of "daal chawal," the system recognizes it in 200ms via vector search — no LLM call, no interview. This compounds. Mainstream apps don't expose or persist per-user visual learning. | HIGH | Core architectural bet. Already in schema. The differentiator IS the pipeline. |
| **Zero-friction entry via iOS Shortcut** | One tap (or one Siri command) sends the most recent photo. No app open, no scrolling, no "log meal" button. Faster than any consumer app. | LOW | Single endpoint + shared secret. The Shortcut itself is trivial. |
| **Agentic web-grounding for restaurant/branded items** | When AI sees a Domino's box or a Cheesecake Factory plate, it can search the actual menu via SearXNG + Firecrawl rather than guessing. Mainstream apps either fall back to user search or generic estimates. | MEDIUM | Tools wired into reasoning + post-interview stages per PROJECT.md |
| **Honest confidence surfacing** | When the system commits an entry it isn't sure about, `is_verified=false` is preserved and visible. Mainstream apps hide uncertainty behind a single number. | LOW | Already in `FoodItem.is_verified` and `IdentificationMethod`. Surface in per-meal message: "Logged as X (not yet confirmed — reply `/fix` to correct)" |
| **Structured Telegram interview (not freeform chat)** | `InterviewMessageKey` enforces a state machine: food name → source type → restaurant/brand → portion → confirm. Avoids the "AI rambles, user gets bored" failure mode that hurts conversational logging UX. | MEDIUM | State machine already in schema design. Bot SDK must persist session state across messages. |
| **Audit trail per identification** | Every DiaryEntry traceable to MealSegment → IdentificationMethod → similarity score / LLM reasoning / interview transcript. Lets the user debug their own data. | LOW | Schema already supports this via FK chain. Surface via `/why <entry_id>` command (small addition). |
| **Conversational query (free-text questions about diary)** | "How much protein did I have yesterday?" / "When did I last eat eggs?" — LLM with read-only DB access can answer these. Mainstream apps require navigating to specific report screens. | MEDIUM | Differentiator BUT may be over-scope for v1 — flag as v1.x |

### Anti-Features (Deliberately NOT Built)

| Feature | Why Requested (Surface Appeal) | Why Problematic Here | Alternative |
|---------|-------------------------------|---------------------|-------------|
| Calorie / macro goals + progress bars | Every consumer app has them | PROJECT.md explicitly excludes; goals imply judgment, this is a logger not a coach; "percent of goal" requires a goal | Absolute daily summary (eaten X kcal, Y g protein) without "of target" |
| Streaks, badges, gamification | Engagement mechanic | Excluded per PROJECT.md; single-user adherence is not the problem being solved | None — adherence comes from low friction, not extrinsic reward |
| Recipe builder / meal planner | "What should I eat next?" | Explicitly out of scope; this is a logger | None |
| Manual food-search UI | Standard fallback in every app | Excluded per PROJECT.md; the Telegram interview IS the manual path | Interview flow on low confidence |
| Mobile app | Native experience | Excluded per PROJECT.md; iOS Shortcut + Telegram covers the surface | iOS Shortcut for capture, Telegram for everything else |
| Direct image input via Telegram | Telegram already has image upload — why not? | Excluded per PROJECT.md; would split entry paths and complicate iOS Shortcut as the canonical source | iOS Shortcut → endpoint is the only photo path |
| Multi-user / family accounts | Common scaling assumption | Single-user by design; shared secret + pinned chat ID. Auth/OAuth would 10× the surface area | Hard-pin chat ID; reject anything else |
| Barcode scanner | Best accuracy for packaged foods (~100%) | Requires camera UI = requires app. iOS Shortcut can capture photos but not drive a barcode scanner flow naturally | Photo of the packaging + LLM reasoning + Firecrawl on brand name; lower accuracy but no app needed |
| Real-time / sub-minute latency | Snappy UX | Explicitly excluded; async is fine; LLM calls take seconds anyway | Ack immediately, push result when ready |
| Social sharing / feed | Engagement | Single user; nobody to share to | None |
| Continuous calorie display widget | iOS / Apple Watch lockscreen widgets | No app → no widget host; would require iOS dev | `/today` slash command provides the same info on demand |
| Voice-input meal logging | "I ate two eggs and toast" via voice | Out of scope and complicates the entry pipeline. iOS Shortcut → photo is the only entry | Photo is mandatory; no photo, no log |
| Water/hydration tracking | Common feature in nutrition apps | Out of scope drift; photo of water glass is low-value and beverages aren't the use case being optimized | If beverages appear in a meal photo, log them; no standalone hydration tracker |
| Mood / symptom journaling | Common adjacent feature | Scope drift; logger not journal | None |
| Pre-loaded comprehensive food database (USDA, etc.) | Industry standard (Cronometer: 680K items) | Conflicts with self-improving vocabulary thesis. Pre-seeding biases vector matches toward generic foods over user-specific (homemade, regional) ones | Empty FoodItems table at start; let it grow per confirmation. Optionally seed a small set of very common generics after v1 if cold-start is painful |

## Photo-to-Nutrition Pipeline: Detailed Expectations

Based on 2026 competitor research (Cal AI, Foodvisor, SnapCalorie, Cronometer):

### Accuracy Bar (Realistic Targets)

| Meal Type | Industry-Best MAPE | Notes |
|-----------|-------------------|-------|
| Packaged (barcode) | ~0% | N/A here — no barcode scanner; photo of label + grounding gets closer to ±5–10% |
| Single-item generic (apple, boiled egg) | ±10–15% | Vector match after a few confirmations should beat this for this user |
| Plated meal (protein + starch + veg) | ±15–25% | Cal AI claim; portion estimation is the dominant error |
| Mixed dishes (curry, stir-fry, soup) | ±25–40% | Hardest case industry-wide — accept and move on |
| Restaurant items | ±15–25% | Grounding via Firecrawl on menu page can tighten this significantly when the menu has nutrition info |

**Conclusion:** Aim for ±20% on average; don't pretend to do better. The self-improving vocabulary is the play — accuracy improves *for this user's actual diet* over time, even if the global accuracy is mediocre.

### Portion Estimation Constraints

Industry approaches:
- **Depth sensor / LiDAR** (Cal AI on iPhone Pro): not available here — iOS Shortcut sends a still photo, no depth map
- **Fiducial markers** (coin, hand): poor UX, not enforced by Shortcut
- **Plate-size heuristics** (assume standard 11-inch dinner plate): the realistic option here
- **User confirmation in interview**: `PORTION_CONTEXT` interview key already covers "full / half / double portion" disambiguation

**Decision implication:** Portion estimation will be the weakest stage. The interview's `PORTION_CONTEXT` question should be the standard fallback whenever portion confidence is low, even if food identity is high-confidence.

### Confirmation / Edit Flow

Industry pattern: confidence < ~0.70 → prompt user. The schema's confidence-driven gating matches this. Suggested thresholds (per PROJECT.md notes and competitor practice):

| Similarity / Confidence | Action |
|-------------------------|--------|
| ≥ 0.85 | Auto-match, commit silently (still surface in per-meal push) |
| 0.65–0.84 | LLM reasoning stage; commit if LLM self-reports ≥ threshold |
| < 0.65 or LLM low confidence | Telegram interview |
| Post-interview still low | Best-effort commit with `is_verified=false` (per PROJECT.md Key Decision) |

## Daily Summary UX (No-Goals Variant)

Mainstream summaries lean on "X% of goal." Without goals, what makes a summary coherent?

### Recommended Summary Content

```
Yesterday — 2026-05-23

Breakfast (08:14)
  • 2 fried eggs · 180 kcal · 14g P
  • Toast w/ butter · 220 kcal · 6g P

Lunch (13:20)
  • Daal chawal (homemade, full portion) · 540 kcal · 18g P
  • Cucumber salad · 30 kcal · 1g P

Dinner (20:45)
  • Chicken biryani (Student Biryani, half plate) · 620 kcal · 32g P

Total: 1,590 kcal · 71g P · 178g C · 56g F · 14g fiber

3 items auto-matched · 1 interviewed · 0 unverified
```

Coherence comes from:
- **Absolute numbers** (not percentages) — calories and grams stand alone as information
- **Time + category grouping** — gives the day a shape
- **Source attribution** — "homemade" vs "Student Biryani" tells the user where calories came from
- **Confidence footer** — "1 unverified" flags items the user might want to fix; this is the no-goals equivalent of a "review" prompt

**Verification:** Yes, absolute summaries without goals are coherent. Cronometer and MyNetDiary both support "track-only" modes; users in those modes still find macro breakdowns valuable as observational data. The job-to-be-done here is awareness, not optimization.

## Slash Command Surface

Already in PROJECT.md: `/today`, `/week`, `/summary`. Recommended extensions for v1:

| Command | Purpose | Complexity |
|---------|---------|------------|
| `/today` | Diary entries for today + running totals | LOW |
| `/week` | Last 7 days, daily totals + 7-day averages | LOW |
| `/summary` | Same as `/today` shape, takes optional date arg: `/summary 2026-05-22` | LOW |
| `/fix <entry_id>` | Replace identification on a past entry (triggers a mini-interview) | MEDIUM |
| `/delete <entry_id>` | Soft-delete a past entry (mistake / non-food slipped through) | LOW |
| `/last` | Repeat the last per-meal result message (in case user missed the push) | LOW |
| `/status` | Pipeline state of the most recent photo (DETECTING / SEGMENTING / etc.) — useful for debugging | LOW |
| `/why <entry_id>` | Show identification provenance (method, similarity, LLM reasoning) | LOW |

**Defer for v1.x:**
- `/find <food>` — "when did I last eat X?"
- `/stats` — meta stats (total foods learned, interviews triggered, etc.)
- Free-text query ("how much protein this week?") via LLM-over-DB

## Edge Cases: Handle vs Ignore

| Edge Case | Decision | Reasoning |
|-----------|----------|-----------|
| Drink-only entry (glass of juice) | **Handle** | The detector should accept it as food; one segment, one DiaryEntry. No special-casing |
| Multi-photo meal ("I took two pics of the same plate") | **Defer to v1.x** | Hash-based dedup of identical-image uploads is easy. Detecting "two angles of the same meal" semantically is hard. v1: each photo = one MealLog. User can `/delete` the redundant one |
| Continue-eating scenario (snack at desk over 30 min, multiple photos) | **Treat each as separate MealLog** | Simpler. User accepts that "snacking" shows as multiple entries. Don't try to merge automatically |
| Non-food photo (screenshot, pet, receipt) | **Handle gracefully** | Detector returns is_food=false → `MealProcessingStatus.NOT_FOOD` → Telegram: "Skipped — didn't look like a meal." Don't create a MealLog row (or create it with NOT_FOOD status and skip everything downstream) |
| Duplicate identical photo within short window | **Handle (image hash dedup)** | iOS Shortcut may fire twice if the user taps twice. Compute SHA256 of image bytes server-side; if seen in last 5 min, return the existing MealLog rather than creating a new one. LOW complexity, prevents annoying duplicates |
| Receipt photo (paper receipt from restaurant) | **Ignore for v1** | Useful in theory; out of scope. Detector will (correctly) flag it as not food |
| Recipe screenshot / cookbook page | **Ignore** | Same as above — not food in the photo |
| Very dark / blurry photo | **Let the detector decide** | If is_food confidence is below detection threshold, treat as NOT_FOOD with a different message: "Couldn't tell if this was food — retake?" |
| Empty plate / finished meal | **Defer** | Could be useful ("ate everything") but adds detector complexity. Just treat as a normal photo; if recognizable food remnants are visible the system will log them, otherwise NOT_FOOD |

## Feature Dependencies

```
iOS Shortcut → Endpoint
    └── requires ── Authenticated POST endpoint (shared secret)
                        └── enables ── MealLog creation

MealLog
    └── requires ── Detect stage (is_food classifier)
                        └── on positive ── Segment stage
                                              └── produces ── MealSegment[]

MealSegment
    └── requires ── Embedding model (multimodal)
                        └── enables ── pgvector match against FoodVisuals
                                          ├── high sim ── auto-resolve
                                          └── low sim ── LLM reasoning stage
                                                            ├── LLM tools (SearXNG + Firecrawl) for branded/restaurant
                                                            └── low confidence ── Interview

Interview
    └── requires ── Telegram bot state machine + InterviewSession + InterviewMessageKey flow
                        └── completes ── FoodItem create/update + FoodVisual append + DiaryEntry create

DiaryEntry
    └── enables ── /today, /week, /summary, daily push
    └── enables ── /fix, /delete (edit flows)

Self-improving vocabulary (FoodVisuals)
    ├── feeds ── faster matches over time
    └── requires ── every confirmation (any path) appends a FoodVisual

Per-meal push
    └── requires ── MealLog reaches COMPLETED status (all segments resolved)
    └── enhances ── /last command

Daily summary
    └── requires ── APScheduler + previous-day DiaryEntry query
    └── conflicts with ── nothing
```

### Dependency Notes

- **FoodVisuals append must happen on EVERY confirmation**, including interview-resolved and USER_CORRECTED paths. Missing this breaks the self-improvement loop entirely.
- **Interview state machine is required before per-meal push can be reliable** — pushing partial results mid-interview is bad UX. Wait for `MealProcessingStatus.COMPLETED`.
- **Daily summary requires meal_category inference** — without it, the summary is a flat list, much less useful.
- **Edit/correct flows depend on stable entry IDs surfaced to the user** — per-meal push must include the DiaryEntry IDs (or short hashes) so the user can reference them in `/fix` / `/delete`.
- **Web-grounding tools only matter if reasoning stage exists** — don't wire SearXNG/Firecrawl in before the LLM reasoning stage is functional.

## MVP Definition

### Launch With (v1)

- [ ] iOS Shortcut posts most recent photo to authenticated endpoint, gets immediate ack
- [ ] Detect → segment → embed → pgvector match pipeline runs end-to-end
- [ ] LLM reasoning stage (with web-grounding tools) when match is below threshold
- [ ] Structured Telegram interview (food name → source type → restaurant/brand → portion → confirm)
- [ ] FoodVisuals append on every confirmation (the learning loop)
- [ ] Per-meal Telegram push when MealLog completes
- [ ] Daily summary at 03:00 local
- [ ] `/today`, `/week`, `/summary` slash commands
- [ ] `/fix <entry_id>` and `/delete <entry_id>` for corrections
- [ ] Graceful NOT_FOOD handling with bot message
- [ ] Image-hash dedup within short window
- [ ] Confidence + verification status surfaced in per-meal messages

### Add After Validation (v1.x)

- [ ] `/last`, `/status`, `/why <entry_id>` debug-flavoured commands — add when the user starts wanting to inspect the system
- [ ] Free-text conversational queries over diary ("how much protein this week?") — add once base logging is stable
- [ ] `/find <food>` history search — add when diary grows large enough to need it
- [ ] Optional small generic-foods seed list — add only if cold-start recall is painfully bad in practice
- [ ] Multi-photo merge for the same meal — add if the user is observed taking multiple angles

### Future Consideration (v2+)

- [ ] Conversational diary analytics (trends, comparisons) — only if logging itself proves valuable
- [ ] Export to standard formats (CSV / Apple Health) — only if the data starts being useful outside the bot
- [ ] Whisper-based voice-note clarification in interview — nice-to-have, not core

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| iOS Shortcut → endpoint + ack | HIGH | LOW | P1 |
| Detect → segment pipeline | HIGH | HIGH | P1 |
| Embedding + pgvector match | HIGH | MEDIUM | P1 |
| LLM reasoning with tools | HIGH | MEDIUM | P1 |
| Structured Telegram interview | HIGH | MEDIUM | P1 |
| FoodVisuals self-improvement loop | HIGH | LOW (given schema) | P1 |
| Per-meal push message | HIGH | LOW | P1 |
| Daily summary | HIGH | LOW | P1 |
| `/today` / `/week` / `/summary` | HIGH | LOW | P1 |
| `/fix` / `/delete` corrections | HIGH | MEDIUM | P1 |
| NOT_FOOD graceful handling | MEDIUM | LOW | P1 |
| Image-hash dedup | MEDIUM | LOW | P1 |
| Confidence surfacing in messages | MEDIUM | LOW | P1 |
| `/why` / `/status` / `/last` | LOW | LOW | P2 |
| Free-text conversational query | MEDIUM | MEDIUM | P2 |
| `/find <food>` history search | LOW | LOW | P2 |
| Multi-photo merge | LOW | MEDIUM | P3 |
| Voice-note interview answers | LOW | MEDIUM | P3 |
| Export to Apple Health / CSV | LOW | LOW | P3 |

**Priority key:** P1 = must have for launch · P2 = add when stable · P3 = defer

## Competitor Feature Analysis

| Feature | Cal AI | Foodvisor | SnapCalorie | MyFitnessPal | Cronometer | **Our Approach** |
|---------|--------|-----------|-------------|--------------|------------|------------------|
| Photo recognition | Yes (LiDAR-assisted on Pro) | Yes | Yes | Premium only | Gold tier | Yes (no LiDAR, single still frame) |
| Per-item segmentation | Yes | Yes | Yes | Limited | Yes | **Yes** (MealSegment[]) |
| Portion estimation | Depth + visual | Visual | Visual | Manual | Visual + manual | Visual + interview fallback |
| Confidence-based confirmation | Yes (hidden) | Yes | Yes | N/A | Review screen | **Yes (explicit threshold + interview)** |
| Self-improving vocabulary | No (per-user) | No | No | No | No (database-driven) | **Yes — core differentiator** |
| Goals / streaks | Yes | Yes | Yes | Yes | Optional | **No (excluded)** |
| Restaurant menus | Limited database | Limited | Limited | Database | Database | **Agentic web grounding (SearXNG + Firecrawl)** |
| Mobile app | Yes | Yes | Yes | Yes | Yes | **No (Telegram + iOS Shortcut)** |
| Conversational clarification | Limited (in-app) | Limited | Limited | No | No | **Yes (structured Telegram interview)** |
| Edit past entries | Yes | Yes | Yes | Yes | Yes | Yes (`/fix`, `/delete`) |
| Daily summary | Yes (goal-centric) | Yes (goal-centric) | Yes (goal-centric) | Yes (goal-centric) | Yes (track-only mode supported) | **Yes (no-goal, absolute numbers)** |
| Auth model | Account | Account | Account | Account | Account | **Single shared secret, pinned chat ID** |

## Sources

- [Cal AI Review 2026: Is Photo Calorie Counting Accurate?](https://aumiqx.com/ai-tools/cal-ai-app-review-nutrition-tracker-2026/) — Accuracy benchmarks (±15–40% MAPE depending on meal type)
- [Nutrola vs Cal AI vs SnapCalorie: Best Photo Calorie Tracker 2026](https://nutrola.app/en/blog/nutrola-vs-cal-ai-vs-snapcalorie-photo-calorie-tracker-2026) — Comparative MAPE figures
- [How Photo Food Recognition Works: Computer Vision for Nutrition Tracking](https://askvora.com/technology/nutrition-ai) — Confidence thresholds and confirmation flow patterns
- [Image Recognition with Confirmation (LogMeal docs)](https://docs.logmeal.com/docs/guides-use-cases-food-recognition-confirmation) — Top-N candidate confirmation pattern
- [SnapCalorie Review (CalorieTrackerLab)](https://calorietrackerlab.com/reviews/snapcalorie/) — SnapCalorie ±19.8% MAPE; 76% category recognition
- [SnapCalorie vs MyFitnessPal (Foodiecal)](https://foodiecal.com/snapcalorie-vs-myfitnesspal-which-app-wins-for-smart-nutrition-tracking/) — Foodvisor ±16.2% MAPE
- [Cronometer Photo Logging](https://cronometer.com/blog/photo-logging/) — Review/confirm UX
- [Cronometer (general)](https://cronometer.com/index.html) — Track-only (no-goal) mode confirms absolute summaries are coherent
- [JMIR mHealth — Automatic Image Recognition Meal Reporting RCT](https://mhealth.jmir.org/2025/1/e60070) — Academic baseline for image-recognition meal logging
- [Food Portion Estimation via 3D Object Scaling (arXiv)](https://arxiv.org/html/2404.12257v1) — Portion estimation methods without fiducial markers
- [Image-based food portion size estimation using a smartphone without a fiducial marker (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC8115205/) — Fiducial-free portion estimation viability
- [Learning Personal Food Preferences via Food Logs Embedding (arXiv)](https://arxiv.org/pdf/2110.15498) — 82% recurrence of top-10 personal foods validates the self-improvement thesis
- [Continual Learning for Food Category Classification (arXiv)](https://arxiv.org/pdf/2603.19624) — Continual / per-user learning is an active research area
- [Telegram Bot Commands API](https://core.telegram.org/api/bots/commands) — Slash-command surface capabilities
- [foodbot (GitHub) — Telegram food logging bot in Go](https://github.com/lelika1/foodbot) — Reference implementation of conversational food logging on Telegram
- [Teaching AI to Clarify (Shane Chang)](https://shanechang.com/p/training-llms-smarter-clarifying-ambiguity-assumptions/) — Targeted single-question clarification beats option overload
- [How Accurate Is AI Food Logging? (Fuel Nutrition)](https://fuelnutrition.app/blog/ai-food-logging-accuracy-benchmarks-failure-modes-and-a-practical-audit) — Real failure modes (sauces, oils, second servings)
- [MyFitnessPal Help — Editing/Deleting Entries](https://support.myfitnesspal.com/hc/en-us/articles/360032623811-How-do-I-edit-or-delete-remembered-meals) — Industry-standard edit/delete pattern
- [Idempotency Implementation Patterns (Zuplo)](https://zuplo.com/learning-center/implementing-idempotency-keys-in-rest-apis-a-complete-guide) — Image-hash dedup pattern reference

---
*Feature research for: personal photo meal tracker (single-user, Telegram-only, no mobile app)*
*Researched: 2026-05-24*
