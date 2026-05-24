# Pitfalls Research

**Domain:** Photo-based personal meal tracker — vision LLM pipeline (detect → segment → embed → vector match → agentic reasoning → Telegram interview), self-improving via FoodVisuals, self-hosted on Mac mini
**Researched:** 2026-05-24
**Confidence:** HIGH for domain-specific items (verified against multiple sources, recent literature); MEDIUM on Gemini Embedding 2 specifics (live-preview docs); MEDIUM on Gemini 3 Flash segmentation behavior (recent release, sparse field reports)

---

## Critical Pitfalls

The four pitfalls most likely to wreck this exact project shape, in priority order.

### Pitfall 1: Embedding dimensionality mismatch — schema assumes `vector(1024)`, Gemini Embedding 2 is natively 3072

**What goes wrong:**
The schema in `MealTracker_Schema_Types.ts` and the pgvector setup notes (`food_visuals.embedding vector(1024)`, `meal_segments.embedding vector(1024)`) hardcode 1024-dim vectors. Gemini Embedding 2 outputs **3072 dimensions** natively, with Matryoshka Representation Learning (MRL) allowing truncation to 1536, 768, etc. Critical detail: dimensions smaller than 3072 are **not normalized by default** — you must L2-normalize manually before cosine similarity is meaningful. A naive truncation to 1024 (not even a recommended MRL tier) produces vectors that look right but yield garbage similarity scores.

**Why it happens:**
The schema was written from a guess at dimensionality before the embedding model was finalized. "Multimodal" is also an assumption — if it turns out the chosen model isn't truly multimodal in the same space (e.g., images and text live in different sub-spaces or the model is text-only with an image encoder bolted on), text-vs-image retrieval breaks silently.

**How to avoid:**
- **Before any other vector work**, run a one-shot calibration script: embed 5–10 of your own meal photos and confirm output dimension, then verify text↔image similarity is meaningful (e.g., "rice and lentils" text should match a photo of daal chawal better than random text).
- Use one of the **MRL-recommended tiers** (3072, 1536, or 768) — not arbitrary 1024.
- If truncating below 3072, **manually L2-normalize** before insert AND before query.
- Make the vector column dimension a **migration variable**, not a hardcoded `1024`. Plan to `DROP INDEX` and `ALTER COLUMN` once the real number is known.
- Have a fallback plan: if Gemini Embedding 2 isn't fit-for-purpose (e.g., cross-modal alignment is weak on food), the alternates are SigLIP, OpenCLIP ViT-L/14, or Vertex multimodal embedding endpoint — each with different dimensions.

**Warning signs:**
- Self-similarity (same photo embedded twice) isn't ~1.0 → normalization issue.
- Random pairs cluster around 0.6–0.8 cosine similarity → anisotropy without calibration; threshold of 0.85 is meaningless.
- Text query matches every food roughly equally → cross-modal alignment is weak; do not trust this embedding space for cross-modal retrieval.

**Phase to address:**
**Phase 1 — Embedding & Vector Slice** (must be its own phase, before any pipeline wiring). Treat as a hard gate: dimensionality, normalization, and cross-modal sanity must be verified before building MealSegment matching.

---

### Pitfall 2: Self-poisoning FoodVisuals library — one wrong confirmation contaminates all future matches

**What goes wrong:**
The whole self-improvement story rests on `FoodVisual` rows being added on every confirmed match. But the confirmation source can be **bad data**:
- A SIMILARITY auto-match at 0.86 that was wrong → its embedding is now permanently associated with the wrong `food_item_id`.
- A USER_CORRECTED event arrives **after** a bad confirmation already added a poisoned visual — the old FoodVisual is still in the index and continues attracting future matches.
- An interview where the user clicked confirm without reading carefully.
Once poisoned, similarity attracts more wrong matches → those get auto-confirmed → poisoning compounds. RAG literature shows poisoning rates as low as 0.0005% of the corpus can shift retrieval behavior at 90% success.

**Why it happens:**
Schema has no mechanism to remove or down-weight FoodVisuals when an identification is later corrected. `IdentificationMethod.USER_CORRECTED` is recorded on the MealSegment, but the originally-written FoodVisual sticks around. There's also no notion of "this visual was confirmed once at 0.86 sim" vs. "confirmed 50 times across many photos" — all FoodVisuals are equal weight in the cosine search.

**How to avoid:**
- **Cascade USER_CORRECTED events** to the FoodVisual table. When a user corrects an identification, delete (or `is_invalidated=true`) the FoodVisual that was written from the original wrong identification. This requires `matched_visual_id` to be set on MealSegment (already in schema — confirm wiring populates it).
- **Don't write a FoodVisual on every confirmation in v1.** Only write on INTERVIEW completions (explicitly confirmed by user) and USER_CORRECTED. Skip SIMILARITY auto-matches at first — they're the riskiest source. Re-enable after a quality bar is hit.
- **Provenance audit table:** every FoodVisual stores `confirmation_source` (INTERVIEW, USER_CORRECTED, SIMILARITY_AUTO) so you can mass-delete a category if something goes wrong.
- **Periodic outlier detection:** for each FoodItem with >5 visuals, flag visuals whose mean cosine distance to siblings exceeds 2σ. Surface in a `/health` Telegram command.

**Warning signs:**
- Same wrong dish keeps re-appearing in matches after you corrected it once.
- A FoodItem's confirmed count grows but a substantial fraction of new matches are subsequently corrected.
- Cosine variance within a single FoodItem's visuals widens over time.

**Phase to address:**
**Phase 3 — Pipeline / Identification Loop.** The USER_CORRECTED → FoodVisual invalidation must ship in the same phase that introduces FoodVisual writes. Skipping it is a "looks done but isn't" disaster.

---

### Pitfall 3: LLM self-reported confidence is profoundly miscalibrated — "brutally honest" prompts do not fix this

**What goes wrong:**
The entire interview-gating decision rests on a single LLM-emitted confidence number being honest. Research is unambiguous: LLMs are massively overconfident, especially when wrong. GPT-4 has been observed assigning its highest confidence to 87% of responses including factually wrong ones. Asking the model to be "brutally honest" or "are you sure?" produces sycophantic re-affirmation, not introspection — the model is predicting plausible next tokens, not performing genuine uncertainty estimation. Result: the gate fires too rarely on confident-wrong, too often on cautious-correct, and the threshold you picked in week 1 will be invalidated by every model update.

**Why it happens:**
Verbalized confidence is just another generation; calibration error (ECE) is typically 0.15–0.25 even for SOTA models. Confidence is also non-stationary across model versions and across providers (relevant given OpenRouter routes across providers — see Pitfall 5).

**How to avoid:**
- **Do not rely on a single self-reported score.** Cross-check with a second signal:
  - For SIMILARITY: the vector distance is an independent signal — gate on `min(llm_confidence, normalized_similarity)`.
  - For LLM identification with no vector match: require the LLM to produce **top-3 candidates with structured outputs**; gate on margin (`p1 - p2`), not raw `p1`. Low margin → interview.
  - Add an **abstention prompt** explicitly listing "if you are not at least 90% sure this is the named food, return `unknown`." Models are better at binary "do I know this?" than at calibrated numerical probability.
- **Calibrate empirically.** Log every (predicted_confidence, ground_truth_post_interview) pair. After 50 meals, plot a reliability diagram. Adjust threshold to the value where actual accuracy matches stated confidence — don't trust the default 0.85.
- **Treat threshold as model-version-pinned.** If you upgrade `google/gemini-3-flash-preview` → next version, recalibrate before trusting old thresholds.
- **Bias toward escalation, not toward auto-commit.** A wrong silent auto-commit is unrecoverable without manual review; an unnecessary interview is mildly annoying.

**Warning signs:**
- `times_confirmed` grows but USER_CORRECTED count tracks proportionally — silent miscalibration.
- LLM emits the same confidence number (0.85, 0.9) for nearly every call regardless of input difficulty.
- Threshold sweeps in retrospective analysis show no clean operating point.

**Phase to address:**
**Phase 3 — Pipeline / Identification Loop.** Build the multi-signal gate from day one. **Phase 5 — Calibration & Quality** (post-MVP): empirical reliability-diagram-driven threshold tuning.

---

### Pitfall 4: Portion estimation is the dominant nutrition error, not food identification

**What goes wrong:**
Research consistently identifies **portion size as the largest source of error** in end-to-end AI calorie tracking, with errors of 20–40% on real meals — far larger than identification error. Without a depth reference (LiDAR, fiducial marker, hand-in-frame), monocular images fundamentally cannot recover real-world scale. A "1.0x portion of rice" is a guess dressed up as a number. If users see calorie totals that are confidently wrong by 30%, trust in the whole system collapses — and unlike a misidentification, the user can't easily detect a portion error from the message text.

**Why it happens:**
- Scale recovery from a single image is an underdetermined problem.
- The schema's `quantity_multiplier` field implies a precision the vision step cannot deliver.
- The LLM will happily emit "0.75x" because we asked for a number, not because it has a basis.

**How to avoid:**
- **Be honest about portion confidence in v1.** Emit a discrete bucket — `small | standard | large` — not a continuous multiplier. Map to 0.5 / 1.0 / 1.5 internally. Users perceive bucket errors as reasonable; precision-looking-but-wrong numbers as broken.
- **Always interview on portion** until you have data showing the model is reliable. Add a `PORTION_CONTEXT` interview turn (already in schema) that's mandatory, not optional.
- **Surface portion uncertainty in the Telegram message.** "~1 cup rice (rough estimate)" sets expectations correctly.
- **Out of scope for v1: depth recovery, fiducials, 3D reconstruction.** Note this explicitly in PROJECT.md; revisit only if v1 ships and accuracy bites.
- **Don't denormalize wrong totals.** Make `MealLog.total_calories` etc. computed on the fly from DiaryEntries until portion estimation has a known error bar.

**Warning signs:**
- Daily calorie totals that are systematically off by a consistent factor (you weighed a sample meal and got 600 kcal, system reported 900).
- Same dish reported with wildly different multipliers across photos.
- User starts ignoring the bot's nutrition numbers.

**Phase to address:**
**Phase 3 — Pipeline / Identification Loop** (use buckets, not continuous multipliers). **Phase 5 — Calibration & Quality** (empirical portion error measurement, optional fiducial marker).

---

### Pitfall 5: OpenRouter silent feature gaps — model swap breaks tool calling, vision, or structured output

**What goes wrong:**
The architecture is built on "OpenRouter + OpenAI SDK + `base_url` swap" as if it's a no-op. Real failure modes:
- Not every model supports tool calling. Swap from `gemini-3-flash-preview` to a cheaper alternative and tools silently stop being called (no error, just no tool_call in response).
- Not every model supports structured outputs (`response_format=json_schema`). Some support "JSON mode" (free-form JSON) but not schema enforcement.
- Some models support vision but reject base64-encoded images over a size limit, or accept only URLs, or have a tokens-per-image quirk.
- OpenRouter's **default provider routing** load-balances across providers — same model name can hit different providers with subtly different behavior (reasoning enabled vs. disabled, different tokenizers, different rate limits). Documented bugs include fallback configs ignoring requested provider order.
- Tool-calling + structured-output simultaneously is buggy across the stack (documented OpenAI Agents SDK issue: structured output suppresses tool calling).

**Why it happens:**
"Drop-in compatibility" is marketing — the surface is OpenAI-shaped but feature support is per-model AND per-provider, not uniform.

**How to avoid:**
- **One model per stage, pinned, with explicit provider preference.** Use OpenRouter's `provider.order` + `provider.allow_fallbacks=false` initially to lock to one provider. Add fallbacks only after the primary is proven.
- **Capability smoke tests.** Before relying on a model, run a fixture test: (1) accepts image input, (2) emits a tool call when given a tool, (3) emits valid JSON-schema-constrained output. Fail loud at startup if any capability is missing.
- **Don't combine structured output + tool calling in the same call** unless you've verified it works on the exact model. Split: tool-using reasoning call → free-text answer → second call with `response_format` to structure the answer.
- **Log the actual `model` and `provider` returned in every response** (OpenRouter surfaces this) — gives you a paper trail when behavior changes.
- **Track cost per stage.** Cheap models doing 10 tool calls cost more than expensive models doing 1. Set a per-meal budget cap.

**Warning signs:**
- Pipeline runs but no segments come back → vision didn't actually see the image.
- LLM returns text reasoning instead of calling a tool → tool support absent.
- JSON parse errors despite `response_format` being set → schema enforcement not honored by provider.
- Same prompt, same model name, different answers on different days → provider routing flipped.

**Phase to address:**
**Phase 0 — Foundation / LLM Gateway.** Capability smoke tests are part of "stack is alive." **Phase 2 — Vision Slice** (verify per-stage). Provider pinning is a v1 decision, not a v2 polish.

---

### Pitfall 6: Vision LLM bounding box hallucinations on composite plates

**What goes wrong:**
Gemini and similar vision models are known to **hallucinate bounding boxes** — fabricate coordinates, drift coordinates so the crop misses the actual food, return a different count of boxes than items present, or "see" food that isn't there. On composite/layered plates (biryani with raita and salad on one platter, a thali with 6 compartments, a sandwich with visible filling) the problems compound: under-segmentation merges items into a single nutrition entry; over-segmentation creates duplicate ghost items; crops misalign so the embedding step ingests background or adjacent food.

The downstream effect is invisible: a hallucinated box produces an embedding, which produces a similarity score, which gets logged as a DiaryEntry. Double-counting is silent.

**Why it happens:**
Coordinate output is text generation, not perception. The model predicts plausible-looking coordinates conditioned on having identified some food was present. Gemini 3 Flash's "agentic vision" with code execution improves this but does not eliminate it.

**How to avoid:**
- **Validate every box before cropping:** coordinates within [0,1], y0<y1, x0<x1, area > minimum (e.g., 1% of image), max boxes per image (e.g., 8). Reject the whole segmentation and re-prompt if violated.
- **Round-trip sanity check.** After segmentation, ask the same model (or a cheap classifier) "does this crop contain food? what is it?" — if the crop comes back as "not food" or as something incompatible with the original label, drop the segment.
- **Cap segment count per meal at 6–8.** If model returns 15 boxes for a single plate, it's hallucinating. Force a re-segmentation or take top-K by claimed confidence.
- **IoU dedup.** Compute pairwise IoU between all boxes; merge or drop overlapping ones (>0.5 IoU) — prevents double-counting the same food.
- **Composite plates: ship the "single dish per photo" guidance to yourself.** v1 user behavior tip: photograph one plate per shot. Don't try to solve thali-style multi-compartment plates perfectly in v1.

**Warning signs:**
- Daily calorie totals 2x reality → likely double-counting from overlapping boxes.
- Crops that show background, plate edge, or empty table → coordinate drift.
- Segment count varies wildly for visually similar photos.
- A photo of one item produces 3 DiaryEntries.

**Phase to address:**
**Phase 2 — Vision Slice** (box validation, IoU dedup, count cap, round-trip check are all part of "segmentation is done").

---

### Pitfall 7: Agentic tool-use infinite loops and cost blowouts

**What goes wrong:**
Reasoning + post-interview stages have access to SearXNG and Firecrawl as tools. Failure modes:
- Model calls SearXNG → no good result → calls SearXNG with a rephrased query → no good result → repeats. Burns tokens, money, latency, with no progress.
- Model fabricates URLs not from search results and asks Firecrawl to fetch them — wastes a heavy browser invocation.
- Model trusts low-quality SEO content from search results and writes confident-wrong nutrition into a FoodItem.
- Each tool call adds latency; if the meal pipeline is async this is fine, but cost compounds. A cheap-feeling Flash model doing 12 tool calls costs more than one Pro call.
- "Resource amplification" — model keeps calling tools until hitting max_tokens, then returns mid-thought.

**Why it happens:**
LLMs are bad at recognizing "I have enough information" and bad at recognizing "more searches won't help."

**How to avoid:**
- **Hard cap iterations.** Max tool calls per stage = 5. After the cap, force a final answer with whatever info is on hand.
- **Per-meal wall-clock budget.** Max 60 seconds of tool-use time per meal. After timeout, commit best-effort with `is_verified=false` (already a Key Decision in PROJECT.md — wire it).
- **Tool-call deduplication.** Reject a tool call if the same tool was called with semantically similar args in the last 2 steps. Force a different action.
- **URL allowlist for Firecrawl.** Only fetch URLs that appeared in a previous SearXNG result this session. Block model-fabricated URLs.
- **Per-meal cost budget.** Cap total token spend per meal (e.g., $0.05). Log and alert if exceeded.
- **Domain whitelist for "trustworthy" nutrition info.** A SEO recipe blog isn't a source for `calories_per_unit`. Prefer USDA FoodData Central, manufacturer sites for branded items, restaurant's own menu for restaurant items. If model can't reach a whitelist source, mark `is_verified=false` and move on.

**Warning signs:**
- Pipeline routinely takes >60s end-to-end.
- OpenRouter spend graphs spiking per-meal.
- FoodItems being created with `llm_reasoning` referencing dubious sources.
- Same query string appearing 4+ times in a single session's SearXNG logs.

**Phase to address:**
**Phase 4 — Agentic Reasoning & Grounding.** Iteration caps, dedup, URL allowlist, budgets all ship with the tool layer — never afterward.

---

### Pitfall 8: Pipeline state-machine stuck mid-state on crash

**What goes wrong:**
`MealLog.processing_status` walks PENDING → DETECTING → SEGMENTING → MATCHING → REVIEWING → COMPLETED. If the worker crashes mid-stage (OOM, OpenRouter 5xx, Mac mini reboots, Docker restarts container), a MealLog sits at SEGMENTING forever. No alert, no recovery. User photographs a meal and never sees a result. Days later, a daily summary references an "incomplete" meal that has no DiaryEntries.

**Why it happens:**
States are persisted but transitions are not transactional with the work, and there's no janitor process to recover orphaned entries.

**How to avoid:**
- **Every status set has a `status_updated_at` timestamp.** Already mostly possible via `updated_at` on FoodItem — add to MealLog too.
- **Janitor cron (APScheduler) every 5 minutes:** for MealLogs in non-terminal status with `status_updated_at` > 10 minutes ago, mark as `processing_status = PENDING` and re-enqueue, OR mark as `FAILED` after 3 retries.
- **Idempotent stage handlers.** Re-running DETECTING on the same image must not create duplicate segments. Use `ON CONFLICT` on segment writes or check existing segments before insert.
- **Add a `FAILED` enum value** to `MealProcessingStatus` (not in schema today — add it). Treat it as terminal but recoverable via manual `/retry` slash command.
- **Health endpoint** that returns count of meals in each non-terminal status — surface as `/health` slash command.

**Warning signs:**
- `SELECT processing_status, COUNT(*) FROM meal_logs GROUP BY 1` shows stuck rows.
- A meal you photographed never produces a Telegram message.
- Daily summary count of "logged meals" mismatches your memory of how many you ate.

**Phase to address:**
**Phase 3 — Pipeline / Identification Loop.** Janitor and FAILED status are part of "pipeline is robust," not v2.

---

### Pitfall 9: APScheduler daily summary silently dies

**What goes wrong:**
The daily summary at 03:00 is the only proactive signal you get that "yesterday is reconciled." If APScheduler:
- Misses execution because the previous run took >24h (it shouldn't, but…) — silently dropped.
- Job persistence wasn't configured → after a Docker restart, the job is gone.
- Was added via a lambda or closure → silent serialization failure, never persists.
- The Mac mini is asleep at 03:00 → cron never fires (Macs sleep aggressively).
- A previous scheduler instance is still holding a job-store lock → no execution.

You don't notice for days, by which point you've forgotten which days are real-but-missing-summaries vs. days you didn't eat.

**Why it happens:**
APScheduler doesn't tell you when jobs silently fail or miss their window. Multi-process job stores are a known footgun. Mac sleep is platform-specific.

**How to avoid:**
- **Prevent Mac mini sleep:** `pmset -a sleep 0 disablesleep 1` (and `caffeinate` as a belt-and-braces inside the container if applicable). Or move to a VM where this isn't a question. **This is the #1 risk for the Mac mini hosting choice.**
- **Run scheduler in the FastAPI process or one dedicated worker — never share the job store across processes.**
- **Use module-level functions, not lambdas/closures, for scheduled jobs.** Verify by listing jobs after registration.
- **Heartbeat job every hour** that writes a row to a `scheduler_heartbeats` table. If the daily summary doesn't fire by 03:05, the next heartbeat sees it missing and sends a Telegram alert.
- **`misfire_grace_time = 3600`** so a slightly-late wakeup still runs the job.
- **`/summary` slash command idempotent and on-demand** — if 03:00 fails, user can still pull yesterday's summary manually.

**Warning signs:**
- You don't get the 03:00 message and only notice the next evening.
- `SELECT max(sent_at) FROM telegram_messages WHERE message_key='DAILY_SUMMARY'` shows yesterday-not-today.
- Heartbeat table has gaps.

**Phase to address:**
**Phase 6 — Telegram Bot & Daily Summary.** Heartbeat + Mac sleep prevention + persistent job store all ship in the same phase.

---

### Pitfall 10: Time zone bugs in `logged_at` — off-by-one daily summaries

**What goes wrong:**
`logged_at` is `Date` (UTC under the hood in Postgres). Daily summary at "03:00 local" needs to roll up "yesterday in local TZ." If you join in UTC, a 23:30 local dinner gets counted into the wrong day. DST transitions silently shift the boundary.

**Why it happens:**
Naïve `date(logged_at) = current_date - 1` runs in server TZ, not user TZ.

**How to avoid:**
- **Store `logged_at` as `TIMESTAMPTZ`** (Postgres preserves the offset).
- **Hard-code one user TZ** (e.g., `Asia/Karachi`) in config. This is a single-user app; don't generalize.
- **All daily/weekly rollups use `(logged_at AT TIME ZONE 'Asia/Karachi')::date`**.
- **Schedule daily summary in local TZ** (APScheduler supports timezone parameter on cron triggers).

**Warning signs:**
- A late-night meal appears in the wrong day's summary.
- Around DST transitions (spring/fall), one day's summary is missing or duplicated.

**Phase to address:**
**Phase 0 — Foundation / DB Schema** (pick TZ-aware types from day one — extremely costly to retrofit).

---

### Pitfall 11: Cold-start noise — empty FoodVisuals routes everything to interview

**What goes wrong:**
On day 1, `food_visuals` is empty. Every segment hits "no match" → LLM stage → almost certainly below confidence → interview. User gets bombarded with interviews for the first 20–30 meals. They get annoyed and abandon the project before the library bootstraps.

**Why it happens:**
The system is designed to learn but has nothing to learn from at the start.

**How to avoid:**
- **Pre-seed the FoodItems table with ~50 common-for-you items** (your typical breakfasts, lunches, snacks). No FoodVisuals yet, but the LLM stage can match against known names and skip parts of the interview.
- **Bootstrap mode: relaxed thresholds for the first N meals.** Auto-accept LLM identification at 0.7 confidence for the first 2 weeks, then ratchet up. Track which auto-accepts were later corrected to drive threshold tuning.
- **Batch onboarding:** an explicit "seed photos" command where you post 10–20 photos of foods you already know the name of; system asks for names once, builds FoodVisuals, ready for daily use.
- **Interview-fatigue throttle:** if >3 interviews are pending, don't open new ones — commit best-effort and let user run `/correct` later.

**Warning signs:**
- First week shows interview-on-every-segment.
- You stop responding to interviews and meals pile up in REVIEWING.

**Phase to address:**
**Phase 7 — Bootstrap & Polish** (the seed-photos flow). But the underlying schema must support pre-creating FoodItems without FoodVisuals — that's Phase 0.

---

### Pitfall 12: Denormalized MealLog totals drift from DiaryEntry sums

**What goes wrong:**
Schema has both `MealLog.total_calories` (denormalized) and `DiaryEntry.calories` (source of truth). Any path that creates/updates/deletes a DiaryEntry but forgets to recompute the MealLog total → totals drift. After a USER_CORRECTED event (delete old DiaryEntry, create new), this is especially easy to miss. Weekly summary shows totals that don't match the sum of meals.

**Why it happens:**
Two sources of truth, manual sync. Classic denormalization tax.

**How to avoid:**
- **v1: don't denormalize.** Compute totals on the fly via SQL aggregate. At this scale (one user, dozens of meals/day), the query is free.
- **If denormalizing later: trigger-based.** Postgres trigger on DiaryEntry insert/update/delete recomputes MealLog totals. No application-level "remember to update both."
- **Reconciliation check** as a weekly cron: assert all MealLog totals match `SUM(diary_entries)` for their meal. Telegram alert on mismatch.

**Warning signs:**
- `/today` and `/week` numbers don't add up.
- Manually corrected meals show wrong totals.

**Phase to address:**
**Phase 0 — Schema decision.** Remove the denormalized columns from MealLog for v1; revisit if/when query perf actually matters.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|---|---|---|---|
| Hardcode `vector(1024)` instead of parameterized dimension | Skips a config knob | Full re-embedding + index rebuild when reality differs | **Never** — make it a config variable from day one |
| Skip USER_CORRECTED → FoodVisual invalidation | One less code path | Library poisoning compounds; trust collapses | **Never** — these must ship together |
| Trust LLM-emitted confidence as-is, no calibration | No measurement infra needed | Threshold is meaningless; can't tell when models drift | Only if you log raw confidence + outcome for later calibration |
| Continuous portion multiplier (0.5–2.0 free-form) | Looks precise | Confidently wrong by ~30%; user trust collapses | **Never in v1** — use buckets |
| Denormalize MealLog totals | One JOIN saved on daily summary | Drift bugs after every USER_CORRECTED | Acceptable only after a Postgres trigger maintains it |
| One MealProcessingStatus enum without FAILED state | Smaller enum | Stuck rows accumulate, no clean recovery path | **Never** — add FAILED from day one |
| Skip janitor cron for stuck meals | One less moving part | Silent meal loss; user notices days later | Acceptable for the first week of local dev only |
| Webhook for Telegram on Mac mini behind home internet | Lower latency | Needs static IP / tunnel / cert; flaky | Acceptable; **long-polling is the safer default** for home hosting |
| MarkdownV2 for Telegram messages | Rich formatting | One unescaped `.` in a food name crashes the send | Switch to HTML parse mode; only escape `<`, `>`, `&` |
| Run Firecrawl from Mac mini without resource caps | Easy setup | Headless Chromium eats 1–4 GB RAM, kills other services | Set Docker memory limits + `--ipc=host` + `--disable-dev-shm-usage` |
| Share APScheduler job store across multiple processes | Convenience | Duplicate execution OR silent drops | **Never** — one scheduler process, period |
| Single shared OpenRouter API key, no per-stage budget | Simplest config | Cost runaway from a tool-loop bug | Acceptable in dev; per-stage logging mandatory for v1 |

---

## Integration Gotchas

Common mistakes when connecting to external services.

| Integration | Common Mistake | Correct Approach |
|---|---|---|
| OpenRouter via OpenAI SDK | Assuming `model="google/gemini-3-flash-preview"` is one model with one behavior | Pin provider with `provider.order` and `allow_fallbacks=false`; verify capabilities at startup |
| OpenRouter structured outputs | Combining `response_format=json_schema` with tools in one call | Split: tool-using call → structuring call. Verify per-model. |
| Gemini Embedding 2 | Assuming 1024 dims and skipping normalization | Use 3072/1536/768 (MRL tiers); manually L2-normalize when truncated |
| pgvector cosine | Confusing distance (`<=>`) with similarity | `similarity = 1 - distance`; calibrate threshold on YOUR data, never trust generic 0.85 |
| pgvector IVFFlat | Creating index on empty table, never rebuilding | Use **HNSW** instead — it builds incrementally, works on empty/growing tables |
| SearXNG | Self-host on a hyperscaler IP; expect Google to return results forever | Either host on Mac mini (residential IP — best) or expect periodic blocks; rotate engine list, retry with fallbacks |
| Firecrawl OSS | Assume 1:1 feature parity with cloud | Fire-engine anti-bot, proxy rotation, dashboard are cloud-only; expect failures on bot-protected sites; do not rely on Firecrawl for restaurant sites with Cloudflare |
| Firecrawl + Mac mini | No resource caps; Chromium OOMs | Docker memory limit, `--ipc=host`, `--disable-dev-shm-usage`; constrain concurrency to 1 |
| python-telegram-bot | Webhook setup behind home NAT without tunnel | Use long-polling (`run_polling`) for Mac mini hosting; no public ingress needed |
| python-telegram-bot ConversationHandler | Conversations dropped on restart | `persistent=True` + named `ConversationHandler` + `PicklePersistence` |
| Telegram MarkdownV2 | Sending user-derived strings without escaping | Use **HTML parse mode** (`<b>`, `<i>`, `<code>`); only escape `<`, `>`, `&` |
| Telegram media | Posting JPEG with EXIF rotation; bot strips orientation | Re-encode to upright before sending; otherwise reasoning model sees a sideways image |
| iOS Shortcut → endpoint | Shortcut posts then loses the response | Endpoint must return 200 within ~5s; do heavy work async; ack immediately |
| APScheduler | Lambda/closure jobs with persistent job store | Module-level functions only; verify serialization at startup |
| pgvector + Docker volume | Forgetting to persist the volume | Lose all FoodVisuals on container recreate; named volume mandatory |

---

## Performance Traps

Patterns that work at small scale but fail as usage grows. Note: this is a one-user app, so scale thresholds are modest — but FoodVisuals grows monotonically forever.

| Trap | Symptoms | Prevention | When It Breaks |
|---|---|---|---|
| IVFFlat index on a growing FoodVisuals table | Recall degrades as data shifts; periodic rebuilds needed | Use **HNSW** — incremental, no rebuild needed | After ~6 months of daily logging |
| No vector index at all (brute force) | Queries are fast at first, slow imperceptibly | Add HNSW index from day one even on small data | Around 5–10k FoodVisuals (~6–12 months) |
| Embedding every segment synchronously inside the request | Endpoint times out on slow LLM API | Async pipeline (already a Key Decision); endpoint just enqueues | Immediately under any LLM latency spike |
| Loading whole MealLog history into memory for `/week` | Memory creep, slow command | Aggregate in SQL with GROUP BY on `logged_at::date AT TIME ZONE` | After a few months of data |
| Firecrawl with no concurrency cap | Chromium spawns multiple instances; Mac mini OOM | Max 1 concurrent fetch; queue the rest | Within the first concurrent burst |
| No image storage rotation | `image_url` storage grows forever | Auto-delete original images after N days; keep crops if needed | After 6–12 months |
| Per-meal OpenRouter spend uncapped | Sudden bill spikes when a tool loop runs wild | Per-call wall-clock + token budget; alert at 2x normal spend | First day a model decides to loop |
| Logging full LLM prompts/responses to DB | Table bloat, slow scans | Log to file, summarize to DB | After a few weeks |
| Re-running vector search against the entire FoodVisuals on every segment | Fine at 1k, slow at 100k | HNSW index handles this — but make sure ORDER BY uses the index | After 50k visuals |

---

## Security Mistakes

Single-user personal tool, so security surface is narrower than a multi-tenant SaaS. Still:

| Mistake | Risk | Prevention |
|---|---|---|
| Shared-secret header check that's `==` not constant-time | Timing attack to leak the secret | `hmac.compare_digest` |
| Secret in URL query param (iOS Shortcut convenience) | Logged in nginx access logs, browser history | Send via header; nginx log_format excludes the header |
| Telegram chat_id check by string compare with user input | Spoofable updates from other chats | Verify chat_id against pinned config value; reject anything else with no response (don't echo "unauthorized" — silent drop) |
| Telegram bot token in image URL signed by it | Token leakage via image link sharing | Don't proxy through Telegram bot URL; store original elsewhere |
| OpenRouter API key in `docker-compose.yml` checked into git | Public exposure | `.env` file, `.gitignore`, never committed; use Docker secrets when migrating to VM |
| SearXNG admin interface exposed | Public abuse of your search instance | Bind to `127.0.0.1` or Docker internal network; never publish port |
| Firecrawl SSRF — model fetches `http://192.168.x.x/admin` | Internal network exposed via tool | Firecrawl URL allowlist; block RFC1918, localhost, link-local |
| Image upload with no MIME/size check | Disk fill, malformed image crashes pipeline | Validate content type, max size (e.g., 10 MB), strip metadata |
| Postgres exposed on host network | Easy db dump from outside | Postgres on Docker internal network only; no published port |
| iOS Shortcut runs over HTTP not HTTPS | Secret transmitted plaintext on coffee-shop wifi | Caddy/Traefik in front with Let's Encrypt; reject HTTP |

---

## UX Pitfalls

Single user, but UX still matters — and "the user" is you, so abandonment risk is real.

| Pitfall | User Impact | Better Approach |
|---|---|---|
| Interview-on-every-meal in week 1 | Annoyance, abandonment | Bootstrap mode + seed photos (Pitfall 11) |
| Asking the same question across two interviews instead of stitching | "Why is the bot asking again?" | One InterviewSession per MealLog (not per segment if multiple segments share a question) |
| Bot pings during work meetings | Notification fatigue | Quiet-hours config (no per-meal push 9–17); daily summary instead during quiet hours |
| Daily summary at 03:00 wakes you with notification | Sleep disrupted | Schedule send at 03:00 but with `disable_notification=true` |
| User correction (`/correct`) requires remembering exact wording | Friction | Inline keyboard with last 5 meals as buttons → tap to correct |
| Showing a 4-decimal confidence number | Looks robotic, hides uncertainty | "Pretty sure" / "Not sure — confirm?" / "Need help with this" |
| Long LLM reasoning dumped into Telegram | Wall of text, noise | Surface only the conclusion; reasoning available via `/why` |
| "Best-effort committed, is_verified=false" silently | User doesn't realize numbers are guesses | Suffix `*` and explain once in the message; periodic `/unverified` digest |
| No way to delete a wrong meal | Lingering bad data | `/delete` slash command tied to last meal |
| iOS Shortcut posts but no Telegram message ever comes | User assumes it worked, days later finds gaps | Endpoint ack via Telegram immediately on receipt: "Received your meal photo, processing…" |

---

## "Looks Done But Isn't" Checklist

- [ ] **Embedding pipeline:** verified output dimension matches schema; verified L2 normalization; verified self-similarity ≈1.0; verified cross-modal alignment isn't degenerate.
- [ ] **Vector search:** index actually used (`EXPLAIN ANALYZE` shows the HNSW scan, not seq scan); threshold calibrated on real data, not generic 0.85.
- [ ] **USER_CORRECTED:** corrected MealSegment AND deletes/invalidates the FoodVisual it originally produced; verify with a manual test.
- [ ] **Janitor:** stuck-status recovery cron is actually running (heartbeat row appears every 5 min); test by killing worker mid-segment.
- [ ] **Daily summary:** fires at 03:00 local in the actual TZ; survives a Docker restart; heartbeat alert fires if it doesn't.
- [ ] **Mac mini sleep:** confirmed `pmset` blocks sleep; reboot test confirms scheduler resumes.
- [ ] **Telegram parsing:** food names containing `.`, `_`, `*`, `(`, `)` don't crash the send (HTML mode preferred).
- [ ] **Telegram persistence:** ConversationHandler resumes after Docker restart; user mid-interview doesn't lose state.
- [ ] **OpenRouter:** startup capability smoke tests pass (vision + tool calling + structured output verified per stage).
- [ ] **Tool budget caps:** verified by deliberately triggering a search-loop scenario; pipeline exits cleanly after N iterations.
- [ ] **Firecrawl URL allowlist:** model can't fetch a fabricated URL; only URLs from prior SearXNG results in this session.
- [ ] **Time zone:** dinner logged at 23:30 local on day N appears in day N's `/today` and day N's daily summary, NOT day N+1.
- [ ] **Idempotency:** re-running the pipeline on the same MealLog doesn't duplicate segments or DiaryEntries.
- [ ] **Image rotation:** iPhone photos with EXIF orientation render upright to the vision model.
- [ ] **Cost telemetry:** per-meal token + dollar cost logged; spike detection alert configured.
- [ ] **Endpoint ack:** iOS Shortcut receives `200 OK` within 5 seconds even if pipeline takes minutes.

---

## Recovery Strategies

When pitfalls occur despite prevention.

| Pitfall | Recovery Cost | Recovery Steps |
|---|---|---|
| Embedding dimension wrong | MEDIUM | Drop FoodVisuals index, `ALTER COLUMN` dimension, re-embed all from stored crops (if you kept them) or accept library reset |
| FoodVisuals poisoned by bad confirmations | MEDIUM-HIGH | Bulk-delete visuals with `confirmation_source = SIMILARITY_AUTO`; require interview to re-seed; tighten threshold |
| Confidence threshold miscalibrated | LOW | Adjust config value; no data migration; new threshold takes effect on next meal |
| Stuck pipeline rows | LOW | Janitor handles automatically; manual `/retry <meal_id>` as fallback |
| MealLog totals drift from DiaryEntries | LOW | Run reconciliation: `UPDATE meal_logs SET total_* = (SELECT SUM ...)` |
| Daily summary missed | LOW | `/summary 2026-05-23` on-demand regenerates any past day |
| Wrong food identified, USER_CORRECTED missed | LOW per-meal; HIGH if compounded | Per-meal: `/correct`. If many: bulk audit script that joins MealSegments to DiaryEntries for review |
| OpenRouter cost spike | LOW | Budget cap should have prevented it; if not, kill switch (disable LLM stages, queue meals as PENDING) until rate limit added |
| SearXNG blocked by Google | MEDIUM | Switch enabled engines (Bing, DuckDuckGo, Brave); reduce per-meal search count |
| Firecrawl can't reach a site (Cloudflare) | LOW | Mark `is_verified=false`, defer to interview; consider manual override |
| Telegram MarkdownV2 crash | LOW | Switch to HTML mode globally |
| Mac mini went to sleep, missed meals | LOW (data not lost — iOS Shortcut retries fail, photo still in camera roll) | Fix sleep settings; manually re-post recent meals via Shortcut |

---

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls. (Phase numbering is suggested; orchestrator may resequence.)

| Pitfall | Prevention Phase | Verification |
|---|---|---|
| 1. Embedding dim mismatch | **Phase 1 — Embedding & Vector Slice** (must be standalone) | Calibration script outputs: dim=N, ‖v‖=1.0, cross-modal sanity passes |
| 2. FoodVisuals poisoning | **Phase 3 — Pipeline / Identification Loop** | USER_CORRECTED test: confirm, then correct, verify FoodVisual is invalidated |
| 3. Confidence miscalibration | **Phase 3** (multi-signal gate) + **Phase 5 — Calibration** (empirical tuning) | Reliability diagram on 50+ meals shows stated≈actual within ±10% |
| 4. Portion estimation error | **Phase 3** (use buckets) + **Phase 5** (measure error) | Bucket assignment matches manual weighing on a sample of 10 meals within ±50% |
| 5. OpenRouter feature gaps | **Phase 0 — Foundation / LLM Gateway** | Startup capability smoke test passes for every pinned model |
| 6. Bounding box hallucinations | **Phase 2 — Vision Slice** | Bad-segmentation test: corrupt prompt, verify validator rejects and re-prompts |
| 7. Agentic tool loops | **Phase 4 — Agentic Reasoning & Grounding** | Synthetic test: ambiguous query that would loop, verify cap fires |
| 8. Pipeline state stuck | **Phase 3** | Kill worker mid-stage; janitor recovers within 10 minutes |
| 9. APScheduler dies silently | **Phase 6 — Telegram Bot & Daily Summary** | Heartbeat row appears hourly; deliberately skip a day, verify alert fires |
| 10. Time zone bugs | **Phase 0 — Foundation / DB Schema** | Test: insert dinner at 23:30 local, verify it's in today's `/today` |
| 11. Cold-start interview fatigue | **Phase 7 — Bootstrap & Polish** | After seed photos, 80%+ of next meals auto-resolve without interview |
| 12. Denormalized totals drift | **Phase 0 — Schema** (remove the columns) | `SELECT … WHERE MealLog.total_calories != SUM(diary)` returns 0 rows |
| 13. SearXNG blocking (Mac mini residential IP helps) | **Phase 4** | After 100 queries, success rate >80% |
| 14. Firecrawl resource consumption | **Phase 4** | Mem cap holds under stress test of 5 sequential fetches |
| 15. Telegram MarkdownV2 crashes | **Phase 6** | Send food names containing every special char; nothing 400s |
| 16. iOS Shortcut endpoint hangs | **Phase 0 — Foundation / Endpoint** | Endpoint returns 200 in <5s under 30s LLM stage |
| 17. Solo-dev over-engineering | **All phases — explicit DONE line per phase** | Phase exits even if "could be better"; ratchet quality via Phase 5, not by extending earlier phases |

---

## Highest-Risk Items (Priority Order)

Highlighting the items most likely to silently sink the project:

1. **Embedding dim/normalization (Pitfall 1)** — false foundation; everything downstream is meaningless if wrong.
2. **FoodVisuals self-poisoning (Pitfall 2)** — the core self-improvement loop is also the core failure loop.
3. **Confidence miscalibration (Pitfall 3)** — the single gate that everything routes through is fundamentally unreliable; defenses must be designed in.
4. **Portion estimation overconfidence (Pitfall 4)** — invisibly wrong numbers destroy trust in the whole product.
5. **OpenRouter feature gaps (Pitfall 5)** — drop-in compatibility is a marketing claim, not an engineering reality.
6. **Bounding box hallucinations on composite plates (Pitfall 6)** — silent double-counting is unrecoverable without manual audit.

---

## Sources

**Vision LLM grounding & food:**
- [Building a tool showing how Gemini Pro can return bounding boxes for objects in images — Simon Willison](https://simonw.substack.com/p/building-a-tool-showing-how-gemini)
- [Agentic Vision Gemini 3 Flash: Code Execution Solves Visual Hallucination — StartupHub](https://www.startuphub.ai/ai-news/ai-research/2026/agentic-vision-gemini-3-flash-code-execution-solves-visual-hallucination)
- [Evaluating Gemini LLM in Food Image-Based Recipe and Nutrition Description (arXiv 2511.08215)](https://arxiv.org/pdf/2511.08215)
- [GroundSight: Augmenting Vision-Language Models with Grounding Information (arXiv 2509.25669)](https://arxiv.org/pdf/2509.25669)
- [A comparative study of vision–language models for food ingredient recognition (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC13092701/)
- [Food Image Segmentation with LLM-Derived Ingredient Labels — Springer](https://link.springer.com/chapter/10.1007/978-981-95-6950-2_30)

**Portion estimation:**
- [Automated Food Weight and Content Estimation Using Computer Vision (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11644939/)
- [Size Matters: Reconstructing Real-Scale 3D Models for Food Portion Estimation (arXiv 2601.20051)](https://arxiv.org/pdf/2601.20051)
- [Food Portion Estimation: From Pixels to Calories (arXiv 2602.05078)](https://arxiv.org/html/2602.05078v1)
- [The Evidence Base for AI Nutrition Accuracy — Nutrient Metrics](https://www.nutrientmetrics.com/en/guides/peer-reviewed-ai-nutrition-accuracy-literature-review)

**Embeddings & vector retrieval:**
- [Gemini Embedding 2 — Google Blog](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-embedding-2/)
- [Building with Gemini Embedding 2: Agentic multimodal RAG — Google Developers](https://developers.googleblog.com/building-with-gemini-embedding-2/)
- [Gemini Embedding 2: Variants, Dimensions, and Use Cases — MindStudio](https://www.mindstudio.ai/blog/what-is-gemini-embedding-2)
- [IVFFlat vs HNSW in pgvector — DEV.to](https://dev.to/philip_mcclarence_2ef9475/ivfflat-vs-hnsw-in-pgvector-which-index-should-you-use-305p)
- [Vector Indexes in Postgres using pgvector: IVFFlat vs HNSW — Tembo](https://legacy.tembo.io/blog/vector-indexes-in-pgvector/)
- [pgvector cosine similarity threshold guide — Sarah Glasmacher](https://www.sarahglasmacher.com/how-to-use-cosine-similarity-in-pgvector/)
- [Calibrated Similarity for Reliable Geometric Analysis of Embedding Spaces (arXiv 2601.16907)](https://arxiv.org/pdf/2601.16907)

**LLM confidence calibration:**
- [The Illusion of Confidence: Why Asking Your LLM "Are You Sure?" Is a Terrible Idea — Medium](https://medium.com/data-science-collective/the-illusion-of-confidence-why-asking-your-llm-are-you-sure-is-a-terrible-idea-84eb5859fc26)
- [Can LLMs Express Their Uncertainty? (arXiv 2306.13063)](https://arxiv.org/pdf/2306.13063)
- [Fact-Level Confidence Calibration and Self-Correction (arXiv 2411.13343)](https://arxiv.org/pdf/2411.13343)
- [Calibrating Verbalized Confidence with Self-Generated Distractors (arXiv 2509.25532)](https://arxiv.org/pdf/2509.25532)

**Agentic tool use / loops:**
- [Agentic Resource Exhaustion: The "Infinite Loop" Attack — Medium](https://medium.com/@instatunnel/agentic-resource-exhaustion-the-infinite-loop-attack-of-the-ai-era-76a3f58c62e3)
- [Stop the Loop! Prevent Infinite Conversations in AI Agents — DEV.to](https://dev.to/alessandro_pignati/stop-the-loop-how-to-prevent-infinite-conversations-in-your-ai-agents-ekj)
- [Beyond Max Tokens: Stealthy Resource Amplification via Tool Calling Chains (arXiv 2601.10955)](https://arxiv.org/pdf/2601.10955)

**RAG poisoning / vector contamination:**
- [The Embedded Threat: Poisoning RAG Pipelines via Vector Embeddings — Prompt Security](https://prompt.security/blog/the-embedded-threat-in-your-llm-poisoning-rag-pipelines-via-vector-embeddings)
- [RAGPoison: Persistent Prompt Injection via Poisoned Vector Databases — Snyk Labs](https://labs.snyk.io/resources/ragpoison-prompt-injection/)
- [What is RAG poisoning? Complete Guide — DevSecOps Now](https://www.devsecopsnow.com/rag-poisoning/)

**OpenRouter:**
- [Structured Outputs — OpenRouter Docs](https://openrouter.ai/docs/guides/features/structured-outputs)
- [OpenAI SDK Integration — OpenRouter Docs](https://openrouter.ai/docs/guides/community/openai-sdk)
- [Provider Routing — OpenRouter Docs](https://openrouter.ai/docs/guides/routing/provider-selection)
- [OpenRouter Routing: Fallbacks, Provider Reliability — DataStudios](https://www.datastudios.org/post/openrouter-routing-fallbacks-provider-reliability-and-model-selection-logic-across-multi-provider)
- [Tool Call doesn't work with Structured Outputs — openai-agents-python #1778](https://github.com/openai/openai-agents-python/issues/1778)

**SearXNG / Firecrawl self-hosted:**
- [Google is actively blocking SearXNG instances — searxng #2515](https://github.com/searxng/searxng/issues/2515)
- [SearXNG on a VPS: how to avoid getting rate-limited — ServerSpan](https://www.serverspan.com/en/blog/searxng-on-a-vps-how-to-run-private-search-without-getting-rate-limited-into-uselessness)
- [Firecrawl Self-Host — GitHub](https://github.com/firecrawl/firecrawl/blob/main/SELF_HOST.md)
- [Firecrawl pros and cons — Filip Konecny](https://filipkonecny.com/2026/03/29/firecrawl-pros-and-cons/)
- [Firecrawl Review and Alternatives — Thunderbit](https://thunderbit.com/blog/firecrawl-review-and-alternatives)
- [Playwright and Chromium in Docker Production — Thomas Bourimech](https://thomasbourimech.com/blog/en/playwright-chromium-docker-production/)
- [Playwright Docker docs](https://playwright.dev/docs/docker)

**Telegram bot:**
- [Telegram MarkdownV2 Special Characters — Complete Escape Guide](https://botnamefinder.com/blog/telegram-markdownv2-escape-characters)
- [Escaping markdown bug — python-telegram-bot #2371](https://github.com/python-telegram-bot/python-telegram-bot/issues/2371)
- [Making your bot persistent — python-telegram-bot wiki](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Making-your-bot-persistent)
- [Polling vs Webhook in Telegram Bots — Hostman](https://hostman.com/tutorials/difference-between-polling-and-webhook-in-telegram-bots/)

**APScheduler:**
- [APScheduler FAQ](https://apscheduler.readthedocs.io/en/3.x/faq.html)
- [Missed jobs although misfire_grace_time is set — apscheduler #146](https://github.com/agronholm/apscheduler/issues/146)
- [APScheduler jobs not executed as scheduled — apscheduler #481](https://github.com/agronholm/apscheduler/issues/481)
- [Python APScheduler Monitoring — CronRadar](https://cronradar.com/blog/python-scheduler-monitoring)

**Solo-dev / MVP discipline:**
- [Stop overengineering your SaaS MVP — DEV.to](https://dev.to/muhammadtanveerabbas/stop-overengineering-your-saas-mvp-heres-what-actually-ships-2g9e)
- [The "One More Feature" Trap — DEV.to](https://dev.to/godnick/the-one-more-feature-trap-why-i-ship-ugly-mvps-as-a-solo-dev-21c4)

---
*Pitfalls research for: photo-meal-tracking AI pipeline (vision LLM + RAG + agentic tools + Telegram bot, self-hosted on Mac mini)*
*Researched: 2026-05-24*
