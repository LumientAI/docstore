# docstore

[![tests](https://github.com/LumientAI/docstore/actions/workflows/test.yml/badge.svg)](https://github.com/LumientAI/docstore/actions/workflows/test.yml)
[![lint](https://github.com/LumientAI/docstore/actions/workflows/lint.yml/badge.svg)](https://github.com/LumientAI/docstore/actions/workflows/lint.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue)](pyproject.toml)

**dbt for unstructured data. Extract once, query forever.**

Most tools re-read your documents every time you ask a question. docstore extracts the fields you care about once, caches them locally, and answers subsequent queries from the cache — no LLM calls, no re-reading, no waiting.

```
Run 1 (cold): 200 invoices → 400 LLM calls → ~$0.40
Run 2 (warm): 200 invoices → 0 LLM calls  → $0.00
Query:        "which invoices are unpaid?" → 0 LLM calls → <1s
```

---

## Why this exists

LLMs made it easy to extract structured data from documents. What they did not provide is a layer that *persists* that extraction and *invalidates it automatically* when the source file changes. Every existing tool either:

- Re-reads raw documents on every query (expensive, slow)
- Requires a database or vector store (complex, overkill for most teams)
- Stores embeddings for semantic search (wrong abstraction for structured extraction)

docstore treats structured extraction as a **cache over your unstructured data**. Same insight as dbt applied to SQL — you define the transformation once, the system manages the state.

---

## Benchmark

docstore ships with a reproducible public cache benchmark. It generates a
synthetic invoice corpus, writes `ground_truth.jsonl`, then measures:

- `cold_extract`: empty cache, every document calls the LLM once
- `warm_extract`: same corpus and schema, every document is served from cache
- `cached_query`: query stored JSON locally, with no parser or LLM calls

```bash
uv run python scripts/benchmark.py /tmp/docstore-benchmark --count 30
uv run python scripts/benchmark.py /tmp/docstore-benchmark --count 30 --output json
```

Use `--provider` and `--model` to run it against a specific vendor. The
benchmark is intended to show cache behavior, not provider quality.

---

## Installation

```bash
pip install docstore
```

Or from source:

```bash
git clone https://github.com/your-org/docstore
cd docstore
pip install -e ".[dev]"
```

---

## Quickstart

### Python API

```python
from docstore import DocStore, ExtractionSchema, create_llm_client

class InvoiceSchema(ExtractionSchema):
    vendor: str
    amount: float
    currency: str
    due_date: str
    paid: bool

from docstore.agents.orchestrator import run_directory

store = DocStore()
descriptor = InvoiceSchema.to_descriptor()
client = create_llm_client()  # defaults to Anthropic
results = run_directory("./invoices", descriptor, store, client)

# Query without any LLM calls
unpaid = store.query("InvoiceSchema", lambda r: r.data.get("paid") is False)
```

### CLI

```bash
# Extract — describe fields interactively
docstore shell ./invoices/

# Extract with a named schema
docstore extract ./invoices/ --schema invoice_schema

# Use OpenAI, Groq, or Gemini instead of the default Anthropic provider
docstore extract ./invoices/ --schema invoice_schema --provider openai
docstore extract ./invoices/ --schema invoice_schema --provider groq
docstore extract ./invoices/ --schema invoice_schema --provider gemini

# Override the default model for any provider
docstore extract ./invoices/ --schema invoice_schema --provider gemini --model gemini-2.5-pro

# Query stored results (no LLM)
docstore query invoice_schema --filter "paid=false"

# Ask in natural language — one LLM call compiles to a filter,
# results come from cache with no per-document re-reads
docstore ask "which unpaid invoices are over $5000?" --schema invoice_schema

# Diff a changed file
docstore diff ./invoices/acme_april.pdf --schema invoice_schema

# Stats
docstore stats
```

### MCP server (Claude Desktop)

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "docstore": {
      "command": "docstore-server",
      "env": {
        "DOCSTORE_DIR": "/path/to/your/.docstore",
        "DOCSTORE_PROVIDER": "anthropic",
        "ANTHROPIC_API_KEY": "your-key"
      }
    }
  }
}
```

Claude can then call `extract`, `query`, `diff`, and `stats` directly.

Supported providers are `anthropic` (default), `openai`, `groq`, and `gemini`.
Set `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, or `GEMINI_API_KEY`
for the provider you choose. Each provider has a default model, and you can
override it with `--model` on the CLI or `DOCSTORE_MODEL` for the MCP server.

---

## How it works

```
┌──────────────────────────────────────────────────────────────────┐
│                         docstore pipeline                        │
│                                                                  │
│  document.pdf                                                    │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────┐     cache hit?   ──────────────────────────────┐    │
│  │  Parser │  ─────────────►  .docstore/{hash}.json         │    │
│  └─────────┘     (no LLM)     ──────────────────────────────┘    │
│       │                                                          │
│       │ cache miss                                               │
│       ▼                                                          │
│  ┌───────────┐                                                   │
│  │ Extractor │  LLM call 1 — extract fields against schema       │
│  └───────────┘                                                   │
│       │                                                          │
│       ▼                                                          │
│  ┌───────────┐                                                   │
│  │ Validator │  LLM call 2 — verify plausibility                 │
│  └───────────┘                                                   │
│       │                                                          │
│       ▼                                                          │
│  .docstore/{file_hash}__{schema}__{version}.json                 │
└──────────────────────────────────────────────────────────────────┘
```

**Cache key:** `sha256(file_bytes)` + `schema_name` + `sha256(schema_fields)`

The cache invalidates automatically when:
- The file content changes (file hash changes)
- The schema changes (schema version changes)
- A different schema is applied to the same file (different key)

---

## Schema definition

Two ways to define a schema:

**1. Python class (recommended for code)**

```python
from docstore import ExtractionSchema

class ContractSchema(ExtractionSchema):
    parties: list
    start_date: str
    end_date: str
    obligations: list
    auto_renews: bool
```

**2. Natural language via CLI (recommended for ad-hoc use)**

```bash
docstore shell ./contracts/
# > vendor name, contract start date, expiry date, whether it auto-renews
```

The orchestrator normalises your description into a canonical schema and shows it to you before running.

---

## Supported file types

PDF, DOCX, TXT, MD, CSV, HTML, JSON

PDF support covers documents with embedded/selectable text. Scanned or
image-only PDFs need OCR, which docstore does not support yet.

---

## Limitations vs Lumient

docstore is a single-document extraction cache. It does not:

- Compose records across documents (invoice + Stripe → reconciliation status)
- Trigger automatically when files arrive
- Maintain a queryable entity layer with lineage
- Support multi-step workflow logic (validate, diff, generate)
- Provide governance and audit trails for regulated industries

For cross-document composition and maintained operational records, see [Lumient](https://lumient.ai).

---

## Development

```bash
pip install -e ".[dev]"
pytest tests/
```

---

## License

MIT
