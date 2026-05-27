# Phase 2: Vision Slice - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-27
**Phase:** 2-Vision Slice
**Areas discussed:** Item granularity, Telegram result shape, Borderline food policy, Bad-box recovery

---

## Item granularity

| Option | Description | Selected |
|--------|-------------|----------|
| Main items + obvious sides only | Count major foods and substantial sides, ignore tiny extras | |
| Everything edible visible | Detect every visible edible thing separately | |
| Main plated components only | Strictest grouping, only dominant plated components | |
| Other | Group by self-defined food regions rather than individual pieces | ✓ |

**User's choice:** Group by food type and clear visual separation, not by counting each piece.
**Notes:** User referenced `sample_images/IMG_4583.HEIC` and clarified expected grouping: stacked breads as one food, curry/chicken as one dish, and sauteed vegetables as one side. Same food in separate places should remain separate segments that may later cluster together. Mixed dishes should use dish-level labels; simple isolated foods can use ingredient-level labels. Tiny garnish or minor sauces should usually be ignored.

---

## Telegram result shape

| Option | Description | Selected |
|--------|-------------|----------|
| One plain sentence | Simple sentence listing what the system sees | ✓ |
| Short list | Multi-line numbered list of items | |
| List + grouping hints | Mention segment/group counts in the output | |
| Other | Freeform message style | |

**User's choice:** One plain sentence.
**Notes:** Non-food photos should send nothing at all. If labels are weak, uncertainty should appear inline on those items only. Duplicate same-food segments should collapse into one final label in the sentence. During this discussion the user also clarified that human-readable label assignment is a separate call from segmentation.

---

## Borderline food policy

| Option | Description | Selected |
|--------|-------------|----------|
| Bias toward processing | Continue when image might be food | |
| Bias toward skipping | Only continue when food is clear | ✓ |
| Two-tier | Skip only clear non-food, continue uncertain cases | |
| Other | Freeform rule | |

**User's choice:** Bias toward skipping.
**Notes:** Clutter around the meal is fine if the meal is clearly present anywhere in the frame. High-confidence non-food results should stop silently with no Telegram output. If detect passes but segment yields nothing usable, retry once using a better model; user explicitly named `google/gemini-3.5-flash` for that stronger retry path.

---

## Bad-box recovery

| Option | Description | Selected |
|--------|-------------|----------|
| One retry with better model, then stop | Single escalated repair attempt | ✓ |
| Two retries max | More resilience, more latency/cost | |
| Retry until one usable result | Highest recovery, unbounded loop risk | |
| Other | Freeform retry rule | |

**User's choice:** One retry with a stronger model, then stop.
**Notes:** If a response contains some valid and some invalid boxes, reject the entire segmentation response and rerun it rather than keeping a partial set; user explicitly said token usage is negligible here. If the stronger retry still fails, send a soft failure message. The retry should be an explicit escalation to a stronger segmentation setup/model, not just a stricter prompt.

---

## the agent's Discretion

None.

## Deferred Ideas

None.
