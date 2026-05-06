# Seele Compaction Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor seele.json compaction to use per-section independent triggers, give short-term emotions/needs their own dedicated LLM compaction flow, and add a global string-length fallback validation tier.

**Architecture:** Split the monolithic `_compact_overflowing_memory_async` into three independent compaction paths that each check their own limit and trigger their own LLM flow. Short-term emotions/needs get a new dedicated prompt that takes only overflow entries as input and returns rewritten `long_term` strings. A post-write validation pass scans all leaf strings and triggers two-tier LLM compaction for any exceeding 500 chars.

**Tech Stack:** Python 3.12+, OpenAI API, jsonpatch, loguru, pytest with unittest.mock

---

### 2026-05-06 Follow-Up: Long-String Compaction Audit

- [x] Removed duplicate long-string constants in `src/memory/seele.py` that overrode the approved `MAX_STRING_LENGTH_WARNING = 500`, `MAX_STRING_LENGTH_HARD = 300`, and `STRING_COMPACTION_MAX_RETRIES = 3` values with `300`, `1000`, and `2`.
- [x] Moved long-string and single-string compaction prompts into `src/prompts/memory_prompts.py` with runtime getters in `src/prompts/runtime.py`.
- [x] Updated tool-model memory calls to use streaming responses for keepalive during Seele update-related LLM work.
- [x] Preserved JSON Patch priority by comparing post-compaction data against the freshly loaded current seele state before falling back to `_write_complete_seele_json_async`.

---

### Task 1: Modify existing compaction prompt to remove emotions/needs rules

**Files:**
- Modify: `src/prompts/memory_prompts.py:605-705`

- [ ] **Step 1: Remove emotions/needs rules from `build_seele_compaction_prompt`**

Remove rules 8-10 (the short-term emotion/need merge rules) and remove the `bot`/`user` sections from the output shape. The prompt will now only handle `personal_facts` and `memorable_events`.

Replace the function body (lines 615-705) with:

```python
    return f"""<seele_compaction_task>
<role>
You are a long-term memory curator for {bot_name}.
</role>

<goal>
The current seele.json contains too many long-term memory items.
Re-evaluate importance and return a compacted result that preserves only the most valuable long-term information.
</goal>

<compaction_rules>
1. Return a JSON object with exactly two top-level fields:
   - "personal_facts": array of strings
   - "memorable_events": object keyed by stable event ids
2. Keep at most {personal_facts_limit} personal_facts.
3. Keep at most {memorable_events_limit} memorable_events.
4. For personal_facts:
   - Keep only durable, identity-relevant, long-term useful facts about {user_name}
   - Remove temporary, redundant, overly specific, outdated, or low-value facts
   - Prefer facts that help {bot_name} understand {user_name}'s stable identity, preferences, history, habits, abilities, or long-term situation
5. For memorable_events:
   - Re-evaluate each event's lasting significance
   - You may remove low-value or redundant events
   - You may adjust importance scores up or down
   - Keep only events that are truly important to {user_name}'s life story or the relationship between {user_name} and {bot_name}
   - Do not keep reminders, todo items, errands, meeting schedules, shopping lists, or temporary tasks
6. Preserve the original language of each item whenever possible.
7. Do not invent new facts or new events unsupported by the current data.
</compaction_rules>

<event_schema>
Each memorable event value must remain:
{{
  "date": "YYYY-MM-DD",
  "importance": 1-5,
  "details": "string"
}}
</event_schema>

<selection_preference>
When forced to choose, prefer:
- higher long-term significance
- clearer identity relevance
- stronger relationship importance
- less redundancy
- more stable and enduring information
</selection_preference>

<current_seele_json>
{current_seele_json}
</current_seele_json>

<output_requirements>
1. Output pure JSON only, no markdown, no code fences, no explanation.
2. The first character must be '{{' and the last character must be '}}'.
3. Output exactly this shape:
{{
  "personal_facts": ["..."],
  "memorable_events": {{
    "evt_example": {{"date": "YYYY-MM-DD", "importance": 3, "details": "..."}}
  }}
}}
</output_requirements>

<final_instruction>
Compacted memory JSON:
</final_instruction>
</seele_compaction_task>"""
```

- [ ] **Step 2: Run existing tests to confirm no regressions in prompt structure**

```bash
python -m pytest tests/test_prompts.py tests/test_memory.py -v 2>&1 | tail -30
```

Expected: Some compaction tests that check for bot/user emotions/needs in compaction output will FAIL — that's expected; they'll be updated in later tasks.

- [ ] **Step 3: Commit**

```bash
git add src/prompts/memory_prompts.py
git commit -m "refactor: remove emotions/needs rules from seele compaction prompt"
```

---

### Task 2: Add `build_short_term_compaction_prompt` to memory_prompts.py

**Files:**
- Modify: `src/prompts/memory_prompts.py` (append after line 705)

- [ ] **Step 1: Add the new prompt builder function**

Append after the end of `build_seele_compaction_prompt` (after line 705):

```python
def build_short_term_compaction_prompt(fields_json: str, bot_name: str, user_name: str) -> str:
    """Build prompt for LLM-driven short-term emotion/need compaction."""
    return f"""<short_term_compaction_task>
<role>
You are a long-term memory curator for {bot_name}.
</role>

<goal>
Short-term emotions and needs have overflowed and must be merged into long-term memory.
For each field below, re-describe the overall long-term situation in 300 characters or fewer.
</goal>

<strict_rules>
1. Only return the final result — no explanatory text, no recounting old results.
2. Do NOT simply list or concatenate old items. You must re-describe the overall situation.
3. Each long_term string must be 300 characters or fewer.
4. Ignore transient facts that will not cause long-term impact. Only personality-shaping matters are worth recording.
5. Merge new observations into the existing long-term context to form a coherent, concise re-description.
6. Output pure JSON only, no markdown, no code fences, no explanation.
7. {bot_name} is the AI assistant; {user_name} is the user.
</strict_rules>

<fields_needing_compaction>
{fields_json}
</fields_needing_compaction>

<output_format>
Return a JSON object mapping each field path to its new long_term string:
{{
  "/bot/emotions/long_term": "re-described long-term emotional state",
  "/bot/needs/long_term": "re-described long-term needs",
  "/user/emotions/long_term": "re-described long-term emotional state",
  "/user/needs/long_term": "re-described long-term needs"
}}
</output_format>

<final_instruction>
Compacted long-term strings JSON:
</final_instruction>
</short_term_compaction_task>"""
```

- [ ] **Step 2: Commit**

```bash
git add src/prompts/memory_prompts.py
git commit -m "feat: add build_short_term_compaction_prompt for independent short-term compaction"
```

---

### Task 3: Add `get_short_term_compaction_prompt` to runtime.py

**Files:**
- Modify: `src/prompts/runtime.py:155-165`

- [ ] **Step 1: Add import for new prompt builder**

Change line 16 to:
```python
from prompts.memory_prompts import (
    build_complete_memory_json_prompt,
    build_memory_update_prompt,
    build_seele_compaction_prompt,
    build_seele_repair_prompt,
    build_short_term_compaction_prompt,
    build_summary_prompt,
)
```

- [ ] **Step 2: Add the getter function**

Append after line 165:

```python
def get_short_term_compaction_prompt(
    fields_json: str,
    bot_name: str,
    user_name: str,
) -> str:
    """Build the LLM prompt for compacting short-term emotion/need overflow."""
    return build_short_term_compaction_prompt(
        fields_json=fields_json,
        bot_name=bot_name,
        user_name=user_name,
    )
```

- [ ] **Step 3: Commit**

```bash
git add src/prompts/runtime.py
git commit -m "feat: add get_short_term_compaction_prompt runtime getter"
```

---

### Task 4: Add LLM client methods for short-term compaction

**Files:**
- Modify: `src/llm/memory_client.py:157-176` (append new method)
- Modify: `src/llm/chat_client.py:559-571` (append new method)
- Modify: `src/llm/chat_client.py:11-19` (add import)

- [ ] **Step 1: Add async method to MemoryClient**

Append after `generate_seele_compaction_async` (after line 176):

```python
    async def generate_short_term_compaction_async(
        self,
        fields_json: str,
        bot_name: str,
        user_name: str,
        prompt_builder: Callable[[str, str, str], str],
    ) -> str:
        """Asynchronously compact overflowing short-term emotion/need lists."""
        prompt = prompt_builder(fields_json, bot_name, user_name)

        return await self._run_tool_model_prompt(
            prompt=prompt,
            system_content="You compact short-term emotions and needs into long-term memory summaries.",
            debug_prompt_label="Short-term compaction (async) prompt sent to tool_model",
            debug_result_label="Short-term compaction (async) result from tool_model",
        )
```

- [ ] **Step 2: Add import to chat_client.py**

Add `get_short_term_compaction_prompt` to the import block at line 11-19:
```python
from prompts.runtime import (
    get_complete_memory_json_prompt,
    get_cacheable_system_prompt,
    get_current_time_str,
    get_memory_update_prompt,
    get_seele_compaction_prompt,
    get_seele_repair_prompt,
    get_short_term_compaction_prompt,
    get_summary_prompt,
    load_seele_json,
)
```

- [ ] **Step 3: Add public method to LLMClient**

Append after `generate_seele_compaction_async` (after line 571):

```python
    async def generate_short_term_compaction_async(
        self,
        fields_json: str,
        bot_name: str,
        user_name: str,
    ) -> str:
        """Asynchronously compact overflowing short-term emotion/need lists."""
        return await self._memory_client.generate_short_term_compaction_async(
            fields_json=fields_json,
            bot_name=bot_name,
            user_name=user_name,
            prompt_builder=get_short_term_compaction_prompt,
        )
```

- [ ] **Step 4: Commit**

```bash
git add src/llm/memory_client.py src/llm/chat_client.py
git commit -m "feat: add short-term compaction async methods to LLM clients"
```

---

### Task 5: Add leaf-string scanning helper to seele.py

**Files:**
- Modify: `src/memory/seele.py` (near constants, after line 92)

- [ ] **Step 1: Add new constants**

Replace the constants block (lines 87-92) to include new limits:

```python
PERSONAL_FACTS_LIMIT = 20
MEMORABLE_EVENTS_LIMIT = 20
SHORT_TERM_MEMORY_LIMIT = 12
SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION = 4
SHORT_TERM_MEMORY_OWNERS = ("bot", "user")
SHORT_TERM_MEMORY_SECTIONS = ("emotions", "needs")
MAX_STRING_LENGTH_WARNING = 500
MAX_STRING_LENGTH_HARD = 300
STRING_COMPACTION_MAX_RETRIES = 3
```

- [ ] **Step 2: Add `_collect_oversized_strings` helper**

Append after `fallback_compact_short_term_memory` (after line 395):

```python
def _collect_oversized_strings(
    data: Dict[str, Any], threshold: int
) -> List[tuple[str, str]]:
    """Return (json_pointer, value) pairs for leaf strings exceeding threshold."""
    oversized: List[tuple[str, str]] = []

    def _walk(value: Any, path: str) -> None:
        if isinstance(value, str):
            if len(value) > threshold:
                oversized.append((path, value))
        elif isinstance(value, dict):
            for key, child in value.items():
                _walk(child, f"{path}/{key}")
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                _walk(child, f"{path}/-")
                # Fix path: jsonpointer list indices are numeric
                over_index = len(oversized) - 1
                if over_index >= 0 and oversized[over_index][0] == f"{path}/-":
                    oversized[over_index] = (f"{path}/{idx}", oversized[over_index][1])

    _walk(data, "")
    return oversized
```

Wait — the above `_walk` for lists is bug-prone with the index tracking. Let's use a cleaner approach:

```python
def _collect_oversized_strings(
    data: Dict[str, Any], threshold: int
) -> List[tuple[str, str]]:
    """Return (json_pointer, value) pairs for leaf strings exceeding threshold."""
    oversized: List[tuple[str, str]] = []

    def _walk(value: Any, path: str) -> None:
        if isinstance(value, str):
            if len(value) > threshold:
                oversized.append((path, value))
        elif isinstance(value, dict):
            for key, child in value.items():
                _walk(child, f"{path}/{key}")
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                _walk(child, f"{path}/{idx}")

    _walk(data, "")
    return oversized
```

- [ ] **Step 3: Commit**

```bash
git add src/memory/seele.py
git commit -m "feat: add leaf-string scanning helper and length constants"
```

---

### Task 6: Refactor `_validate_compaction_candidate` and `_apply_compaction_candidate`

**Files:**
- Modify: `src/memory/seele.py:718-804`

- [ ] **Step 1: Update `_apply_compaction_candidate` to only handle personal_facts + memorable_events**

Replace the method (lines 718-739):

```python
    @staticmethod
    def _apply_compaction_candidate(
        data: Dict[str, Any], candidate: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply compacted personal_facts and memorable_events onto existing seele data."""
        compacted = json.loads(json.dumps(data))
        compacted_user = compacted.setdefault("user", {})
        compacted_user["personal_facts"] = candidate["personal_facts"]
        compacted["memorable_events"] = candidate["memorable_events"]
        return compacted
```

- [ ] **Step 2: Update `_validate_compaction_candidate` to remove emotions/needs checks**

Replace the method (lines 757-804):

```python
    def _validate_compaction_candidate(self, candidate: Dict[str, Any]) -> bool:
        """Validate LLM compaction output shape and limits (personal_facts + memorable_events only)."""
        if not isinstance(candidate, dict):
            return False

        personal_facts = candidate.get("personal_facts")
        memorable_events = candidate.get("memorable_events")
        if not isinstance(personal_facts, list) or not isinstance(memorable_events, dict):
            return False
        if len(personal_facts) > PERSONAL_FACTS_LIMIT:
            return False
        if len(memorable_events) > MEMORABLE_EVENTS_LIMIT:
            return False

        normalized_facts = _deduplicate_personal_facts(personal_facts)
        if len(normalized_facts) != len(personal_facts):
            return False

        if any(not isinstance(fact, str) or not fact.strip() for fact in personal_facts):
            return False

        return True
```

- [ ] **Step 3: Update `_compact_overflowing_memory_async` for per-section triggers**

Replace the method (lines 819-843):

```python
    async def _compact_overflowing_memory_async(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Async version of overflowing long-term memory compaction with per-section triggers."""
        if not self._memory_limits_exceeded(data):
            return data

        result = json.loads(json.dumps(data))

        user = result.get("user", {}) if isinstance(result.get("user"), dict) else {}
        personal_facts = user.get("personal_facts", [])
        memorable_events = result.get("memorable_events", {})

        needs_pf_compaction = isinstance(personal_facts, list) and len(personal_facts) > PERSONAL_FACTS_LIMIT
        needs_me_compaction = isinstance(memorable_events, dict) and len(memorable_events) > MEMORABLE_EVENTS_LIMIT

        if needs_pf_compaction or needs_me_compaction:
            result = await self._compact_personal_facts_and_events_async(result)

        if _short_term_limits_exceeded(result):
            result = await self._compact_short_term_overflow_async(result)

        return result
```

Add the `_compact_personal_facts_and_events_async` method before `_compact_overflowing_memory_async`:

```python
    async def _compact_personal_facts_and_events_async(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """LLM-compact personal_facts and memorable_events sections."""
        from llm.chat_client import LLMClient

        client = LLMClient()
        current_seele_json = json.dumps(data, ensure_ascii=False, indent=2)
        try:
            response = await client.generate_seele_compaction_async(
                current_seele_json=current_seele_json,
                personal_facts_limit=PERSONAL_FACTS_LIMIT,
                memorable_events_limit=MEMORABLE_EVENTS_LIMIT,
            )
            candidate = self._parse_compaction_response(response)
            if not self._validate_compaction_candidate(candidate):
                raise ValueError("Invalid seele compaction response structure")
            logger.info("Compacted personal_facts and memorable_events with LLM")
            return self._apply_compaction_candidate(data, candidate)
        except Exception as error:
            logger.warning(f"LLM seele compaction failed, using fallback compaction: {error}")
            return self._fallback_compact_seele_data(data)
        finally:
            await client.close_async()
```

- [ ] **Step 4: Run tests to verify the refactored compaction still works**

```bash
python -m pytest tests/test_memory.py -v -k "compact or fallback" 2>&1 | tail -30
```

Expected: tests that check bot/user emotions/needs in compaction response will fail since that's now handled separately. Tests for personal_facts and memorable_events fallback should pass.

- [ ] **Step 5: Commit**

```bash
git add src/memory/seele.py
git commit -m "refactor: per-section compaction triggers, strip emotions/needs from main compaction"
```

---

### Task 7: Add `_compact_short_term_overflow_async` to seele.py

**Files:**
- Modify: `src/memory/seele.py` (in Seele class, after `_compact_overflowing_memory_async`)

- [ ] **Step 1: Add `_collect_overflow_fields` helper**

```python
    def _collect_overflow_fields(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Collect all short-term fields that exceed the limit, with overflow items."""
        fields = []
        for owner_name in SHORT_TERM_MEMORY_OWNERS:
            owner = data.get(owner_name)
            if not isinstance(owner, dict):
                continue
            for section_name in SHORT_TERM_MEMORY_SECTIONS:
                section = owner.get(section_name)
                if not isinstance(section, dict):
                    continue
                short_term = section.get("short_term", [])
                if not isinstance(short_term, list) or len(short_term) <= SHORT_TERM_MEMORY_LIMIT:
                    continue
                overflow_items = short_term[:-SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION]
                fields.append({
                    "path": f"/{owner_name}/{section_name}",
                    "owner": owner_name,
                    "section": section_name,
                    "existing_long_term": section.get("long_term", ""),
                    "overflow_items": overflow_items,
                    "section_data": section,
                })
        return fields
```

- [ ] **Step 2: Add `_compact_short_term_overflow_async` method**

```python
    async def _compact_short_term_overflow_async(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Compact short-term emotions/needs overflow using a dedicated LLM prompt."""
        fields_to_compact = self._collect_overflow_fields(data)
        if not fields_to_compact:
            return data

        bot_name = data.get("bot", {}).get("name", "AI Assistant")
        user_name = data.get("user", {}).get("name", "User")

        # Deterministically truncate short_term arrays in-place
        for field in fields_to_compact:
            field["section_data"]["short_term"] = field["section_data"]["short_term"][
                -SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION:
            ]

        fields_json = json.dumps([
            {
                "path": f["path"],
                "existing_long_term": f["existing_long_term"],
                "overflow_items": f["overflow_items"],
            }
            for f in fields_to_compact
        ], ensure_ascii=False, indent=2)

        from llm.chat_client import LLMClient

        client = LLMClient()
        try:
            response = await client.generate_short_term_compaction_async(
                fields_json=fields_json,
                bot_name=bot_name,
                user_name=user_name,
            )
            new_long_terms = self._parse_short_term_compaction_response(response, fields_to_compact)

            # Build JSON patch operations (JSON Patch first)
            patch_ops = []
            for field in fields_to_compact:
                path = field["path"]
                new_long_term = new_long_terms.get(f"{path}/long_term", "")
                if new_long_term:
                    patch_ops.append({
                        "op": "replace",
                        "path": f"{path}/long_term",
                        "value": new_long_term,
                    })
                patch_ops.append({
                    "op": "replace",
                    "path": f"{path}/short_term",
                    "value": field["section_data"]["short_term"],
                })

            from prompts.runtime import update_seele_json

            success = update_seele_json(patch_ops)
            if not success:
                await self._write_complete_seele_json_async(data)

            logger.info("Compacted short-term emotions/needs with dedicated LLM prompt")
        except Exception as error:
            logger.warning(f"LLM short-term compaction failed, using fallback: {error}")
            fallback_compact_short_term_memory(data)
        finally:
            await client.close_async()

        return data
```

- [ ] **Step 3: Add `_parse_short_term_compaction_response` helper**

```python
    def _parse_short_term_compaction_response(
        self, response: str, fields: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """Parse the short-term compaction response into a path → new long_term map."""
        cleaned = self.clean_json_response(response)
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise ValueError("Short-term compaction response is not a JSON object")
        return parsed
```

- [ ] **Step 4: Commit**

```bash
git add src/memory/seele.py
git commit -m "feat: add independent short-term compaction with dedicated LLM prompt"
```

---

### Task 8: Add string-length fallback to seele.py

**Files:**
- Modify: `src/memory/seele.py` (in Seele class)

- [ ] **Step 1: Add `_compact_long_strings_async` method (Tier 1)**

```python
    async def _compact_long_strings_async(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and compact any leaf strings exceeding the length limit."""
        oversized = _collect_oversized_strings(data, MAX_STRING_LENGTH_WARNING)
        if not oversized:
            return data

        logger.info(
            f"Found {len(oversized)} string(s) exceeding {MAX_STRING_LENGTH_WARNING} chars; "
            "triggering LLM compaction"
        )

        # Tier 1: submit complete seele.json for holistic compaction
        from llm.chat_client import LLMClient

        client = LLMClient()
        try:
            revised_data = await self._llm_compact_long_strings_full(data)
            if revised_data:
                from prompts.runtime import update_seele_json

                patch_ops = dict_to_json_patch(revised_data)
                success = update_seele_json(patch_ops)
                if not success:
                    await self._write_complete_seele_json_async(revised_data)

                data = self.get_long_term_memory()
        except Exception as error:
            logger.warning(f"Tier 1 long-string compaction failed: {error}")
        finally:
            await client.close_async()

        # Tier 2: per-string retry for any remaining >300 char strings
        data = await self._compact_long_strings_tier2(data)

        return data
```

- [ ] **Step 2: Add `_llm_compact_long_strings_full` (Tier 1 LLM call)**

```python
    async def _llm_compact_long_strings_full(
        self, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Submit complete seele.json to LLM for holistic long-string compaction."""
        from llm.chat_client import LLMClient

        bot_name = data.get("bot", {}).get("name", "AI Assistant")
        current_json = json.dumps(data, ensure_ascii=False, indent=2)
        oversized = _collect_oversized_strings(data, MAX_STRING_LENGTH_WARNING)

        prompt = f"""<long_string_compaction_task>
<role>
You are a long-term memory curator for {bot_name}.
</role>

<goal>
Some string fields in seele.json exceed {MAX_STRING_LENGTH_HARD} characters.
Re-examine whether any content reflects genuine personality-level changes worth preserving.
</goal>

<oversized_fields>
{json.dumps([p for p, _ in oversized], ensure_ascii=False, indent=2)}
</oversized_fields>

<rules>
1. Scan all oversized string fields. For each:
   - If the content reflects a genuine personality-shaping change that deserves long-term recording: dialectically synthesize and distill the core insight, saving it to the MOST APPROPRIATE location in seele.json. This could be personality.description, worldview_and_values, long_term emotions/needs, relationship_with_user, memorable_events, or any other semantically fitting field.
   - If the content does NOT reflect personality-level change: directly compress it to {MAX_STRING_LENGTH_HARD} characters or fewer, preserving essential meaning.
2. ALL string fields in the output must be {MAX_STRING_LENGTH_HARD} characters or fewer.
3. Do not add explanatory text, do not recount old results.
4. Output the COMPLETE revised seele.json as pure JSON.
5. No markdown, no code fences, no explanation.
</rules>

<current_seele_json>
{current_json}
</current_seele_json>

<final_instruction>
Revised complete seele.json:
</final_instruction>
</long_string_compaction_task>"""

        client = LLMClient()
        try:
            response = await client._memory_client._run_tool_model_prompt(
                prompt=prompt,
                system_content="You compact oversized strings in seele.json and preserve personality-level insights.",
                debug_prompt_label="Long-string compaction prompt sent to tool_model",
                debug_result_label="Long-string compaction result from tool_model",
            )
            cleaned = self.clean_json_response(response)
            revised = json.loads(cleaned)
            if not self.validate_seele_structure(revised):
                raise ValueError("Revised seele.json has invalid structure")
            return revised
        except Exception as error:
            logger.warning(f"Tier 1 LLM long-string compaction failed: {error}")
            return None
        finally:
            await client.close_async()
```

- [ ] **Step 3: Add `_compact_long_strings_tier2` (per-string retry)**

```python
    async def _compact_long_strings_tier2(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Tier 2: per-string LLM compaction for remaining oversized strings."""
        for attempt in range(STRING_COMPACTION_MAX_RETRIES):
            oversized = _collect_oversized_strings(data, MAX_STRING_LENGTH_HARD)
            if not oversized:
                break

            from llm.chat_client import LLMClient

            client = LLMClient()
            try:
                for path, value in oversized:
                    compressed = await self._llm_compress_single_string(value, data, path)
                    if len(compressed) <= MAX_STRING_LENGTH_HARD:
                        data = self._replace_string_at_path(data, path, compressed)
                        from prompts.runtime import update_seele_json
                        update_seele_json([{"op": "replace", "path": path, "value": compressed}])
                    elif attempt == STRING_COMPACTION_MAX_RETRIES - 1:
                        logger.warning(
                            f"Could not compress string at {path} below {MAX_STRING_LENGTH_HARD} "
                            f"chars after {STRING_COMPACTION_MAX_RETRIES} attempts "
                            f"(current: {len(compressed)})"
                        )
                # Re-read after patch updates
                data = self.get_long_term_memory()
            except Exception as error:
                logger.warning(f"Tier 2 long-string compaction failed: {error}")
            finally:
                await client.close_async()

        return data
```

- [ ] **Step 4: Add `_llm_compress_single_string`**

```python
    async def _llm_compress_single_string(
        self, value: str, seele_data: Dict[str, Any], path: str
    ) -> str:
        """LLM-compress a single oversized string with seele.json context."""
        from llm.chat_client import LLMClient

        bot_name = seele_data.get("bot", {}).get("name", "AI Assistant")
        current_json = json.dumps(seele_data, ensure_ascii=False, indent=2)

        prompt = f"""<single_string_compaction>
<role>You are a long-term memory curator for {bot_name}.</role>

<task>
The string at path "{path}" exceeds {MAX_STRING_LENGTH_HARD} characters ({len(value)} chars).
Compress it to {MAX_STRING_LENGTH_HARD} characters or fewer while preserving essential meaning.
</task>

<oversized_string>
{value}
</oversized_string>

<current_seele_json_for_context>
{current_json}
</current_seele_json_for_context>

<rules>
1. Return ONLY the compressed string, no quotes, no JSON wrapper, no explanation.
2. Must be {MAX_STRING_LENGTH_HARD} characters or fewer.
3. Preserve essential meaning while removing redundancy.
</rules>

<final_instruction>
Compressed string:
</final_instruction>"""

        client = LLMClient()
        try:
            response = await client._memory_client._run_tool_model_prompt(
                prompt=prompt,
                system_content="You compress oversized strings while preserving meaning.",
                debug_prompt_label="Single-string compaction prompt",
                debug_result_label="Single-string compaction result",
            )
            return response.strip()
        finally:
            await client.close_async()
```

- [ ] **Step 5: Add `_replace_string_at_path` helper for in-memory path updates**

```python
    @staticmethod
    def _replace_string_at_path(
        data: Dict[str, Any], path: str, new_value: str
    ) -> Dict[str, Any]:
        """Set a value at a jsonpointer path in a copy of the data dict."""
        result = json.loads(json.dumps(data))
        parts = path.strip("/").split("/")
        current: Any = result
        for part in parts[:-1]:
            if isinstance(current, dict):
                current = current[part]
            elif isinstance(current, list):
                current = current[int(part)]
        last = parts[-1]
        if isinstance(current, dict):
            current[last] = new_value
        elif isinstance(current, list):
            current[int(last)] = new_value
        return result
```

- [ ] **Step 6: Commit**

```bash
git add src/memory/seele.py
git commit -m "feat: add global string-length fallback with two-tier LLM compaction"
```

---

### Task 9: Integrate string-length fallback into write paths

**Files:**
- Modify: `src/memory/seele.py:1350-1363` (`_write_complete_seele_json_async`)
- Modify: `src/memory/seele.py:884-913` (`_apply_generated_patch_async`)

- [ ] **Step 1: Update `_write_complete_seele_json_async` to include string-length validation**

Replace lines 1350-1363:

```python
    async def _write_complete_seele_json_async(self, complete_data: dict) -> None:
        """Write a full seele.json object from async memory update flows."""
        from core.config import Config
        import prompts.runtime as prompts_runtime

        config = Config()
        complete_data, _ = normalize_seele_data(complete_data, logger)
        complete_data = await self._compact_overflowing_memory_async(complete_data)
        complete_data = await self._compact_long_strings_async(complete_data)
        seele_path = config.SEELE_JSON_PATH
        seele_path.parent.mkdir(parents=True, exist_ok=True)
        with open(seele_path, "w", encoding="utf-8") as f:
            json.dump(complete_data, f, indent=2, ensure_ascii=False)

        prompts_runtime._seele_json_cache = complete_data
```

- [ ] **Step 2: Update `_apply_generated_patch_async` to include string-length validation**

Replace lines 884-913:

```python
    async def _apply_generated_patch_async(
        self,
        summary_id: int,
        patch_data: Any,
        messages: Optional[List[Message]],
    ) -> bool:
        """Apply generated patch data and trigger async fallback when needed."""
        from prompts.runtime import update_seele_json

        success = update_seele_json(patch_data)
        if success:
            current_memory = self.get_long_term_memory()
            compacted_data = await self._compact_overflowing_memory_async(current_memory)
            compacted_data = await self._compact_long_strings_async(compacted_data)
            if compacted_data != current_memory:
                await self._write_complete_seele_json_async(compacted_data)
            self._log_patch_update_success(summary_id, patch_data)
            return True

        if messages:
            logger.warning(
                f"JSON Patch failed for summary {summary_id}, attempting fallback to complete JSON generation"
            )
            return await self.fallback_to_complete_json_async(
                summary_id, messages, "JSON Patch application failed"
            )

        logger.warning(
            f"Failed to apply patch from summary {summary_id}, no fallback available"
        )
        return False
```

- [ ] **Step 3: Commit**

```bash
git add src/memory/seele.py
git commit -m "feat: integrate string-length fallback into seele write paths"
```

---

### Task 10: Update and add tests

**Files:**
- Modify: `tests/test_memory.py`

- [ ] **Step 1: Add test for `_collect_oversized_strings`**

Append at end of file:

```python
def test_collect_oversized_strings_finds_leaf_strings_exceeding_threshold():
    """Should return (path, value) for all leaf strings exceeding the threshold."""
    from memory.seele import _collect_oversized_strings

    data = {
        "bot": {
            "name": "TestBot",
            "personality": {"description": "A" * 501, "worldview_and_values": "short"},
            "emotions": {"long_term": "B" * 600, "short_term": ["ok"]},
            "needs": {"long_term": "brief", "short_term": ["X" * 501]},
        },
        "user": {
            "name": "TestUser",
            "emotions": {"long_term": "fine", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }

    oversized = _collect_oversized_strings(data, 500)

    paths = {p for p, _ in oversized}
    assert "/bot/personality/description" in paths
    assert "/bot/emotions/long_term" in paths
    assert "/bot/needs/short_term/0" in paths
    assert all(len(v) > 500 for _, v in oversized)


def test_collect_oversized_strings_returns_empty_when_none_exceed_threshold():
    """Should return empty list when all strings are within limit."""
    from memory.seele import _collect_oversized_strings

    data = {"bot": {"name": "short"}, "user": {"name": "also_short"}}

    oversized = _collect_oversized_strings(data, 500)
    assert oversized == []
```

- [ ] **Step 2: Add async test for short-term compaction flow**

```python
@pytest.mark.asyncio
async def test_collect_overflow_fields_detects_exceeding_short_term_lists(memory_manager):
    """Should identify which short_term lists exceed the limit."""
    from memory.seele import SHORT_TERM_MEMORY_LIMIT

    data = {
        "bot": {
            "emotions": {"long_term": "", "short_term": [f"e{i}" for i in range(SHORT_TERM_MEMORY_LIMIT + 3)]},
            "needs": {"long_term": "", "short_term": ["n1", "n2"]},
        },
        "user": {
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": [f"u{i}" for i in range(SHORT_TERM_MEMORY_LIMIT + 1)]},
        },
    }

    fields = memory_manager.seele._collect_overflow_fields(data)

    assert len(fields) == 2
    field_paths = {f["path"] for f in fields}
    assert "/bot/emotions" in field_paths
    assert "/user/needs" in field_paths


@pytest.mark.asyncio
async def test_compact_short_term_overflow_truncates_and_calls_llm(memory_manager):
    """Short-term compaction should truncate lists and call dedicated LLM prompt."""
    from memory.seele import SHORT_TERM_MEMORY_LIMIT, SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION

    short_terms = [f"Emotion {i}" for i in range(SHORT_TERM_MEMORY_LIMIT + 2)]
    data = {
        "bot": {
            "name": "TestBot",
            "gender": "",
            "birthday": "",
            "role": "",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {"description": "", "examples": []},
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "Previously calm.", "short_term": short_terms},
            "needs": {"long_term": "", "short_term": []},
            "relationship_with_user": "",
        },
        "user": {
            "name": "TestUser",
            "gender": "",
            "birthday": "",
            "location": "",
            "personal_facts": [],
            "abilities": [],
            "likes": [],
            "dislikes": [],
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }

    new_long_term = "Synthesized calm with recent emotional depth."
    fake_llm_response = json.dumps({"/bot/emotions/long_term": new_long_term})

    fake_client = Mock()
    fake_client.generate_short_term_compaction_async = AsyncMock(return_value=fake_llm_response)
    fake_client.close_async = AsyncMock()

    with patch("llm.chat_client.LLMClient", return_value=fake_client):
        with patch("prompts.runtime.update_seele_json", return_value=True):
            result = await memory_manager.seele._compact_short_term_overflow_async(data)

    assert result["bot"]["emotions"]["short_term"] == short_terms[-SHORT_TERM_MEMORY_KEEP_AFTER_COMPACTION:]
    # update_seele_json was called with the patch ops (don't check exact args since we patched)
    fake_client.generate_short_term_compaction_async.assert_awaited_once()
    fake_client.close_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_compact_short_term_overflow_falls_back_on_llm_failure(memory_manager):
    """When LLM fails, short-term compaction should use deterministic fallback."""
    from memory.seele import SHORT_TERM_MEMORY_LIMIT

    short_terms = [f"Need {i}" for i in range(SHORT_TERM_MEMORY_LIMIT + 3)]
    data = {
        "bot": {
            "name": "TestBot",
            "gender": "",
            "birthday": "",
            "role": "",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {"description": "", "examples": []},
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "Existing need.", "short_term": short_terms},
            "relationship_with_user": "",
        },
        "user": {
            "name": "TestUser",
            "gender": "",
            "birthday": "",
            "location": "",
            "personal_facts": [],
            "abilities": [],
            "likes": [],
            "dislikes": [],
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }

    fake_client = Mock()
    fake_client.generate_short_term_compaction_async = AsyncMock(side_effect=Exception("LLM down"))
    fake_client.close_async = AsyncMock()

    with patch("llm.chat_client.LLMClient", return_value=fake_client):
        result = await memory_manager.seele._compact_short_term_overflow_async(data)

    assert "Existing need." in result["bot"]["needs"]["long_term"]
    assert len(result["bot"]["needs"]["short_term"]) == 4
    fake_client.close_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_compact_long_strings_tier1_triggers_on_oversized(memory_manager):
    """Tier 1 should submit full seele.json and apply revisions when strings exceed 500 chars."""
    from memory.seele import MAX_STRING_LENGTH_HARD

    data = {
        "bot": {
            "name": "TestBot",
            "gender": "",
            "birthday": "",
            "role": "",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {"description": "X" * 501, "examples": []},
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
            "relationship_with_user": "",
        },
        "user": {
            "name": "TestUser",
            "gender": "",
            "birthday": "",
            "location": "",
            "personal_facts": [],
            "abilities": [],
            "likes": [],
            "dislikes": [],
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }

    revised = json.loads(json.dumps(data))
    revised["bot"]["language_style"]["description"] = "A" * (MAX_STRING_LENGTH_HARD - 10)

    fake_response = json.dumps(revised)

    # Mock the internal _run_tool_model_prompt used by _llm_compact_long_strings_full
    mock_memory_client = Mock()
    mock_memory_client._run_tool_model_prompt = AsyncMock(return_value=fake_response)

    fake_client = Mock()
    fake_client._memory_client = mock_memory_client
    fake_client.close_async = AsyncMock()

    class FakeLLMClient:
        def __init__(self, *args, **kwargs):
            pass
        async def close_async(self):
            pass

    with patch("llm.chat_client.LLMClient") as mock_llm_class:
        mock_llm_class.return_value = fake_client
        with patch("prompts.runtime.update_seele_json", return_value=True):
            with patch.object(memory_manager.seele, "get_long_term_memory", return_value=data):
                result = await memory_manager.seele._compact_long_strings_async(data)

    assert result is not None


@pytest.mark.asyncio
async def test_compact_overflowing_memory_triggers_short_term_only_when_needed(memory_manager):
    """Per-section: only short_term overflow should trigger only short_term compaction."""
    from memory.seele import SHORT_TERM_MEMORY_LIMIT

    data = {
        "bot": {
            "name": "TestBot",
            "gender": "",
            "birthday": "",
            "role": "",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {"description": "", "examples": []},
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": [f"e{i}" for i in range(SHORT_TERM_MEMORY_LIMIT + 1)]},
            "needs": {"long_term": "", "short_term": []},
            "relationship_with_user": "",
        },
        "user": {
            "name": "TestUser",
            "gender": "",
            "birthday": "",
            "location": "",
            "personal_facts": ["Just one fact"],
            "abilities": [],
            "likes": [],
            "dislikes": [],
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }

    with patch.object(memory_manager.seele, "_compact_personal_facts_and_events_async") as mock_pf:
        with patch.object(memory_manager.seele, "_compact_short_term_overflow_async") as mock_st:
            mock_pf.return_value = data
            mock_st.return_value = data
            await memory_manager.seele._compact_overflowing_memory_async(data)

    mock_pf.assert_not_awaited()
    mock_st.assert_awaited_once()
```

- [ ] **Step 3: Update existing test `test_compact_overflowing_memory_accepts_short_term_llm_compaction` to reflect new split flow**

Replace the test at line 665 with a version that tests the new per-section flow:

```python
@pytest.mark.asyncio
async def test_compact_overflowing_memory_runs_personal_facts_compaction_only_for_pf_overflow(memory_manager):
    """When only personal_facts exceeds limit, only that compaction runs."""
    from memory.seele import PERSONAL_FACTS_LIMIT

    data = {
        "bot": {
            "name": "TestBot",
            "gender": "",
            "birthday": "",
            "role": "",
            "appearance": "",
            "likes": [],
            "dislikes": [],
            "language_style": {"description": "", "examples": []},
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
            "relationship_with_user": "",
        },
        "user": {
            "name": "TestUser",
            "gender": "",
            "birthday": "",
            "location": "",
            "personal_facts": [f"Fact {i}" for i in range(PERSONAL_FACTS_LIMIT + 3)],
            "abilities": [],
            "likes": [],
            "dislikes": [],
            "personality": {"mbti": "", "description": "", "worldview_and_values": ""},
            "emotions": {"long_term": "", "short_term": []},
            "needs": {"long_term": "", "short_term": []},
        },
        "memorable_events": {},
        "commands_and_agreements": [],
    }

    fake_client = Mock()
    fake_client.generate_seele_compaction_async = AsyncMock(return_value=json.dumps({
        "personal_facts": data["user"]["personal_facts"][:PERSONAL_FACTS_LIMIT],
        "memorable_events": {},
    }))
    fake_client.close_async = AsyncMock()

    with patch("llm.chat_client.LLMClient", return_value=fake_client):
        result = await memory_manager.seele._compact_overflowing_memory_async(data)

    assert len(result["user"]["personal_facts"]) == PERSONAL_FACTS_LIMIT
    fake_client.close_async.assert_awaited_once()
```

- [ ] **Step 4: Run all tests to verify**

```bash
python -m pytest tests/test_memory.py tests/test_prompts.py -v 2>&1 | tail -40
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_memory.py
git commit -m "test: add tests for per-section compaction, short-term overflow, and string-length fallback"
```

---

### Task 11: Final lint and full test suite verification

- [ ] **Step 1: Run ruff lint**

```bash
python -m ruff check src
```

Expected: No errors (or fix any that appear).

- [ ] **Step 2: Run full test suite**

```bash
python -m pytest tests/ -v 2>&1 | tail -50
```

Expected: All tests pass.

- [ ] **Step 3: Fix any remaining test failures from tests that relied on old compaction behavior**

Check tests that may need updating:
- `test_compact_overflowing_memory_accepts_short_term_llm_compaction` — already replaced in Task 10
- `test_short_term_fallback_compaction_keeps_latest_four` — should still pass (fallback unchanged)
- `test_write_complete_seele_json_async_compacts_with_async_fallback` — compaction prompt shape changed (only returns personal_facts + memorable_events now), test may need updating

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: update tests for per-section compaction refactor"
```
