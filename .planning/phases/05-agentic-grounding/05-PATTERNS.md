# Phase 5: Agentic Grounding - Pattern Map

**Mapped:** 2026-06-04
**Files analyzed:** 16
**Analogs found:** 14 / 16

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `app/services/llm_client.py` | service | request-response | `app/services/llm_client.py` | exact |
| `app/config.py` | config | request-response | `app/config.py` | exact |
| `app/services/reasoning_schema.py` | utility/model | transform | `app/services/reasoning_schema.py` | exact |
| `app/services/reasoning_service.py` | service | request-response / event-driven | `app/services/reasoning_service.py` | exact |
| `app/services/interview_service.py` | service | request-response / state-transition orchestration | `app/services/interview_service.py` | exact |
| `app/services/matching_service.py` | service | request-response + persistence | `app/services/matching_service.py` | exact |
| `app/services/meal_resolution_service.py` | service | transform + persistence | `app/services/meal_resolution_service.py` | exact |
| `app/services/grounding_stub.py` | utility/migration seam | request-response | `app/services/grounding_stub.py` | exact |
| `app/services/tracing_service.py` | utility | request-response / audit stream | `app/services/tracing_service.py` | exact |
| `bot/polling.py` | worker/orchestrator | event-driven background task | `bot/polling.py` | exact (to be retired/rewired) |
| `bot/handlers.py` | component/adapter | request-response | `bot/handlers.py` | exact (grounding branch cleanup) |
| `tests/test_interview_flow.py` | test | request-response/state transitions | `tests/test_interview_flow.py` | exact |
| `tests/test_match_flow.py` | test | request-response + persistence assertions | `tests/test_match_flow.py` | exact |
| `tests/test_bot_contract.py` | test | event-driven worker contract | `tests/test_bot_contract.py` | exact |
| `tests/test_reasoning_flow.py` | test | request-response + trace-id propagation | `tests/test_reasoning_flow.py` | exact |
| `tests/test_reasoning_contract.py` | test | schema contract validation | `tests/test_reasoning_contract.py` | exact |

## Pattern Assignments

### `app/services/llm_client.py` (service, request-response)

**Analog:** self

**Imports and provider wiring** (lines 1-20):
```python
from openai import AsyncOpenAI, APIError, APITimeoutError, RateLimitError
from openai.types.chat import ChatCompletion
import httpx
```

**OpenRouter LLM call envelope** (lines 50-71):
```python
async def chat_completion(..., tools: list[dict[str, Any]] | None = None, tool_choice: str | None = "auto", thinking: str | None = None, timeout: float | None = None)
    response = await self.chat_client.chat.completions.create(...)
```

**Tool-call and strict-output metadata pattern**
```python
if tools is not None:
    payload["tools"] = tools
if response_format_model is not None:
    payload["response_format"] = response_format_model
```

**Error surface and retry posture**:
Uses OpenAI exception classes from client calls; phase 5 should keep this and add explicit boundary handling in caller.

**Raw embeddings path (multimodal/httpx escape hatch)** (lines 73-120):
```python
async with self._httpx_client() as client:
    response = await client.post("/embeddings", json={...})
raw_data = data.get("data")
if not isinstance(raw_data, list) or not raw_data: raise ValueError(...)
raw_embedding = first.get("embedding")
if len(raw_embedding) != output_dimensionality: raise ValueError(...)
```

### `app/config.py` (config, request-response)

**Analog:** self

**Provider config shape** (lines 15-40):
```python
openrouter_api_key: SecretStr
openrouter_base_url: str = "https://openrouter.ai/api/v1"
openrouter_http_referer: str = ...
openrouter_x_title: str = ...
llm_timeout_s: int = 60
llm_max_retries: int = 2
llm_connect_timeout_s: float = ...
llm_read_timeout_s: float = ...
```

**Current gap for Phase 5**
- No structured entries for firecrawl/searxng tool endpoints yet; if adding a dedicated grounding client, add `firecrawl_api_base_url`, `firecrawl_api_key`, and optional allowlist/allow-domain config adjacent to LLM config.

### `app/services/reasoning_schema.py` (utility/model, transform)

**Analog:** self

**Schema primitives and legacy fields** (lines 900-980):
```python
trace_id = _coerce_str(payload.get("trace_id"), "trace_id")
raw_groups = payload.get("food_groups") ...
action_raw = _coerce_str(payload.get("action"), "action")
decision_rationale = ...
```

**Group action model + coercion path** (lines 721-803):
```python
raw_actions = group.get("group_actions")
...
group_actions = _coerce_group_actions(group)
action = _primary_group_action(group_actions)
```

**Canonicalization logic used by callers** (lines 940-984):
```python
state_raw = _coerce_str(payload.get("meal_state"), "meal_state")
meal_state = state_raw if state_raw in _MEAL_STATES else _normalize_group_state(action_raw, state_raw)
```

### `app/services/reasoning_service.py` (service, request-response)

**Analog:** self

**Primary tool/caching path** (lines 1940-2010 and 2270+):
```python
trace_metadata = {"trace_id": None, "cached_tokens": None}
response = await llm.chat_completion(...)
trace_id_from_api, cached_tokens = _extract_trace_metadata(response)
normalized["trace_id"] = _normalize_trace_id_from_payload(...)
normalized["meal_reasoning"] = coerced_payload
```

**Structured-action extraction used by finalizer** (lines 887-103 etc):
```python
def _raw_group_actions(group: Mapping[str, Any]) -> set[str]:
    raw_actions = group.get("group_actions")
    ...
```

**Segment-level trace propagation** (lines 2027-2034):
```python
if hasattr(segment, "reasoning_trace_id") and normalized.get("trace_id"):
    segment.reasoning_trace_id = normalized.get("trace_id")
```

**Authoritative apply in phase flow** (lines 2264-2298):
```python
result = await apply_final_meal_resolution(...)
```

### `app/services/interview_service.py` (service, state-transition + request-response)

**Analog:** self

**Grounding seam and legacy handoff construction** (lines 865-1029):
```python
def build_grounding_reasoning_state(...):
    return {
      "handoff_target": "poll_post_interview_grounding",
      "finalizer_groups": [...],
      ...
    }
```

**Group finalizer orchestration** (lines 1067-1206):
```python
async def _run_group_finalizers(...):
    semaphore = asyncio.Semaphore(finalizer_concurrency)
    for prompt, group in grouped_items:
        tasks.append(_try_group_finalize(...))
```

**Handoff decision point** (line 1225):
```python
"poll_post_interview_grounding" if need_grounding_handoff else "apply_final_meal_resolution"
```

**Per-group action normalization** (lines 1757, 1792-1799):
```python
raw_actions = group.get("group_actions")
if not isinstance(raw_actions, list): return set()
```

**Trace metadata helper** (lines 1460-1469, 1866-1869):
```python
def _group_trace_id(...):
    return _optional_text(group_state.get("trace_id")) or ...
```

> Phase 5 target: keep `meal_reasoning`, trace propagation, and final write ordering, but replace `poll_post_interview_grounding` / `finalizer_groups` flow with synchronous grounding call inline in Phase 4 finalization path.

### `app/services/matching_service.py` (service, persistence + retry)

**Analog:** self

**Retry pattern** (lines 247-255, 286-303):
```python
async with AsyncRetrying(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(...),
    retry=retry_if_exception_type((ValueError, RuntimeError, ...)),
    reraise=True,
) as retry_state:
    return await func(...)
```

**Persistence style for per-segment final write** (lines 343+):
```python
meal_log.reasoning_state_json = ...
session.add(diary_entry)
session.add(food_item)
session.add(food_segment)
```

### `app/services/meal_resolution_service.py` (service, transform + persistence)

**Analog:** self

**Input shapes and grouped write contract** (lines 40-110):
```python
@dataclass
class ResolvedFoodInput:
    name: str
    calories_kcal: float
    ...
    trace_id: str | None = None
```

**Final write path** (lines 423-559):
```python
async def apply_final_meal_resolution(
    ...
) -> FinalizeResult:
    # writes diary entry, food items, visual matches, telemetry fields
```

### `app/services/grounding_stub.py` (utility/migration seam)

**Analog:** self

**Legacy gating stub** (lines 1-33):
```python
def should_use_packaged_or_restaurant_grounding(...):
    return source in {"PACKAGED", "RESTAURANT"}

def build_grounding_prep(...):
    if not should_use_packaged_or_restaurant_grounding(source):
        return None
    return {...}
```

Use this as the seam to replace with phase 5 tool-based grounding eligibility and payload builder.

### `app/services/tracing_service.py` (utility, audit/logging pattern)

**Analog:** self

**Trace lifecycle** (lines 85-152):
```python
@dataclass
class TracedCall:
    trace_id: str | None = None
    name: str | None = None

async def __aenter__... / __aexit__... end(...)
trace_id= _call_if_available(self.client, "get_current_trace_id") or self.trace_id
```

**Error and metadata handling**:
callers pass `status` and `metadata` so phase-5 tool grounding should attach provider/tool error counters and call `span.end()` in finally-style block.

### `bot/polling.py` (worker/orchestrator, event-driven worker flow)

**Analog:** self

**Current grounding worker seam to retire** (lines 936-1116):
```python
async def poll_post_interview_grounding() -> None:
    # loops INTERVIEW_LIMIT candidates in batches
    # calls _classify_grounding_failure()
    # calls run_reasoning_request(...)
    # calls _finalize_grounding_from_confirmation(...)
```

**Failure classification policy** (lines 297-387):
```python
def _classify_grounding_failure(error: Exception, fallback_category: str = "tool_execution") -> dict[str, Any]:
    ...
```

**State persistence helpers** (lines 252-293):
```python
def _set_interview_grounding_state(interview, active: bool, payload: dict[str, Any]) -> None:
    interview.state_key = "GROUNDING_PENDING" if active else "GROUNDING_COMPLETED"
    payload["roadmap_step"] = "GROUNDING_PENDING"
```

### `bot/handlers.py` (adapter/component)

**Analog:** self

**UI/UX handoff branch** (lines 787-810, 855-856):
```python
if state.get("roadmap_step") == "GROUNDING_PENDING":
    # message prompts user to confirm grounding completion
```

**Grounding pending state set** (lines 404-429):
```python
payload["roadmap_step"] = "GROUNDING_PENDING"
interview.state_key = "GROUNDING_PENDING"
meal.reasoning_state_json = interview_service.build_grounding_reasoning_state(...)
```

### Tests for telemetry/audit and grounding seam removal

#### `tests/test_interview_flow.py` (test)
- handoff assertions around reasoning-state payload:
  - `build_grounding_reasoning_state` expectations (`handoff_target`, `finalizer_groups`) at lines 1459 and 1315.
- interview seeding from `group_actions` lines 1009, 1028, 1164.
- grounding-handoff persistence assertions around line 1459 are key for migration.

#### `tests/test_match_flow.py` (test)
- grounding-poller assertions:
  - `poll_post_interview_grounding` invocation and degraded state at lines 1371, 1384.
- final write trace propagation (`trace_id`) at lines 976, 1018, 1076.
- segment-to-group state persistence around lines 1482, 682+.

#### `tests/test_bot_contract.py` (test)
- contract-level call wiring:
  - `bot_main` calls `poll_post_interview_grounding` (lines 3902, 3939).
  - handler/worker text path still blocks while in `GROUNDING_PENDING` (lines 561, 2731).

#### `tests/test_reasoning_flow.py` and `tests/test_reasoning_contract.py` (test)
- trace propagation checks:
  - trace id presence and fallback paths in reasoning outputs (`trace_id`: 170, 195, 196?).
- schema contract around `group_actions` enum and coercion at lines 63-67, 279, 293, 332.

## Shared Patterns

### OpenRouter + tool-call + structured-response envelope
**Source:** `[app/services/llm_client.py](/Users/mali/Documents/Projects/MealTracker/app/services/llm_client.py)`
Apply to: `reasoning_service`, `interview_service`, any new Phase 5 grounding coordinator.

```python
tools: list[dict[str, Any]] | None = None
tool_choice: str | None = "auto"
response_format=...
payload["tools"] = tools
payload["response_format"] = response_format
```

### Retry and timeout envelope
**Source:** `[app/services/reasoning_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/reasoning_service.py)`, `[app/services/matching_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/matching_service.py)`
Apply to all outbound LLM/tool/DB calls doing Phase 5 grounding and writes.

```python
AsyncRetrying(stop_after_attempt(...), wait_exponential_jitter(...), retry=retry_if_exception_type((...)), reraise=True)
```

### Error and failure classification contract
**Source:** `[bot/polling.py](/Users/mali/Documents/Projects/MealTracker/bot/polling.py:297)`
Apply to Phase 5 post-tool error reporting.

```python
def _classify_grounding_failure(error, fallback_category="tool_execution") -> dict[str, Any]:
    return {"category": category, "message": blocker, "recoverable": ...}
```

### Trace propagation + status metadata
**Source:** `[app/services/reasoning_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/reasoning_service.py:1866)` + `[app/services/tracing_service.py](/Users/mali/Documents/Projects/MealTracker/app/services/tracing_service.py:85)`
Apply to all phase 5 boundaries before/after tool-calls and authoritative writes.

```python
trace_id = _normalize_trace_id_from_payload(payload, response)
if trace_id:
    segment.reasoning_trace_id = trace_id
    state["trace_id"] = trace_id
```

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `app/services/grounding_tool_client.py` | service | tool-calling | No current dedicated firecrawl/searxng wrapper exists; use `llm_client.py` + raw httpx patterns. |
| `app/services/agentic_grounding_coordinator.py` | service | request-response | No existing “inline post-interview grounding in finalizer” implementation; only polling handoff worker exists in `bot/polling.py` and `interview_service.py`. |

## Metadata

**Analog search scope:** `app/`, `bot/`, `tests/`
**Files scanned:** 16 anchors across service, bot, and tests
**Pattern extraction date:** 2026-06-04
