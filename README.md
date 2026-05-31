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

Over a corpus of 200 documents queried 3 times:

| Scenario | Baseline tokens | docstore tokens | Saving |
|---|---|---|---|
| First extraction | 180,000 | 180,000 | 0% |
| Second query, no changes | 180,000 | 0 | 100% |
| Monthly run, 12 new files | 180,000 | 10,800 | 94% |
| Single question over corpus | 180,000 | ~500 | 99.7% |

Run the benchmark yourself: `python scripts/benchmark.py ./your_documents --runs 3`

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
from docstore import DocStore, ExtractionSchema

class InvoiceSchema(ExtractionSchema):
    vendor: str
    amount: float
    currency: str
    due_date: str
    paid: bool

from docstore.agents.orchestrator import run_directory
import anthropic

store = DocStore()
descriptor = InvoiceSchema.to_descriptor()
results = run_directory("./invoices", descriptor, store, anthropic.Anthropic())

# Query without any LLM calls
unpaid = store.query("InvoiceSchema", lambda r: r.data.get("paid") is False)
```

### CLI

```bash
# Extract — describe fields interactively
docstore shell ./invoices/

# Extract with a named schema
docstore extract ./invoices/ --schema invoice_schema

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
        "ANTHROPIC_API_KEY": "your-key"
      }
    }
  }
}
```

Claude can then call `extract`, `query`, `diff`, and `stats` directly.

---

## How it works

```
┌─────────────────────────────────────────────────────────────────┐
│                         docstore pipeline                        │
│                                                                  │
│  document.pdf                                                    │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────┐     cache hit?  ──────────────────────────────┐    │
│  │  Parser  │  ─────────────►  .docstore/{hash}.json        │    │
│  └─────────┘     (no LLM)   ──────────────────────────────┘    │
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
└─────────────────────────────────────────────────────────────────┘
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
