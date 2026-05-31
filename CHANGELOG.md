# Changelog

All notable changes are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses
[setuptools-scm](https://github.com/pypa/setuptools-scm) for versioning, so
release numbers come from git tags.

## [0.1.0] - UNRELEASED

Initial public version.

### Added

- **Multi-provider LLM support** via a `LLMClient` Protocol in `docstore/llm.py`.
  Choose between Anthropic (default), OpenAI, Groq, and Gemini at runtime —
  Groq and Gemini are driven through their OpenAI-compatible endpoints, so the
  three non-Anthropic providers share a single adapter (`OpenAIChatLLM`).
  All four providers are installed by default; pick one at runtime via
  `--provider` (or the `DOCSTORE_PROVIDER` env var). Each reads its own
  API key from the environment.
- **`docstore sync` command** — finds cache entries whose source file no longer
  exists on disk. `--yes` removes them; without it, the command reports stale
  entries without deleting.
- **`docstore ask "<question>"`** — compiles a natural-language question into a
  JSON filter AST via one LLM call, then evaluates against the cache with zero
  further LLM calls.
- **`docstore clean [--schema X] [--yes]`** for scoped cache deletion.
- **Read the Docs site** at `docstore.lumient.ai` (MkDocs + Material theme,
  `.readthedocs.yaml` + `mkdocs.yml`).
- **GitHub Actions CI** — `lint` (ruff), `tests` (pytest across
  `{ubuntu, macos} × {3.11, 3.12, 3.13}`), and `docs` (mkdocs build --strict).
- **AGENTS.md** documenting architectural invariants.
- **`scripts/generate_txt_invoices.py`** synthetic invoice corpus generator
  with idempotent filenames.

### Changed

- **Validator is opt-in** (`--validate`, default off). Cold extract is now one
  LLM call per file instead of two. The validator prompt is tightened to a
  closed list of failure modes and uses `temperature=0` for reproducibility.
- **PDF parser now fails loudly** when no extractable text is found.
  Previously returned an empty string (which silently produced garbage
  extractions). Scanned/image-only PDFs raise `ValueError` with a clear OCR
  note. **Breaking change** if any caller relied on the old empty-string
  behaviour.
- **Schema elicitation respects the `--schema` flag verbatim** and uses
  `temperature=0`, so the same English description always produces the same
  `SchemaDescriptor.version` across runs.
- **CLI cache co-location**: commands that take a path (`extract`, `diff`,
  `shell`) default to `<path>/.docstore` instead of `./.docstore` so the
  cache lives with the corpus.
- **`stats()` keys renamed** for honesty: `total_tokens_saved` →
  `total_tokens_cached`, `estimated_cost_saved_usd` →
  `estimated_cost_to_recompute_usd`. The cache stores LLM work absorbed once;
  per-query "saved" numbers can't be derived without hit tracking.
- **Project version** is now derived from git tags via setuptools-scm.

### Fixed

- **`docstore diff` could never find the previous extraction after a file
  changed** (the lookup was keyed on the *current* file hash). Now uses
  `DocStore.find_for_path` to look up by stored file path.
- **`docstore extract --schema X` on a cache miss produced empty extractions**
  because `ExtractionResult` didn't persist `schema_fields`. Now persisted;
  CLI and MCP server hydrate the descriptor from any cached entry.
- **MCP server `main()` was broken** — passed `stdio_server(server)` to
  `asyncio.run` instead of using `async with stdio_server() as (read, write)`.
  The server never actually worked end-to-end before this fix.
- **MCP server lazy-inits the Anthropic client** so importing the module
  doesn't require an API key.
- **Benchmark accounting** double-counted cached tokens, showing "13.9%
  saving" on a 100%-cache-hit run.
- **Generator filenames are idempotent** (`invoice_0001.txt` ...) and stale
  files are cleared before generation, so re-running with smaller `--count`
  doesn't leak orphans.