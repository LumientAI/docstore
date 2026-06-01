# Changelog

All notable changes are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses
[setuptools-scm](https://github.com/pypa/setuptools-scm) for versioning, so
release numbers come from git tags.

## [Unreleased]

### Added

- **Aggregation on `docstore query`** — `--group-by`, `--count`, `--sum`, and `--avg` flags for in-cache aggregation with zero LLM calls. Non-numeric values are skipped with a warning.

## [0.1.0] - 2026-05-31

Initial public release.

### Core

- **File-based extraction cache.** Run an extraction once, get the result as
  JSON in a `.docstore/` directory; subsequent reads of the same file under
  the same schema return from cache with zero LLM calls. Cache key is
  `sha256(file_bytes)[:16] + schema_name + sha256(fields)[:12]`, so the cache
  invalidates automatically when either the file content or the schema changes.
- **Schema definition, two ways.** Subclass `ExtractionSchema` for code-driven
  schemas, or pass `--ask` to describe fields in plain English; the orchestrator
  normalises the description into a canonical `SchemaDescriptor` with
  `temperature=0` so the same input always produces the same schema version.

### Multi-provider LLM support

- **Anthropic (default), OpenAI, Groq, Gemini** via a `LLMClient` Protocol in
  `docstore/llm.py`. Groq and Gemini are driven through their
  OpenAI-compatible endpoints, so the three non-Anthropic providers share one
  adapter. Pick at runtime with `--provider` or `DOCSTORE_PROVIDER`. Each
  provider reads its own `*_API_KEY` from the environment.
- **All four providers installed by default** — no extras to remember.

### Three surfaces

- **CLI** (`docstore`): `extract`, `query`, `ask`, `diff`, `schemas`, `stats`,
  `clean`, `sync`, `shell`. CLI commands that take a path co-locate the cache
  with the corpus (`<path>/.docstore`).
- **Python API**: `from docstore import DocStore, ExtractionSchema,
  create_llm_client`. Mirrors the CLI surface.
- **MCP server** (`docstore-server`): exposes `extract`, `query`, `diff`,
  `stats` as MCP tools for Claude Desktop. Lazy-inits the LLM client so
  importing the module doesn't require an API key.

### Natural-language queries

- **`docstore ask "<question>" --schema X`** compiles English to a JSON filter
  AST via one LLM call, then evaluates against cached results with zero
  further LLM calls. Filter operators: `=`, `!=`, `>`, `<`, `>=`, `<=`,
  `contains`, `in`, `is_null`, plus compound `and` / `or` / `not`. The
  compiler is anchored to the actual schema fields so the LLM can't
  hallucinate column names.

### Supported file types

- PDF (text-based; scanned/image-only PDFs raise a clear OCR-not-supported
  error), DOCX, TXT, MD, CSV, HTML, JSON.

### Operational tooling

- **`docstore sync`** removes cache entries whose source file no longer
  exists. Dry-run by default; `--yes` deletes.
- **`docstore clean [--schema X] [--yes]`** for scoped cache wipes.
- **Validator is opt-in** via `--validate`. Cold extraction is one LLM call
  per file by default; `--validate` adds a second LLM call that checks
  plausibility against a closed list of failure modes.
- **`scripts/generate_txt_invoices.py`** synthetic invoice corpus generator
  for benchmarking and demos. Idempotent filenames.
- **`scripts/benchmark.py`** measures cold/warm/cached-query token spend
  across providers.

### Documentation and tooling

- **Documentation site** at https://docstore.lumient.ai (MkDocs + Material).
- **`AGENTS.md`** documents architectural invariants that aren't visible
  from the code alone (cache key shape, `schema_fields` persistence,
  validator opt-in rationale, cross-provider determinism caveats).
- **GitHub Actions CI**: `lint` (ruff), `tests` (pytest across
  `{ubuntu, macos} × {3.11, 3.12, 3.13}`), and `docs` (`mkdocs build --strict`).
- **Dynamic versioning** via setuptools-scm reading git tags.