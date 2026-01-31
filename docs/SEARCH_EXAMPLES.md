# Memory Search Tool - Usage Examples

## FTS5 Boolean Operators

The `search_memories` tool supports FTS5 full-text search with boolean operators for complex queries.

## Basic Examples

### 1. Single Keyword
```python
search_memories(query="Anna")
```
Finds all memories containing "Anna"

### 2. AND Operator (Both keywords must appear)
```python
search_memories(query="Anna AND 电影")
```
Finds memories containing both "Anna" AND "电影"

### 3. OR Operator (Either keyword)
```python
search_memories(query="电影 OR 音乐")
```
Finds memories containing "电影" OR "音乐" (or both)

### 4. NOT Operator (Exclusion)
```python
search_memories(query="电影 NOT 恐怖")
```
Finds memories containing "电影" but NOT "恐怖"

### 5. Exact Phrase
```python
search_memories(query='"Anna 喜欢"')
```
Finds the exact phrase "Anna 喜欢" (words in that order)

## Complex Queries

### 6. Nested Boolean Logic
```python
search_memories(query="(电影 OR 音乐) AND Anna")
```
Finds memories where Anna is mentioned together with either 电影 or 音乐

### 7. Multiple AND Conditions
```python
search_memories(query="Anna AND 电影 AND 排序")
```
All three keywords must appear

### 8. Mixed Operators
```python
search_memories(query="Anna AND (电影 OR 音乐) NOT 恐怖")
```
Complex: Anna must appear, either 电影 or 音乐 must appear, but 恐怖 must not appear

## Combining with Filters

### 9. Keywords + Time Period
```python
search_memories(
    query="Anna AND 电影",
    time_period="last_week"
)
```
Find memories from last week containing both keywords

### 10. Keywords + Role Filter
```python
search_memories(
    query="电影",
    role="user"
)
```
Find only user messages containing "电影"

### 11. Keywords + Date Range
```python
search_memories(
    query="Anna OR 电影",
    start_date="2026-01-01",
    end_date="2026-01-15"
)
```
Find memories in date range with either keyword

### 12. Multiple Filters (No Keywords)
```python
search_memories(
    role="assistant",
    time_period="last_month"
)
```
Find all assistant messages from last month

### 13. Complex Query with All Filters
```python
search_memories(
    query="(电影 OR 音乐) AND Anna NOT 恐怖",
    role="user",
    start_date="2026-01-01",
    end_date="2026-01-15",
    limit=20
)
```

## Special FTS5 Features

### 14. Prefix Matching
```python
search_memories(query="电影*")
```
Matches: 电影, 电影院, 电影节, etc.

### 15. Column Specification (if needed)
```python
# Not commonly needed, but FTS5 supports it
search_memories(query="text:Anna")
```

## Common Use Cases

### Find discussions about a specific topic
```python
search_memories(query="机器学习 OR AI OR 人工智能")
```

### Find what user said about something
```python
search_memories(
    query="Anna",
    role="user"
)
```

### Find recent conversations
```python
search_memories(
    time_period="last_day"
)
```

### Find exact quotes
```python
search_memories(query='"那部电影叫什么"')
```

## Error Handling

The tool validates queries and provides helpful error messages for:
- Unmatched quotes
- Unmatched parentheses
- Operators at start/end of query
- Invalid FTS5 syntax

Example error:
```
Invalid query syntax: Unmatched quotes in query

Valid examples:
- Anna AND 电影
- 电影 OR 音乐
- "exact phrase"
- (电影 OR 音乐) AND Anna
```

## Tips

1. **Case Sensitivity**: FTS5 is case-insensitive by default
2. **Operators**: Must be uppercase (AND, OR, NOT)
3. **Parentheses**: Use for grouping complex queries
4. **Quotes**: Use for exact phrase matching
5. **Wildcards**: Use `*` for prefix matching
6. **Combine Filters**: Mix keywords with time/role filters for precise results

## Performance Notes

- FTS5 index makes keyword search very fast
- Complex boolean queries are still efficient
- Time and role filters are applied in SQL for optimal performance
- Results automatically exclude the current session
