# Memory Search Tool - Usage Examples

## Overview

The `search_memories` tool supports:

- FTS5 full-text keyword search
- Mixed-language n-gram fallback for CJK and mixed-script queries
- Boolean operators (`AND`, `OR`, `NOT`)
- Role filtering
- Time-range filtering
- Explicit `session_id` targeting
- Choosing whether to search `summaries`, `conversations`, or `all`

By default:

- `search_target="all"`
- the tool searches both summaries and conversations
- the current session is excluded unless `include_current_session=true`
- if the search scope includes the current session, the most recent `CONTEXT_WINDOW_KEEP_MIN` conversation messages are excluded to avoid returning messages already present in the current context window

## Basic Examples

### 1. Single Keyword
```python
search_memories(query="Anna")
```
Finds memories containing `Anna`.

### 1b. Bare Multiple Keywords
```python
search_memories(query="Anna 电影")
```
Bare multiple keywords are interpreted by SQLite FTS5. In practice, they usually behave like `AND`.
Prefer `Anna AND 电影` for clarity and predictability.

### 2. AND Operator
```python
search_memories(query="Anna AND 电影")
```
Finds memories containing both `Anna` and `电影`.

### 3. OR Operator
```python
search_memories(query="电影 OR 音乐")
```
Finds memories containing either `电影` or `音乐`.

### 4. NOT Operator
```python
search_memories(query="电影 NOT 恐怖")
```
Finds memories containing `电影` but not `恐怖`.

### 5. Exact Phrase
```python
search_memories(query='"Anna 喜欢"')
```
Finds the exact phrase `Anna 喜欢`.

## Complex Queries

### 6. Nested Boolean Logic
```python
search_memories(query="(电影 OR 音乐) AND Anna")
```

### 7. Multiple AND Conditions
```python
search_memories(query="Anna AND 电影 AND 排序")
```

### 8. Mixed Operators
```python
search_memories(query="Anna AND (电影 OR 音乐) NOT 恐怖")
```

### 8b. Mixed-Language Boolean Query
```python
search_memories(query="Reisekosten AND 東京")
```
Queries containing CJK text may automatically use the mixed-language n-gram fallback.
Boolean operators are still supported in that path.

### 8c. Natural-Language Query With Vector-Assisted Summary Fallback
```python
search_memories(query="上次我们讨论预算和旅行安排的时候", search_target="summaries")
```
For longer natural-language queries, sparse keyword summary matches may be supplemented by vector-retrieved summaries.
The final summary order now uses weighted fusion across keyword signals, vector similarity, and light recency.
This means a clearly stronger semantic match can outrank a weaker keyword-only hit, while exact/strong keyword hits still remain competitive.

## Filtering by Time / Role

### 9. Keywords + Time Period
```python
search_memories(
    query="Anna AND 电影",
    time_period="last_week"
)
```

### 10. Keywords + Role Filter
```python
search_memories(
    query="电影",
    role="user"
)
```

### 11. Keywords + Date Range
```python
search_memories(
    query="Anna OR 电影",
    start_date="2026-01-01",
    end_date="2026-01-15"
)
```

### 12. Filters Without Keywords
```python
search_memories(
    role="assistant",
    time_period="last_month"
)
```

### 13. Complex Query with Multiple Filters
```python
search_memories(
    query="(电影 OR 音乐) AND Anna NOT 恐怖",
    role="user",
    start_date="2026-01-01",
    end_date="2026-01-15",
    limit=20
)
```

## Session Filtering

### 14. Search a Specific Session
```python
search_memories(
    query="电影",
    session_id=42
)
```
Searches only session `42`.

### 14b. Browse a Specific Session Without Keywords (Recommended: Summaries First)
```python
search_memories(
    session_id=42,
    search_target="summaries"
)
```
Use this when you want a concise overview of what happened in one session, without requiring any keyword query.

### 14c. Browse Verbatim Messages in a Specific Session
```python
search_memories(
    session_id=42,
    search_target="conversations"
)
```
Use this only when you need detailed line-by-line conversation history from that session.

### 15. Search the Current Session Explicitly
```python
search_memories(
    query="咖啡",
    session_id=123
)
```
If `123` is the current session, the most recent `CONTEXT_WINDOW_KEEP_MIN` conversation messages are still excluded.

### 16. Include Current Session Without Pinning a Specific Session
```python
search_memories(
    query="项目计划",
    include_current_session=True
)
```
Allows current-session results, but still excludes the most recent context-window-sized conversation tail.

### 17. Search a Non-Current Session
```python
search_memories(
    query="搬家",
    session_id=88
)
```
If session `88` is not the current session, `CONTEXT_WINDOW_KEEP_MIN` exclusion does not apply.

## Search Target Selection

### 18. Search Both Summaries and Conversations (Default)
```python
search_memories(
    query="电影",
    search_target="all"
)
```

### 19. Search Only Summaries
```python
search_memories(
    query="电影",
    search_target="summaries"
)
```

### 20. Search Only Conversations
```python
search_memories(
    query="电影",
    search_target="conversations"
)
```

## Special FTS5 Features

### 21. Prefix Matching
```python
search_memories(query="电影*")
```
Matches `电影`, `电影院`, `电影节`, etc.

### 22. Column Specification (Rarely Needed)
```python
search_memories(query="text:Anna")
```

## Example Output Format

The tool returns plain text to the LLM.

### Summaries
```text
== Related Summaries ==
[2026-03-18 21:00:00 ~ 2026-03-18 21:15:00][session_id=42] 你和 Alice 讨论了电影《沙丘2》，她很在意氛围和配乐。
```

### Conversations
```text
== Related Conversations ==
[2026-03-18 21:03:14][session_id=42] Alice: 我上周看的那部电影其实后劲很大。
[2026-03-18 21:03:50][session_id=42] Seele: 是哪一部让你印象最深？
```

### Search Criteria Header
```text
Search criteria: keywords: '电影', session_id: 42, target: conversations
```

## Automatic Vector Recall Format

The automatic vector-based historical recall used during normal chat follows the same display style:

### Recalled Summaries
```text
[2026-03-18 21:00:00 ~ 2026-03-18 21:15:00][session_id=42] 你和 Alice 讨论了电影《沙丘2》，她很在意氛围和配乐。
```

### Recalled Conversations
```text
[2026-03-18 21:03:14][session_id=42] Alice: 我上周看的那部电影其实后劲很大。
```

## Common Use Cases

### Find discussions about a topic
```python
search_memories(query="机器学习 OR AI OR 人工智能")
```

### Find what the user said about something
```python
search_memories(
    query="Anna",
    role="user"
)
```

### Search only summaries for high-level memory
```python
search_memories(
    query="旅行",
    search_target="summaries"
)
```

### Search only one session
```python
search_memories(
    session_id=7,
    search_target="summaries"
)
```

### Search one session for a specific topic
```python
search_memories(
    query="预算",
    session_id=7,
    search_target="conversations"
)
```

### Find exact quotes
```python
search_memories(query='"那部电影叫什么"')
```

## Error Handling

The tool validates queries and provides helpful error messages for:

- unmatched quotes
- unmatched parentheses
- operators at the start/end of query
- invalid `search_target`
- invalid FTS5 syntax

Example:
```text
Invalid query syntax: Unmatched quotes in query

Valid examples:
- Anna AND 电影
- 电影 OR 音乐
- "exact phrase"
- (电影 OR 音乐) AND Anna
```

## Tips

1. **Case Sensitivity**: FTS5 is case-insensitive by default
2. **Operators**: Use uppercase `AND`, `OR`, `NOT`
3. **Parentheses**: Use them for grouping
4. **Quotes**: Use them for exact phrase matching
5. **Wildcards**: Use `*` for prefix matching
6. **Search Target**: Use `summaries` when you want concise high-level memory, `conversations` when you want verbatim history
7. **Session Filter**: Use `session_id` when you want deterministic scope
8. **Session Overview First**: If using only `session_id` without keywords, prefer `search_target="summaries"` first, then switch to `conversations` if you need details

## Performance Notes

- FTS5 indexing makes keyword search fast
- Boolean queries remain efficient
- Time and role filters are applied in SQL
- By default, the current session is excluded
- If the current session is included in scope, recent context-window-sized conversation messages are excluded to reduce redundancy
