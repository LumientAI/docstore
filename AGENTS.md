# AGENTS.md

Guidance for AI coding agents (and humans) working on this repo. Covers dev
commands, the bits of architecture that aren't obvious from skimming, and the
invariants that quietly break things if you violate them.

## Dev commands

```bash
uv sync --all-extras        # install runtime + dev deps from uv.lock
uv run pytest               # run the test suite (29 tests, no LLM calls)
uv run ruff check .         # lint
cp .env.example .env        # then add ANTHROPIC_API_KEY
```

Sample corpus + end-to-end run:

```bash
python scripts/generate_txt_invoices.py ./sample_invoices --count 30
docstore extract sample_invoices/ --schema invoice_schema --ask
docstore query invoice_schema --filter "is_paid=false" --store sample_invoices/.docstore
```

## Architecture

```
docstore/
  schema.py        SchemaDescriptor (frozen pydantic, version = sha256(fields)[:12])
                   ExtractionResult (persists schema_fields — see invariants)
  store.py         File-based cache. Key shape: {file_hash}__{schema}__{version}.json
                   find_for_path() looks up by stored file_path, not current hash
  cli.py           Typer CLI: extract, query, diff, schemas, stats, clean, shell
  server.py        MCP server exposing extract, query, diff, stats
  agents/
    parser.py        file -> text (no LLM)
    extractor.py     text + schema -> JSON (1 LLM call)
    validator.py     extracted data -> {valid, issues} (1 LLM call, opt-in)
    differ.py        previous vs current -> changed_fields + summary
    orchestrator.py  coordinates the pipeline; elicits schemas from natural language
```

## Invariants — don't break these

- **Cache key shape:** `{file_hash[:16]}__{schema_name}__{schema_version[:12]}.json`.
  `store.list_schemas()` parses filenames with `split("__")` and expects exactly 3
  parts. Changing the delimiter or part count breaks every read path.
- **`ExtractionResult.schema_fields` must be populated** by anything that writes to
  the cache. It's how `docstore diff` and `docstore extract --schema X` rebuild a
  full `SchemaDescriptor` after a cache miss. Empty fields = empty prompt to the
  extractor = silent garbage data.
- **`SchemaDescriptor.version`** is `sha256(json.dumps(fields, sort_keys=True))[:12]`.
  Don't change the hashing — existing caches become unreachable by name lookup.
- **Cache co-location:** CLI commands that take a path default `--store` to
  `<path>/.docstore`. The benchmark and Python example do the same. If you add a
  new command that takes a path, use `_resolve_store_for_path` so the convention
  stays consistent.

## Things that look wrong but are intentional

- **`load_dotenv()` runs before module-level imports** in cli.py, server.py,
  benchmark.py, invoice_example.py. Ruff E402 is ignored for these files in
  `pyproject.toml`. The pattern is required because some imported modules
  instantiate clients at import time.
- **Validator is opt-in (`--validate`), default off.** Reasons: it doubles
  cold-extract cost, and on clean data it produces ~20% false positives
  (overthinks math reconciliation, nested object shapes, formatting). Don't
  make it mandatory. If you tighten the prompt or add deterministic verification,
  the opt-in default can stay.
- **`temperature=0` on schema elicitation** (`elicit_schema`, `_infer_schema_name`).
  Without it, the same English input produces different field name normalisations
  across runs, which produces different version hashes, which orphans cached
  entries by name lookup.
- **MCP server lazy-inits the Anthropic client.** `_get_client()` instead of a
  module-level instance. Importing the module shouldn't crash without an API key
  — embedders rely on this.
- **`MODEL = "claude-haiku-4-5-20251001"` hardcoded** in each agent module.
  Cost-predictable for the demo. If changing, also update the README's cost
  estimates and `HAIKU_BLENDED_USD_PER_MTOK` in `scripts/benchmark.py`.

## Conventions

- Prefer editing existing files over creating new ones. The architecture is small
  on purpose — match it.
- No comments explaining what code does. Only comments for *why* something
  non-obvious is the way it is.
- New CLI commands take `--store` with a sensible default and use the
  `_resolve_store_for_path` helper.
- Tests live in `tests/`. Store and schema tests don't call the LLM. If you add
  a test that does, mark it (no convention yet — propose one when you need it).
