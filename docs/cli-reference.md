# CLI reference

Every `docstore` command, its flags, and a concrete example. Run `docstore <command> --help` to see the same options in your terminal.

## Conventions

- **`--store`** controls the cache directory. Commands that take a path argument (`extract`, `diff`, `shell`) default to `<path>/.docstore` so the cache lives with the corpus. Path-less commands (`query`, `schemas`, `stats`, `clean`, `ask`) default to `./.docstore` in the current directory - pass `--store` explicitly when querying a corpus directory.
- **`--schema`** identifies a schema by name. If the name doesn't exist in the store and `--ask` is set (or no schema is given), the orchestrator elicits one from your description.
- **`--provider`** picks the LLM provider - `anthropic` (default), `openai`, `groq`, or `gemini`. Falls back to the `DOCSTORE_PROVIDER` env var if unset. All four providers are installed by default; you just need the corresponding API key in your environment.
- **`--model`** picks the model within that provider. Each provider has a sensible default (`claude-haiku-4-5-20251001`, `gpt-5.4-mini`, `llama-3.3-70b-versatile`, `gemini-2.5-flash`). Falls back to `DOCSTORE_MODEL` if unset.

Each provider reads its own API key from the environment: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`.

**Caveat - caches don't cross providers.** Schema elicitation is provider-deterministic but not cross-provider-deterministic, so the same English description compiled by different providers may produce different `schema_version` hashes. Treat caches as per-provider.

---

## `extract`

Extract structured fields from a file or directory. Cache hits return instantly; misses run the pipeline and persist.

```bash
docstore extract <path> [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--schema`, `-s` | none | Reuse a stored schema by name. Without it, you'll be prompted for fields. |
| `--ask` | `false` | Describe fields interactively even if a name is given. |
| `--validate` | `false` | Add a second LLM call per file to validate plausibility. Doubles cold-extract cost. |
| `--store` | `<path>/.docstore` | Cache directory. |
| `--provider` | `anthropic` (or `$DOCSTORE_PROVIDER`) | `anthropic` / `openai` / `groq` / `gemini`. |
| `--model` | provider default | Model within the chosen provider. |

```bash
# First extraction - define a schema in plain English
docstore extract ./invoices/ --schema invoice_schema --ask

# Incremental: reuse the stored schema, only new files hit the LLM
docstore extract ./invoices/ --schema invoice_schema

# With validation (opt-in, doubles cost)
docstore extract ./invoices/ --schema invoice_schema --validate

# Use a different provider (set the matching API key in .env first)
docstore extract ./invoices/ --schema invoice_schema --provider openai
docstore extract ./invoices/ --schema invoice_schema --provider groq --model llama-3.3-70b-versatile
```

---

## `query`

Run a filter against cached results. **Zero LLM calls.**

```bash
docstore query <schema> [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--filter`, `-f` | none | Single comparison expression. Operators: `=`, `!=`. |
| `--output`, `-o` | `table` | `table` or `json`. |
| `--store` | `.docstore` | Cache directory (pass explicitly for corpus-local caches). |

```bash
docstore query invoice_schema --filter "is_paid=false" --store ./invoices/.docstore
docstore query invoice_schema --output json --store ./invoices/.docstore
```

For richer expressions (`>`, `<`, `AND`, `OR`), use [`docstore ask`](#ask).

---

## `ask`

Compile a natural-language question into a filter via one LLM call, then evaluate against the cache.

```bash
docstore ask "<question>" --schema <name> [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--schema`, `-s` | **required** | The cached schema to query. |
| `--output`, `-o` | `table` | `table` or `json`. |
| `--store` | `.docstore` | Cache directory. |
| `--model` | `claude-haiku-4-5-20251001` | Model used to compile the question. |

```bash
docstore ask "which unpaid invoices over \$5000?" \
  --schema invoice_schema --store ./invoices/.docstore

docstore ask "show EUR invoices from Q1" \
  --schema invoice_schema --store ./invoices/.docstore
```

The compiled filter is shown above the results for transparency:

```
Filter: is_paid = False AND total_amount > 5000
```

If your question references a field that isn't in the schema, the compiler returns an explanation rather than guessing.

---

## `diff`

Compare a file's current content against its cached extraction. One LLM call (for the re-extraction); the previous version is read from cache.

```bash
docstore diff <file_path> --schema <name> [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--schema`, `-s` | **required** | Schema under which the file was previously extracted. |
| `--store` | `<file_path's parent>/.docstore` | Cache directory. |
| `--model` | `claude-haiku-4-5-20251001` | Model used for the re-extraction. |

```bash
docstore diff ./invoices/acme_april.pdf --schema invoice_schema
```

The previous extraction is located by file path (not by current hash), so this works even after the file has changed.

---

## `schemas`

List every schema in the store with its versions and document counts.

```bash
docstore schemas [--store DIR]
```

```bash
docstore schemas --store ./invoices/.docstore
```

Example output:

```
Schema name      | Versions       | Documents
invoice_schema   | 3cd457dad237   | 30
contract_schema  | a1b2c3d4e5f6   | 8
```

---

## `stats`

Show cache statistics and cost-to-recompute.

```bash
docstore stats [--store DIR]
```

| Stat | Meaning |
|---|---|
| `Total entries` | Count of cached `*.json` files. |
| `Tokens absorbed by cache` | Sum of `tokens_used` across all entries - the LLM work the cache holds. |
| `Cost to re-extract all` | What you'd pay to redo everything at current Haiku 4.5 pricing. |

---

## `clean`

Delete cached extraction results.

```bash
docstore clean [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--schema`, `-s` | none | Only delete entries for this schema. Omit to delete all. |
| `--yes`, `-y` | `false` | Skip the confirmation prompt. |
| `--store` | `.docstore` | Cache directory. |

```bash
# Wipe only one schema's entries
docstore clean --schema invoice_schema --store ./invoices/.docstore

# Wipe everything
docstore clean --yes --store ./invoices/.docstore
```

---

## `sync`

Remove cache entries whose source file no longer exists on disk. Without `--yes`, only reports what would be removed.

```bash
docstore sync [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--yes`, `-y` | `false` | Delete stale entries. Without this flag, only reports them. |
| `--store` | `.docstore` | Cache directory. |

```bash
# Dry run - see what's stale without deleting anything
docstore sync --store ./invoices/.docstore

# Remove stale entries
docstore sync --store ./invoices/.docstore --yes
```

A stale entry is any cached result whose original source file path no longer exists on disk. This happens when documents are moved, renamed, or deleted after they were extracted. Stale entries are otherwise harmless (they don't affect correctness) but they inflate `stats` counts and appear in `query` results.

---

## `shell`

Interactive prompt that walks you through describing fields and runs the pipeline. Useful for ad-hoc exploration.

```bash
docstore shell <path> [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--store` | `<path>/.docstore` | Cache directory. |
| `--model` | `claude-haiku-4-5-20251001` | Model used by elicitation and extraction. |

```bash
docstore shell ./contracts/
# > vendor name, contract start date, expiry date, whether it auto-renews
```

The orchestrator normalises your description, shows the resulting schema, and prompts before extracting.

---

## Environment variables

| Variable | Default | Used by |
|---|---|---|
| `ANTHROPIC_API_KEY` | - | All commands that make LLM calls. |
| `DOCSTORE_DIR` | `.docstore` | MCP server's default store directory. |
| `DOCSTORE_MODEL` | `claude-haiku-4-5-20251001` | MCP server's default model. |

Loaded automatically from `.env` at the project root.
