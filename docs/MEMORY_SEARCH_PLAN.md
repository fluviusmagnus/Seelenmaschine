# Memory Search Upgrade Plan

## Goals

- Preserve the existing SQLite FTS5 search path for queries that already work well.
- Add a mixed-language n-gram fallback for Chinese, Japanese, and mixed-script queries.
- Keep the existing `search_memories(...)` tool API stable.
- Leave room for later vector-assisted recall, weighted fusion, and optional rerank.

## Design Summary

The upgraded design uses multiple retrieval layers rather than replacing the current search stack outright:

1. **FTS5 path** for existing boolean / phrase / prefix queries, especially for Latin-script languages.
2. **Mixed-language n-gram path** for CJK and mixed-script keyword lookup.
3. **Future vector-assisted recall** as a supplemental recall stage, not a replacement for keyword search.
4. **Future optional rerank** after coarse retrieval and filtering.

## Why Keep FTS5

FTS5 is still useful for:

- explicit `AND` / `OR` / `NOT` queries
- phrase search with quotes
- prefix search such as `foo*`
- existing English-centric behavior

Removing it immediately would increase migration risk and regress features that already work.

## Why Add n-gram

The current FTS tables use default tokenization and are weak for CJK and mixed-script text. The new n-gram layer improves:

- Chinese and Japanese substring matching
- mixed-language queries such as `Reisekosten AND 東京`
- names, product identifiers, and newly coined terms

### Indexing Strategy

- CJK runs are indexed as **bigrams**.
- Non-CJK alphanumeric runs are indexed as normalized whole tokens.
- Index data is stored in:
  - `conversation_ngrams`
  - `summary_ngrams`

## Query Routing Strategy

### FTS-first

Use the existing FTS path when the query is primarily FTS-like and Latin-script-friendly.

### n-gram fallback

Use the n-gram path when the query contains CJK characters or mixed-script terms that are likely to perform poorly with default FTS tokenization.

## Boolean Support in n-gram Path

The n-gram route supports boolean logic by parsing the query in application code and compiling it to SQL conditions.

Supported operators for the fallback path:

- `AND`
- `OR`
- `NOT`
- parentheses

Each term is converted into one or more n-gram / normalized token conditions and then compiled into `EXISTS`-based SQL.

## Migration Plan

### Schema version

- Upgrade schema version from `3.2` to `3.3`.

### Migration tasks

1. Create `conversation_ngrams` and `summary_ngrams` tables.
2. Backfill index rows from existing `conversations` and `summaries`.
3. Keep FTS5 tables intact.

## Write-path Maintenance

When inserting conversations or summaries:

- continue maintaining vector rows if embeddings are provided
- continue using existing FTS triggers
- refresh n-gram rows in Python for the inserted content

## Ranking Strategy

### Phase 1

- FTS results: existing FTS ordering
- n-gram results: recency-first ordering

### Phase 2A (implemented)

- minimal vector-assisted recall now supplements sparse summary keyword results for longer natural-language queries
- vector recall is appended conservatively and does not override explicit boolean filtering behavior
- a simple coarse ranking step now keeps stronger keyword summary hits ahead of weaker fallback-only vector additions

### Phase 2 (implemented)

- summary retrieval now uses a weighted fusion stage across keyword-origin, token coverage, exact substring match, vector similarity, and light recency
- vector fallback now fetches a slightly broader candidate set and trims only after fusion ranking
- this allows strong semantic matches to outrank weaker keyword-only hits while still preserving transparent keyword signals in the score

### Phase 3 (implemented for summaries)

- summary retrieval can now optionally call the configured reranker on a small coarse candidate set after weighted fusion
- rerank is best-effort and automatically falls back to fused ordering when no reranker is configured or the rerank call fails
- current scope is summary candidates only; conversations can be added later if needed

## Testing Plan

Add or update tests for:

- schema initialization / migration to `3.3`
- n-gram backfill and maintenance on insert
- Chinese substring search
- mixed-language boolean queries
- preservation of current FTS behavior

## Out of Scope for This Iteration

- vector-assisted merge in the keyword tool path
- language-specific stemming / lemmatization for Western languages

Completed in this iteration:

- weighted score fusion for summary ranking
- optional rerank integration for summary candidates

These remain explicitly planned future enhancements rather than part of the initial implementation.