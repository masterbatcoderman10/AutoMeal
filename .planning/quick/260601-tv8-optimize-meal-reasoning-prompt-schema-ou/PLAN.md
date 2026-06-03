---
status: completed
quick_id: 260601-tv8
slug: optimize-meal-reasoning-prompt-schema-ou
started: 2026-06-01T17:30:17Z
---

# Optimize Meal Reasoning Prompt Schema Output

## Goal

Reduce meal reasoning token use and remove legacy root compatibility surfaces.

## Tasks

1. Remove root-level `top_3` and root-level `clarification_schema` from reasoning schema, normalized output, gate output, and persisted result return payloads.
2. Remove deprecated per-group `clarification` alias from prompted schema/output.
3. Replace verbose reasoning prompt with compact high-signal policy.
4. Force clear no-vector/visual-only foods through `AFFIRMATION_REQUIRED`, not `AUTO_CONFIRM`.
5. Update tests for lean contract and deploy against reset blank UAT DB.
