# Phase 3: Embed & Match - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-27
**Phase:** 3-Embed & Match
**Areas discussed:** Seed Contract, No-Match Behavior, Portion Default, Nutrition Push Shape, FoodVisual Write-Back

---

## Seed Contract

| Option | Description | Selected |
|--------|-------------|----------|
| Fixture script | Repeatable helper seeds known `FoodItem`/`FoodVisual` rows from local crop images. | |
| Manual SQL | Exact row control, but UAT can drift. | |
| Test-only seed | Keep seeding inside tests only; live UAT uses manual setup. | |
| Existing sample images | Use `sample_images/*.HEIC` as seed material; production library may start empty. | yes |

**User's choice:** Existing sample images can serve as seeds after segmentation.
**Notes:** User questioned why seeds are needed at all. We clarified empty `FoodVisuals` is valid runtime state, but seeded visuals are needed to prove the match -> diary -> nutrition path in Phase 3.

| Option | Description | Selected |
|--------|-------------|----------|
| Small labeled manifest | Map crops/segments to nutrition fields. | |
| DB/manual after segmentation | Inspect created segments and fill rows by hand. | |
| Hardcoded demo seeds | Use 1-2 sample-image crops and fixed known nutrition for smoke only. | yes |

**User's choice:** Hardcoded demo seeds.
**Notes:** Demo seeds are UAT scaffolding only.

| Option | Description | Selected |
|--------|-------------|----------|
| Exact sample re-photo | Reuse same sample/crop to prove plumbing. | |
| Different photo of same food | Better real similarity proof if images cooperate. | |
| Both | Self-similarity first, same-food different-photo when possible. | yes |

**User's choice:** Both.
**Notes:** UAT should avoid depending solely on exact duplicate matching.

| Option | Description | Selected |
|--------|-------------|----------|
| Script under `scripts/` | Operator can run before UAT. | agent |
| Test fixture only | Tests seed DB internally. | |
| One-time app command | More structure than needed now. | |

**User's choice:** Agent discretion.
**Notes:** Suggested default: `scripts/seed_demo_foods.py`, with reusable test helper if useful.

---

## No-Match Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Soft complete, no diary | Terminal for now, no stuck rows. | |
| Mark `FAILED` | Simple, but looks like system error. | |
| Keep pending for Phase 4 | Leave unresolved for future reasoning/interview. | yes |

**User's choice:** Some kind of pending state.
**Notes:** Current enum has `REASONING`, so no new enum is needed.

| Option | Description | Selected |
|--------|-------------|----------|
| Use `REASONING` as deferred state | Accurate pipeline handoff to Phase 4. | yes |
| Use `COMPLETED` plus no diary | Terminal for now. | |
| Add `NEEDS_REVIEW` enum | Clean semantics, but extra schema ripple. | |

**User's choice:** Use `REASONING`.
**Notes:** No/low similarity match moves the meal to the next real pipeline stage.

| Option | Description | Selected |
|--------|-------------|----------|
| Expected branch | Tests cover no-match -> `REASONING`; not a failure. | yes |
| Warning branch | Allowed live, but main UAT must use seeded match. | |
| Minimal only | Do not crash; no explicit test beyond happy path. | |

**User's choice:** Expected branch.
**Notes:** Seeded happy path still required for Phase 3 success.

| Option | Description | Selected |
|--------|-------------|----------|
| Notify once | Transparent note that the system does not know the food yet. | yes |
| Silent | Avoids exposing phase status. | |
| Generic processing note | "Still learning this meal." | |

**User's choice:** Notify once.
**Notes:** Message may mention future interview/reasoning in plain terms.

| Option | Description | Selected |
|--------|-------------|----------|
| Per-segment embedding | Each crop/constituent gets its own embedding. | yes |
| Whole-meal embedding | Embed entire image for matching. | |

**User's choice:** Per-segment embedding.
**Notes:** User explicitly corrected that the whole meal must not be embedded for match logic.

| Option | Description | Selected |
|--------|-------------|----------|
| Partial diary + `REASONING` | Write entries for matched segments, leave unresolved for later. | |
| Hold all diary until all segments resolved | Avoid partial diary data while unresolved segments remain. | yes |
| Complete matched only | Ignore unmatched segments. | |

**User's choice:** Hold all diary until all segments resolve.
**Notes:** If any segment is unresolved, no `DiaryEntry` rows are created for the meal yet.

---

## Portion Default

| Option | Description | Selected |
|--------|-------------|----------|
| Always `STANDARD` | Simplest; later interview/corrections handle nuance. | yes |
| Seeded default | More realistic, more seed metadata. | |
| Infer from crop size | Unreliable and out of scope. | |

**User's choice:** Always `STANDARD`.
**Notes:** Applies to every Phase 3 similarity-created `DiaryEntry`.

| Option | Description | Selected |
|--------|-------------|----------|
| Mention softly | "standard portion assumed." | |
| Hide it | Keep output clean. | yes |
| Show verification field only | Show `portion: standard`, no caveat. | |

**User's choice:** Hide it.
**Notes:** No default/assumed portion caveat in Telegram output.

| Option | Description | Selected |
|--------|-------------|----------|
| Use `FoodItem` macros as standard portion | Stored nutrition is used directly. | yes |
| Scale from `serving_size_g` | Needs quantity estimate. | |
| Seed-only convention | Demo seeds decide; production unspecified. | |

**User's choice:** Use `FoodItem` macros as standard portion.
**Notes:** Phase 3 does not scale nutrition values.

---

## Nutrition Push Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Known fields only | Show fields present on matched `FoodItem`; omit missing. | yes |
| Require complete seed nutrition | Seeded foods must have kcal/protein/carbs/fat. | |
| Name-only for Phase 3 | No nutrition numbers yet. | |

**User's choice:** Known fields only.
**Notes:** User noted nutrition info is not fully decided yet. Phase 3 should prove flow without locking full nutrition policy.

| Option | Description | Selected |
|--------|-------------|----------|
| Method + verified flag | Useful dev/UAT audit trail. | yes |
| Method only | Show matched by similarity. | |
| No audit fields | Clean user-facing result only. | |

**User's choice:** Initially chose no audit fields, then changed to method + verified flag for development-phase UAT clarity.
**Notes:** Later UX can hide these fields if noisy.

| Option | Description | Selected |
|--------|-------------|----------|
| Inline compact | `rice: 210 kcal, 4g protein`. | |
| Two-line per item | More readable but verbose. | yes |
| Calories-first only | Macros remain DB-only for now. | |

**User's choice:** Two-line per item.
**Notes:** Show known fields only.

| Option | Description | Selected |
|--------|-------------|----------|
| Total known fields | Sum known calories/macros; omit unavailable totals. | yes |
| No total yet | Item lines only. | |
| Calories total only | Sum kcal if all matched items have calories. | |

**User's choice:** Total known fields.
**Notes:** Totals are partial by field availability.

---

## FoodVisual Write-Back

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, append every auto-match | Proves self-improving loop now. | yes |
| Only append seeded/UAT matches | Safer, but not real learning loop. | |
| Wait until Phase 4 confirmations | Avoids reinforcement risk, weakens Phase 3 goal. | |

**User's choice:** Yes, append every auto-match.
**Notes:** Applies when the full meal resolves.

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, multiple rows | Grows view-angle vocabulary. | yes |
| Deduplicate exact image hash | Prevents duplicate storage but needs more tracking. | |
| One visual per food item | Simpler, but not self-improving. | |

**User's choice:** Multiple rows.
**Notes:** No dedupe for Phase 3.

| Option | Description | Selected |
|--------|-------------|----------|
| No, wait for full meal resolution | Consistent with holding all diary. | yes |
| Yes, write matched visuals | Learning happens even if meal incomplete. | |
| Only in UAT | Extra branching. | |

**User's choice:** Wait for full meal resolution.
**Notes:** If any segment is unmatched and meal moves to `REASONING`, matched segments do not append visuals yet.

| Option | Description | Selected |
|--------|-------------|----------|
| Same transaction as `DiaryEntry` creation | Entries, visuals, and completion land atomically. | yes |
| After Telegram succeeds | Couples DB correctness to chat delivery. | |
| Background after completion | More moving parts. | |

**User's choice:** Same transaction as `DiaryEntry` creation.
**Notes:** Telegram success should not gate DB commit.

---

## Agent Discretion

- Exact seed helper shape and file location; likely `scripts/seed_demo_foods.py`.
- Exact internal module placement for embedding/matching, while preserving the existing status-driven worker pattern.

## Deferred Ideas

None.
