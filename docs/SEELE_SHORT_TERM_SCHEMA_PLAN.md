# seele.json Short-Term Emotion/Needs Schema Plan

## Goal

Migrate short-term `emotions` and `needs` from strings to append-only string
lists. Each list can grow to 12 items; once it exceeds 12, compaction merges old
items into the matching long-term field and keeps the latest 4 short-term items.

## Progress

- [x] Define implementation plan and limits.
- [x] Add regression tests for migration, validation, compaction, prompts, and system prompt formatting.
- [x] Update template and built-in fallback schema.
- [x] Implement normalization, validation, and compaction behavior.
- [x] Update memory update, complete JSON, repair, and compaction prompts.
- [x] Run focused tests and record results.

## Verification

- `.venv\Scripts\python.exe -m pytest tests\test_memory.py tests\test_prompts.py tests\test_prompts_system.py` -> 75 passed.
- `.venv\Scripts\python.exe -m pytest tests` -> 642 passed.
- `.venv\Scripts\python.exe -m ruff check src tests` -> passed.

## Decisions

- `short_term` uses `list[str]`; `long_term` remains `str`.
- LLM-generated JSON Patch should append short-term entries with `add` to `/-`.
- Complete JSON writes, schema repair, and compaction may rewrite complete objects
  to keep persisted memory valid.
