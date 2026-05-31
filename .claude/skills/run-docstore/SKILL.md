---
name: run-docstore
description: Use the docstore MCP tools to extract structured fields from documents and query the cache. Use when asked to extract, query, or analyse documents with docstore.
---

docstore extracts structured fields from documents once and caches by `sha256(file) + schema + schema_version`. `query` is always free; `extract` costs tokens only on a cache miss.

## Decision order

1. **`stats`** — understand what's already cached.
2. **`query`** an existing schema — zero LLM calls, instant. Inspect the result keys to see what fields are cached (see below).
3. **`extract`** only when you need a schema or file not yet in the cache. Match the cached field set exactly or you'll get a full cache miss.

## Reading the cached field set

The keys in a `query` result (excluding `file`) are the exact field names in that schema version. Use this to understand what's already cached before deciding to extract:

```python
results = mcp__docstore__query(schema_name="vendor_invoice")
# e.g. results[0] = {"file": "...", "vendor": "...", "amount_due": 96.43, "due_date": "...", "paid": false}
# → cached fields are: vendor, amount_due, due_date, paid
```

If you need a field that isn't in the result, you must extract with an updated `fields` dict — but that creates a new cache version, so **all files** need to be re-extracted. Define the broadest field set you'll ever need on the first extraction.

## Extract

Always supply `fields` explicitly. Match the cached field set exactly to get hits; any addition or removal produces a new schema version and misses for every file.

```python
mcp__docstore__extract(
    file_path="/absolute/path/to/file.pdf",   # must be absolute
    schema_name="vendor_invoice",
    fields={"vendor": "str", "amount_due": "float", "due_date": "str", "paid": "bool"}
)
# Returns: {data, valid, cache_hit, tokens_used, tokens_saved, validation_issues}
```

## Query

```python
mcp__docstore__query(schema_name="vendor_invoice")
mcp__docstore__query(schema_name="vendor_invoice", filter="paid=false")
# filter supports: field=value, field!=value
```

## Sync

Remove cache entries whose source file no longer exists on disk:

```python
mcp__docstore__sync()               # dry run — reports stale paths, deletes nothing
mcp__docstore__sync(delete=True)    # removes stale entries
```

Run this if `query` returns results for files you know have been deleted.

## Gotchas

**File paths must be absolute.** Relative paths return "File not found".

**Schema naming is the cache namespace.** A different `schema_name` each time defeats caching entirely.

**Changing `fields` busts the cache for all files.** Even with the same `schema_name`, a different set of fields produces a new schema version — every document is a cache miss. Read the cached field set from `query` first; if the fields you need are already there, reuse them exactly.

**"Predates field persistence" error.** Old cache entries lack field metadata. Fix: always pass `fields` explicitly rather than relying on `schema_name` alone to hydrate the descriptor.

**`query` filter is equality-only.** `paid=false`, `vendor=Acme`. No ranges, no aggregations. Pull results with `query` and reduce in-context for anything more complex.
