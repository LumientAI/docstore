---
name: docstore
description: Use when working with docstore document extraction caches, MCP tools, invoice/contract/document schemas, cache-aware multi-file questions, or benchmarks comparing direct LLM rereads against cached structured queries.
---

# docstore

Use docstore as a structured extraction cache for local documents. The core
workflow is: extract fields once, persist typed JSON, then answer repeated
questions from the cache instead of rereading raw files.

## Workflow

1. Check cache state first.
   - Prefer `docstore stats` or the MCP `stats` tool.
   - Use `docstore schemas` or MCP `query` when the needed schema likely exists.
2. Query before rereading documents.
   - For repeated structured questions, prefer `docstore query <schema>`.
   - Do not inspect every raw document unless the cache is missing, stale, or the user asks for source-level verification.
3. Extract only when needed.
   - Use a stable schema name and field set so the schema version remains reusable.
   - For directories, let docstore co-locate cache at `<path>/.docstore` unless the user gives `--store`.
   - Keep validation opt-in; use `--validate` only when the user asks for extra LLM verification.
4. Diff changed files instead of reprocessing everything.
   - Use `docstore diff <file> --schema <schema>` when the question is about what changed.
5. Benchmark architecture, not provider quality.
   - Use `scripts/benchmark.py` to compare `direct_context_query`, `cold_extract`, `warm_extract`, and `cached_query`.
   - Use `--skip-direct-baseline` when avoiding extra LLM spend.

## Common Commands

```bash
uv run python scripts/generate_txt_invoices.py /tmp/docstore-invoices --count 30
uv run python scripts/benchmark.py /tmp/docstore-invoices --count 30 --output json
uv run python scripts/benchmark.py /tmp/docstore-invoices --count 30 --skip-direct-baseline

docstore extract ./invoices --schema invoice_benchmark --ask
docstore query invoice_benchmark --filter "paid=false" --store ./invoices/.docstore
docstore diff ./invoices/acme_april.pdf --schema invoice_benchmark
docstore stats --store ./invoices/.docstore
```

## MCP Agent Behavior

When docstore is available as an MCP server:

- Call `stats` before deciding whether raw document reads are needed.
- Call `query` for grounded answers from existing extractions.
- Call `extract` only for files or schemas that are missing.
- Call `diff` for changed-document questions.
- Tell the user when a cold extraction will make provider API calls.

Good agent prompt:

```text
Use docstore. Check stats first. If invoice_benchmark exists, query paid=false
and summarize unpaid invoices. Only extract raw invoice files if the cache is
missing.
```

## Invariants

- Do not change cache key shape: `{file_hash[:16]}__{schema_name}__{schema_version[:12]}.json`.
- Anything writing cache entries must populate `ExtractionResult.schema_fields`.
- Schema versions are derived from sorted schema fields; avoid casual field renames.
- New CLI commands that take a path should use the repo's store co-location convention.
