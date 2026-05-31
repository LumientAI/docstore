# Getting started

Install, configure, and run your first cached extraction. ~3 minutes.

## Install

=== "pip"

    ```bash
    pip install lumient-docstore
    ```

=== "From source"

    ```bash
    git clone https://github.com/LumientAI/docstore
    cd docstore
    pip install -e ".[dev]"   # or: uv sync --all-extras
    ```

## Configure

You need an Anthropic API key. Copy `.env.example` to `.env` and add yours:

```bash
cp .env.example .env
# edit .env, paste your key from https://console.anthropic.com/settings/keys
```

Entry points (`docstore`, `docstore-server`, the example, the benchmark) load `.env` automatically.

## Generate a sample corpus

If you don't have documents on hand, the repo includes a synthetic invoice generator:

```bash
python scripts/generate_txt_invoices.py ./sample_invoices --count 30
```

That writes 30 plain-text invoices to `sample_invoices/`, varied across 20 vendors, 3 currencies, and ~35% unpaid status.

## First extraction

```bash
docstore extract sample_invoices/ --schema invoice_schema --ask
```

`--ask` prompts you to describe the fields in plain English. Paste:

```
vendor name, total amount, currency, due date, whether it has been paid, line items
```

What happens under the hood:

1. The orchestrator normalises your description into a schema with `snake_case` field names.
2. Each `.txt` file is parsed (no LLM) and sent to the extractor (one Haiku call per file).
3. Results land at `sample_invoices/.docstore/{file_hash}__invoice_schema__{version}.json`.

For 30 invoices this takes ~110s and costs ~$0.04. **Re-running the same command** is instant — every file is a cache hit.

## Query the cache without LLM calls

```bash
docstore query invoice_schema --filter "is_paid=false" --store sample_invoices/.docstore
```

You should see roughly 10 unpaid invoices in a clean table. **Zero LLM calls** — every result comes from the cached JSON.

## Ask in natural language

```bash
docstore ask "which unpaid invoices over \$5000?" \
  --schema invoice_schema --store sample_invoices/.docstore
```

One LLM call compiles your question into a filter, then the filter runs against the cache:

```
Filter: is_paid = False AND total_amount > 5000
invoice_schema — 1 records
| file | vendor_name | total_amount | currency | ... |
```

## Diff a changed document

Open one invoice in your editor, change `Status: UNPAID` to `Status: PAID`, save, then:

```bash
docstore diff sample_invoices/001_*.txt \
  --schema invoice_schema --store sample_invoices/.docstore
```

You'll see a clean field-by-field diff between the cached version and the current file. One LLM call (for the re-extraction); the previous version is read from cache.

## Inspect cache state

```bash
docstore stats --store sample_invoices/.docstore
docstore schemas --store sample_invoices/.docstore
```

## Sync stale entries

If you move or delete source files after extracting them, their cache entries become stale — they'll still appear in `query` results even though the files are gone. Remove them with:

```bash
docstore sync --store sample_invoices/.docstore        # dry run, reports stale paths
docstore sync --store sample_invoices/.docstore --yes  # delete stale entries
```

## Clean up

Wipe the cache for one schema, or everything:

```bash
docstore clean --store sample_invoices/.docstore --schema invoice_schema
docstore clean --store sample_invoices/.docstore --yes
```

## Next steps

- The full [CLI reference](cli-reference.md) covers every command and flag.
- The Python API mirrors the CLI — `from docstore import DocStore, ExtractionSchema`.
- For Claude Desktop integration, add `docstore-server` to `claude_desktop_config.json` (see the README).
