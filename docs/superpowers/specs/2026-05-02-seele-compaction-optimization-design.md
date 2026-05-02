# Seele Compaction Optimization Design

**Date:** 2026-05-02
**Status:** Approved

## Overview

Refactor the seele.json compaction system to:
1. Compact each section independently (per-section triggers, per-section LLM flows)
2. Give short-term emotions/needs their own independent compaction logic with a dedicated LLM prompt
3. Add a global string-length fallback that submits complete seele.json and lets the LLM re-examine where personality-level changes should be stored

## 1. Per-Section Independent Triggers

**Current:** `_memory_limits_exceeded()` returns True if ANY section overflows, triggering a single unified LLM call that handles ALL sections.

**New:** Each section triggers its own compaction only when it overflows.

| Section | Trigger | Compaction Method |
|---|---|---|
| `user.personal_facts` | > 20 items | LLM compaction (existing prompt, stripped of emotions/needs rules) |
| `memorable_events` | > 20 entries | LLM compaction (existing prompt, stripped of emotions/needs rules) |
| any `short_term` list | > 12 items | **New independent LLM flow** (see Section 2) |

### Entry Point: `_compact_overflowing_memory_async` (refactored)

```python
async def _compact_overflowing_memory_async(self, data):
    if len(user.get("personal_facts", [])) > PERSONAL_FACTS_LIMIT:
        data = await self._compact_personal_facts_and_events_async(data)
    if len(data.get("memorable_events", {})) > MEMORABLE_EVENTS_LIMIT:
        data = await self._compact_personal_facts_and_events_async(data)
    if _short_term_limits_exceeded(data):
        data = await self._compact_short_term_overflow_async(data)
    return data
```

Note: `_compact_personal_facts_and_events_async` uses the existing LLM prompt (`build_seele_compaction_prompt`) but modified to only handle `personal_facts` and `memorable_events` — no emotions/needs sections in the prompt response shape.

## 2. Short-Term Emotions/Needs Independent Compaction

### 2.1 Trigger & Extraction

For each of the 4 short-term fields (`bot.emotions`, `bot.needs`, `user.emotions`, `user.needs`):
- If `short_term.length > 12`:
  - Deterministically truncate `short_term` to last 4 items
  - The removed items become `overflow_items`
  - Collect `overflow_items` + `existing long_term`

### 2.2 LLM Prompt (`build_short_term_compaction_prompt`)

**Input:** A JSON array of fields needing compaction, each with:
```json
[
  {
    "path": "/bot/emotions",
    "owner": "bot",
    "section": "emotions",
    "existing_long_term": "current long_term string",
    "overflow_items": ["item1", "item2", ...]
  },
  ...
]
```

**Output:** A JSON object with new `long_term` strings per field:
```json
{
  "/bot/emotions/long_term": "...",
  "/bot/needs/long_term": "...",
  "/user/emotions/long_term": "...",
  "/user/needs/long_term": "..."
}
```

**Prompt rules:**
- Only return the final result — no explanatory text, no recounting old results
- Cannot simply list/graft old items — must use ≤300 characters to re-describe the overall situation
- Ignore transient facts that won't cause long-term impact; only personality-shaping matters are worth recording
- Merge new observations into existing long-term context to form a coherent, concise re-description
- Output pure JSON only, no markdown fences, no explanation

### 2.3 Application (JSON Patch First)

```python
async def _compact_short_term_overflow_async(self, data):
    fields_to_compact = self._collect_overflow_fields(data)
    if not fields_to_compact:
        return data

    # Truncate short_term arrays in-place (deterministic)
    for field in fields_to_compact:
        field["section_data"]["short_term"] = field["section_data"]["short_term"][-4:]

    # LLM call with only overflow items + existing long_term
    new_long_terms = await self._llm_compact_short_terms(fields_to_compact)

    # Build JSON patch operations
    patch_ops = []
    for path, new_value in new_long_terms.items():
        patch_ops.append({"op": "replace", "path": path, "value": new_value})
        # Also update the corresponding short_term path (already truncated)
        short_path = "/".join(path.split("/")[:-1]) + "/short_term"
        owner, section = path.split("/")[1], path.split("/")[2]
        patch_ops.append({"op": "replace", "path": short_path, "value": data[owner][section]["short_term"]})

    success = update_seele_json(patch_ops)  # JSON Patch first
    if not success:
        await self._write_complete_seele_json_async(data)  # fallback
    return data
```

### 2.4 Deterministic Fallback

If LLM call fails entirely, use `fallback_compact_short_term_memory` (existing), but ensure the resulting `long_term` is still validated for length (see Section 3).

## 3. Global String-Length Fallback Validation

### 3.1 Trigger

After `_write_complete_seele_json_async` writes to disk (and at startup bootstrap in `ensure_seele_schema_current_async`), scan all leaf string values in the complete JSON. If any string exceeds 500 characters, trigger validation.

### 3.2 Two-Tier LLM Approach

**Tier 1 (outer):** Submit complete seele.json

- LLM receives the full seele.json with the instruction that some fields exceed length limits
- LLM re-examines whether any content reflects genuine personality-level changes
- If so: dialectically synthesize and distill the core, saving it to the most appropriate location in seele.json (could be `personality.description`, `worldview_and_values`, `memorable_events`, `long_term` emotions/needs, `relationship_with_user`, etc.)
- If not: directly compress the oversize strings to ≤300 characters
- Final constraint: all string fields must be ≤300 characters

**Tier 2 (inner):** Per-string retry for remaining oversize strings

If Tier 1 still leaves strings exceeding 300 characters:
- For each remaining oversize string, a focused LLM call with:
  - The oversize string content
  - Original seele.json context
  - Instruction: compress/summarize this specific string to ≤300 characters while preserving essential meaning
- Retry up to 3 times per string
- If a string still exceeds 300 characters after 3 retries: log a warning, keep the last result, and continue

**No mechanical truncation — ever.**

### 3.3 Application (JSON Patch First)

```python
async def _compact_long_strings_async(self, data):
    oversized = self._collect_oversized_strings(data, threshold=500)
    if not oversized:
        return data

    # Tier 1: full seele.json LLM compaction
    revised_data = await self._llm_compact_long_strings_full(data)
    if revised_data:
        # Apply via JSON Patch first
        patch_ops = dict_to_json_patch(revised_data)
        success = update_seele_json(patch_ops)
        if not success:
            await self._write_complete_seele_json_async(revised_data)

    # Tier 2: per-string retry for any remaining >300 char strings
    data = load_seele_json()  # re-read after patch
    for path, value in self._collect_oversized_strings(data, threshold=300):
        for attempt in range(3):
            compressed = await self._llm_compress_single_string(value, data)
            if len(compressed) <= 300:
                update_seele_json([{"op": "replace", "path": path, "value": compressed}])
                break
            if attempt == 2:
                logger.warning(f"Could not compress string at {path} below 300 chars after 3 attempts")
    return data
```

### 3.4 Integration Points

| Call Site | When |
|---|---|
| `_write_complete_seele_json_async` | After normalize + compaction, before writing to disk |
| `ensure_seele_schema_current_async` | After bootstrap normalization |
| `_apply_generated_patch_async` | After successful patch + compaction check |

## 4. Files Changed

| File | Changes |
|---|---|
| `src/prompts/memory_prompts.py` | Add `build_short_term_compaction_prompt`; remove emotions/needs rules (rules 8-10) from `build_seele_compaction_prompt` |
| `src/memory/seele.py` | Refactor `_compact_overflowing_memory_async` to per-section triggers; add `_compact_short_term_overflow_async`, `_collect_overflow_fields`, `_compact_long_strings_async`, `_collect_oversized_strings`, `_llm_compact_short_terms`, `_llm_compact_long_strings_full`, `_llm_compress_single_string` |
| `src/prompts/runtime.py` | Add `get_short_term_compaction_prompt` |
| `src/llm/chat_client.py` | Add `generate_short_term_compaction_async`, `generate_string_length_compaction_async` |
| `src/llm/memory_client.py` | Add corresponding async methods |
| `tests/test_memory.py` | Add tests for per-section independent compaction, short-term compaction, string-length fallback |

## 5. Constants

```python
SHORT_TERM_MEMORY_LIMIT = 12        # unchanged
SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION = 4  # unchanged
PERSONAL_FACTS_LIMIT = 20           # unchanged
MEMORABLE_EVENTS_LIMIT = 20         # unchanged
MAX_STRING_LENGTH_WARNING = 500     # new: triggers Tier 1
MAX_STRING_LENGTH_HARD = 300        # new: must not exceed
STRING_COMPACTION_MAX_RETRIES = 3   # new: Tier 2 retry limit
```

## 6. Validation Rules

1. **Structure:** `validate_seele_structure()` — existing, unchanged
2. **Compaction output:** `_validate_compaction_candidate()` — updated to only check `personal_facts` + `memorable_events` (no emotions/needs)
3. **Short-term compaction output:** JSON with long_term strings, each ≤300 chars, non-empty, proper JSON structure
4. **String length post-compaction:** Scan all leaf strings, confirm none exceed 300 characters
5. **Fallback:** LLM failure → existing `_fallback_compact_seele_data` for personal_facts/memorable_events; `fallback_compact_short_term_memory` for short-term; Tier 2 per-string retry for length violations
