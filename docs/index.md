# docstore

**dbt for unstructured data. Extract once, query forever.**

Most tools re-read your documents every time you ask a question. **docstore** extracts the fields you care about once, caches them locally as JSON, and serves every subsequent query from the cache — no LLM calls, no re-reading, no waiting.

```
Run 1 (cold): 200 invoices → 400 LLM calls → ~$0.40
Run 2 (warm): 200 invoices → 0 LLM calls   → $0.00
Query:        "which invoices are unpaid?" → 0 LLM calls → <1s
```

## Why it exists

LLMs made it easy to extract structured data from documents. What they didn't provide is a layer that *persists* that extraction and *invalidates it automatically* when the source file changes. Most tools either re-read the raw documents on every query (expensive, slow), require a database or vector store (overkill), or store embeddings (wrong abstraction for structured extraction).

docstore treats structured extraction as a **cache over your unstructured data**. Same insight as dbt applied to SQL — you define the transformation once, the system manages the state.

## Three surfaces

- **CLI** — `docstore extract ./invoices/ --schema invoice_schema`. See [CLI reference](cli-reference.md).
- **Python API** — `from docstore import DocStore, ExtractionSchema`. Examples in [Getting started](getting-started.md).
- **MCP server** — Claude Desktop can call `extract`, `query`, `diff`, and `stats` directly.

## Cache invariants

The cache invalidates automatically when:

- the file content changes (file hash changes)
- the schema changes (schema version hash changes)
- a different schema is applied to the same file (different key)

## Limitations vs Lumient

docstore is a single-document extraction cache. It does **not**:

- compose records across documents (invoice + Stripe → reconciliation status)
- trigger automatically when files arrive
- maintain a queryable entity layer with lineage
- support multi-step workflow logic
- provide governance and audit trails for regulated industries

For cross-document composition and maintained operational records, see [Lumient](https://lumient.ai).

## Get going

1. [Install and run your first extraction](getting-started.md) — ~3 minutes.
2. [Read the CLI reference](cli-reference.md) — every command with examples.
