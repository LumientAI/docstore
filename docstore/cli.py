"""
lumient-docstore CLI

Commands:
  extract   Run extraction pipeline on a file or directory
  query     Query stored results without LLM calls
  ask       Ask a natural-language question
  diff      Compare current file against stored version
  schemas   List all schemas in the store
  stats     Show cache stats and token savings
  clean     Delete cached extraction results
  shell     Interactive schema elicitation shell
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich import print as rprint
from rich.console import Console
from rich.table import Table

load_dotenv()

from docstore.agents import orchestrator, differ as differ_agent
from docstore.config import DOCSTORE_MODEL, DOCSTORE_PROVIDER
from docstore.llm import LLMClient, ProviderName, create_llm_client, resolve_model
from docstore.schema import SchemaDescriptor
from docstore.store import DEFAULT_STORE_DIR, DocStore

app = typer.Typer(
    name="docstore",
    help="dbt for unstructured data — extract once, query forever.",
    add_completion=False,
)
console = Console()


def _get_store(store_dir: str) -> DocStore:
    return DocStore(root=Path(store_dir))


def _resolve_store_for_path(path: Path, store_dir: str) -> str:
    """Co-locate the cache with the corpus when --store is at its default.

    Matches the benchmark's `directory/.docstore` convention so the cache
    travels with the data. If the user passed --store explicitly, honor that.
    """
    if store_dir != ".docstore":
        return store_dir
    base = path if path.is_dir() else path.parent
    return str(base / ".docstore")


def _resolve_provider_model(provider: ProviderName, model: str | None = None) -> str:
    return resolve_model(provider, model)


def _create_llm(provider: ProviderName, model: str | None = None) -> tuple[LLMClient, str]:
    resolved_model = _resolve_provider_model(provider, model or DOCSTORE_MODEL)
    return create_llm_client(provider, resolved_model), resolved_model


# ── extract ────────────────────────────────────────────────────────────────

@app.command()
def extract(
    path: Path = typer.Argument(..., help="File or directory to process"),
    schema: Optional[str] = typer.Option(None, "--schema", "-s", help="Schema name from store"),
    ask: bool = typer.Option(False, "--ask", help="Describe fields interactively"),
    validate: bool = typer.Option(False, "--validate",
        help="Run a second LLM call per file to validate extracted data. "
             "Doubles cold-extract cost; off by default."),
    store_dir: str = typer.Option(".docstore", "--store",
        help="Store directory. Defaults to <path>/.docstore so the cache "
             "lives with the corpus."),
    provider: ProviderName = typer.Option(DOCSTORE_PROVIDER, "--provider"),
    model: str | None = typer.Option(None, "--model"),
    workers: int = typer.Option(1, "--workers", "-w", help="Parallel extraction workers", min=1),
):
    """Extract structured data from a file or directory."""
    client, model = _create_llm(provider, model)
    store = _get_store(_resolve_store_for_path(path, store_dir))

    # Resolve schema descriptor
    descriptor = _resolve_descriptor(store, schema, ask, client)

    if path.is_dir():
        rprint(f"[gold1]Scanning[/gold1] {path} ...")
        results = orchestrator.run_directory(path, descriptor, store, client, model,
                                             validate=validate, workers=workers)
    else:
        results = [orchestrator.run_pipeline(path, descriptor, store, client, model,
                                             validate=validate)]

    # Summary table
    table = Table(title="Extraction Results")
    table.add_column("File", style="dim")
    table.add_column("Valid")
    table.add_column("Cache")
    table.add_column("Tokens used", justify="right")
    table.add_column("Tokens saved", justify="right")

    for r in results:
        valid_str  = "[green]✓[/green]" if r.valid else "[red]✗[/red]"
        cache_str  = "[green]HIT[/green]" if r.cache_hit else "[yellow]MISS[/yellow]"
        table.add_row(
            Path(r.file_path).name,
            valid_str,
            cache_str,
            str(r.tokens_used),
            str(r.tokens_saved),
        )

    console.print(table)

    hits = sum(1 for r in results if r.cache_hit)
    total_saved = sum(r.tokens_saved for r in results)
    rprint(
        f"\n[dim]Cache hits: {hits} / {len(results)} — "
        f"~{total_saved:,} tokens saved[/dim]"
    )


# ── query ──────────────────────────────────────────────────────────────────

@app.command()
def query(
    schema: str = typer.Argument(..., help="Schema name to query"),
    filter_expr: Optional[str] = typer.Option(None, "--filter", "-f",
        help='Filter expression e.g. "paid=false"'),
    output: str = typer.Option("table", "--output", "-o",
        help="Output format: table | json"),
    store_dir: str = typer.Option(".docstore", "--store"),
):
    """Query stored extraction results. No LLM calls."""
    store = _get_store(store_dir)

    filter_fn = _build_filter(filter_expr) if filter_expr else None
    results = store.query(schema, filter_fn)

    if not results:
        rprint(f"[yellow]No results found for schema '{schema}'[/yellow]")
        raise typer.Exit()

    if output == "json":
        rprint(json.dumps([r.data for r in results], indent=2))
        return

    # Table output — columns from first result's data keys.
    # Nested values get summarised so they don't wrap character-by-character.
    if results:
        keys = list(results[0].data.keys())
        table = Table(title=f"{schema} — {len(results)} records")
        table.add_column("file", style="dim")
        for k in keys:
            table.add_column(k)
        for r in results:
            row = [Path(r.file_path).name] + [_fmt_cell(r.data.get(k)) for k in keys]
            table.add_row(*row)
        console.print(table)


# ── export ────────────────────────────────────────────────────────────────

@app.command()
def export(
    schema_name: str = typer.Argument(..., help="Schema name to export"),
    output_format: str = typer.Option("csv", "--format", "-f", help="Output format: csv, json, sqlite"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path (default: <schema_name>.<format>)"),
    store_dir: Path = typer.Option(Path(DEFAULT_STORE_DIR), "--store-dir", "-s"),
) -> None:
    """Export all cached extractions for a schema to csv, json, or sqlite."""
    store = DocStore(store_dir)
    results = store.query(schema_name)
    if not results:
        console.print(f"[yellow]No entries found for schema '{schema_name}'[/yellow]")
        raise typer.Exit(1)

    fmt = output_format.lower()
    if fmt not in ("csv", "json", "sqlite"):
        console.print("[red]--format must be one of: csv, json, sqlite[/red]")
        raise typer.Exit(1)

    out_path = output or Path(f"{schema_name}.{fmt}")
    safe_name = schema_name.replace('"', '""')
    fields = list({k for r in results for k in r.data.keys()})

    if fmt == "csv":
        import csv
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["file_path", "extracted_at", *fields], extrasaction="ignore")
            writer.writeheader()
            for r in results:
                row = {"file_path": r.file_path, "extracted_at": r.extracted_at, **r.data}
                writer.writerow(row)

    elif fmt == "json":
        import json as _json
        rows = [{"file_path": r.file_path, "extracted_at": r.extracted_at, **r.data} for r in results]
        with open(out_path, "w") as f:
            _json.dump(rows, f, indent=2, default=str)

    elif fmt == "sqlite":
        import sqlite3
        cols = ", ".join(f'"{f}" TEXT' for f in ["file_path", "extracted_at", *fields])
        with sqlite3.connect(out_path) as con:
            con.execute(f'DROP TABLE IF EXISTS "{safe_name}"')
            con.execute(f'CREATE TABLE "{safe_name}" ({cols})')
            for r in results:
                vals = [r.file_path, str(r.extracted_at), *[str(r.data.get(f, "")) for f in fields]]
                placeholders = ", ".join("?" * len(vals))
                con.execute(f'INSERT INTO "{safe_name}" VALUES ({placeholders})', vals)

    console.print(f"[green]Exported {len(results)} records to {out_path}[/green]")


# ── ask ────────────────────────────────────────────────────────────────────

@app.command()
def ask(
    question: str = typer.Argument(..., help='Natural-language question, e.g. "which invoices are unpaid?"'),
    schema_name: str = typer.Option(..., "--schema", "-s", help="Schema to query against"),
    store_dir: str = typer.Option(".docstore", "--store"),
    output: str = typer.Option("table", "--output", "-o", help="Output format: table | json"),
    model: str = typer.Option("claude-haiku-4-5-20251001", "--model"),
):
    """Ask a question in natural language. One LLM call compiles it to a
    filter; results come from cache with zero further LLM calls."""
    import anthropic
    from docstore.agents.compiler import compile_filter, filter_to_string
    from docstore.store import evaluate_filter

    client = anthropic.Anthropic()
    store = _get_store(store_dir)

    # Hydrate the schema's fields from any cached entry (compiler needs the
    # exact field names to anchor the LLM and avoid hallucinated columns).
    existing = store.list_schemas()
    if schema_name not in existing:
        rprint(f"[red]Schema '{schema_name}' not found. Available: "
               f"{list(existing.keys())}[/red]")
        raise typer.Exit(1)
    version = existing[schema_name][-1]
    sample = next(store.root.glob(f"*__{schema_name}__{version}.json"), None)
    if sample is None:
        rprint(f"[red]No cached entries for '{schema_name}'.[/red]")
        raise typer.Exit(1)
    with open(sample) as f:
        sample_data = json.load(f)
    fields = sample_data.get("schema_fields", {})
    if not fields:
        rprint(f"[red]Schema '{schema_name}' has no field metadata (predates "
               f"field persistence). Re-extract first.[/red]")
        raise typer.Exit(1)

    # Compile English → filter AST
    ast = compile_filter(question, fields, client, model)

    if "error" in ast:
        rprint(f"[red]Could not compile question: {ast['error']}[/red]")
        rprint(f"[dim]Available fields: {list(fields.keys())}[/dim]")
        raise typer.Exit(1)

    rprint(f"[dim]Filter: {filter_to_string(ast)}[/dim]\n")

    # Evaluate against cache — zero LLM calls beyond the compile
    results = store.query(schema_name, lambda r: evaluate_filter(ast, r.data))

    if not results:
        rprint("[yellow]No matching records.[/yellow]")
        return

    if output == "json":
        rprint(json.dumps([r.data for r in results], indent=2))
        return

    keys = list(results[0].data.keys())
    table = Table(title=f"{schema_name} — {len(results)} records")
    table.add_column("file", style="dim")
    for k in keys:
        table.add_column(k)
    for r in results:
        row = [Path(r.file_path).name] + [_fmt_cell(r.data.get(k)) for k in keys]
        table.add_row(*row)
    console.print(table)


# ── diff ───────────────────────────────────────────────────────────────────

@app.command()
def diff(
    file_path: Path = typer.Argument(..., help="File to diff against stored version"),
    schema: str = typer.Option(..., "--schema", "-s"),
    store_dir: str = typer.Option(".docstore", "--store",
        help="Store directory. Defaults to <file_path's parent>/.docstore."),
    provider: ProviderName = typer.Option(DOCSTORE_PROVIDER, "--provider"),
    model: str | None = typer.Option(None, "--model"),
):
    """Compare current file against its stored extraction."""
    client, model = _create_llm(provider, model)
    store = _get_store(_resolve_store_for_path(file_path, store_dir))

    # Find the previous extraction by file path (not by current file hash —
    # the file may have changed, which is the whole point of diff).
    stored = store.find_for_path(file_path, schema)
    if stored is None:
        rprint(f"[red]No stored result found for '{schema}' on {file_path.name}[/red]")
        raise typer.Exit(1)

    if not stored.schema_fields:
        rprint("[red]Cached entry has no field metadata (predates field "
               "persistence). Re-extract this file first to migrate.[/red]")
        raise typer.Exit(1)

    descriptor = SchemaDescriptor(
        name=stored.schema_name,
        fields=stored.schema_fields,
        version=stored.schema_version,
    )

    rprint(f"[gold1]Re-extracting[/gold1] {file_path.name} ...")

    from docstore.agents import parser as parser_agent, extractor as extractor_agent
    raw_text = parser_agent.parse(file_path)
    current_data, _ = extractor_agent.extract(raw_text, descriptor, client, model)
    current_hash = store.file_hash(file_path)

    result = differ_agent.diff(
        previous=stored.data,
        current=current_data,
        descriptor=descriptor,
        file_path=str(file_path),
        previous_hash=stored.file_hash,
        current_hash=current_hash,
        client=client,
        model=model,
    )

    if not result.changed_fields:
        rprint("[green]No changes detected.[/green]")
        return

    rprint(f"\n[bold]Changed fields:[/bold] {', '.join(result.changed_fields)}")
    rprint(f"[bold]Summary:[/bold] {result.summary}\n")

    table = Table(title="Field Diff")
    table.add_column("Field")
    table.add_column("Previous", style="red")
    table.add_column("Current", style="green")
    for field in result.changed_fields:
        table.add_row(
            field,
            str(result.previous.get(field, "—")),
            str(result.current.get(field, "—")),
        )
    console.print(table)


# ── schemas ────────────────────────────────────────────────────────────────

@app.command()
def schemas(
    store_dir: str = typer.Option(".docstore", "--store"),
):
    """List all schemas present in the store."""
    store = _get_store(store_dir)
    schema_map = store.list_schemas()

    if not schema_map:
        rprint("[yellow]No schemas found in store.[/yellow]")
        return

    table = Table(title="Schemas in store")
    table.add_column("Schema name")
    table.add_column("Versions")
    table.add_column("Documents", justify="right")
    for name, versions in schema_map.items():
        count = len(store.query(name))
        table.add_row(name, ", ".join(versions), str(count))
    console.print(table)


# ── stats ──────────────────────────────────────────────────────────────────

@app.command()
def stats(
    store_dir: str = typer.Option(".docstore", "--store"),
):
    """Show cache statistics and token savings."""
    store = _get_store(store_dir)
    s = store.stats()

    rprint(f"\n[bold]docstore stats[/bold] ({store_dir})\n")
    rprint(f"  Total entries           : {s['total_entries']}")
    rprint(f"  Tokens absorbed by cache: {s['total_tokens_cached']:,}")
    rprint(f"  Cost to re-extract all  : ${s['estimated_cost_to_recompute_usd']:.4f}")
    if s["schema_counts"]:
        rprint("\n  [bold]By schema:[/bold]")
        for name, count in s["schema_counts"].items():
            rprint(f"    {name:<30} {count} documents")
    rprint("")


# ── clean ──────────────────────────────────────────────────────────────────

@app.command()
def clean(
    store_dir: str = typer.Option(".docstore", "--store"),
    schema: Optional[str] = typer.Option(None, "--schema", "-s",
        help="Only delete entries for this schema. Omit to delete all."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
):
    """Delete cached extraction results. Use --schema to scope to one schema."""
    store = _get_store(store_dir)

    if schema:
        pattern = f"*__{schema}__*.json"
        target = f"all entries for schema '{schema}'"
    else:
        pattern = "*.json"
        target = "ALL cached entries"

    entries = list(store.root.glob(pattern))
    if not entries:
        rprint(f"[yellow]Nothing to delete in {store.root} (no entries matched).[/yellow]")
        return

    rprint(f"\n[bold]About to delete {len(entries)} entries[/bold] "
           f"({target}) from {store.root}")
    if not yes and not typer.confirm("Proceed?", default=False):
        rprint("[yellow]Aborted.[/yellow]")
        raise typer.Exit()

    for p in entries:
        p.unlink()
    rprint(f"[green]Deleted {len(entries)} entries.[/green]")


# ── sync ───────────────────────────────────────────────────────────────

@app.command()
def sync(
    store_dir: str = typer.Option(".docstore", "--store"),
    yes: bool = typer.Option(False, "--yes", "-y",
        help="Delete stale entries. Without this flag, only reports them."),
):
    """Remove cache entries whose source file no longer exists on disk."""
    store = _get_store(store_dir)
    stale = store.sync(delete=yes)

    if not stale:
        rprint("[green]Store is in sync — no stale entries.[/green]")
        return

    if yes:
        rprint(f"[green]Removed {len(stale)} stale entr{'y' if len(stale) == 1 else 'ies'}:[/green]")
    else:
        rprint(
            f"[yellow]{len(stale)} stale entr{'y' if len(stale) == 1 else 'ies'} "
            f"(source file missing). Run with --yes to remove:[/yellow]"
        )
    for fp in stale:
        rprint(f"  [dim]{fp}[/dim]")


# ── shell ──────────────────────────────────────────────────────────────────

@app.command()
def shell(
    path: Path = typer.Argument(..., help="File or directory to process"),
    store_dir: str = typer.Option(".docstore", "--store",
        help="Store directory. Defaults to <path>/.docstore."),
    provider: ProviderName = typer.Option(DOCSTORE_PROVIDER, "--provider"),
    model: str | None = typer.Option(None, "--model"),
):
    """Interactive shell — describe fields in plain language."""
    client, model = _create_llm(provider, model)
    store = _get_store(_resolve_store_for_path(path, store_dir))

    existing = store.list_schemas()
    if existing:
        rprint("\n[dim]Existing schemas in store:[/dim]")
        for name, versions in existing.items():
            count = len(store.query(name))
            rprint(f"  [gold1]{name}[/gold1] ({count} documents, versions: {', '.join(versions)})")
        rprint("")

    rprint("[bold]What fields do you want to extract?[/bold]")
    rprint("[dim]Example: vendor name, total amount, due date, whether it's been paid[/dim]\n")

    user_input = typer.prompt("> ")

    rprint("\n[dim]Normalising schema...[/dim]")
    descriptor = orchestrator.elicit_schema(user_input, existing, client)

    rprint(f"\n[bold]Schema:[/bold] [gold1]{descriptor.name}[/gold1] (v{descriptor.version})")
    for field, ftype in descriptor.fields.items():
        rprint(f"  {field:<30} [dim]{ftype}[/dim]")

    proceed = typer.confirm("\nProceed with this schema?", default=True)
    if not proceed:
        rprint("[yellow]Aborted.[/yellow]")
        raise typer.Exit()

    if path.is_dir():
        results = orchestrator.run_directory(path, descriptor, store, client, model)
    else:
        results = [orchestrator.run_pipeline(path, descriptor, store, client, model)]

    hits = sum(1 for r in results if r.cache_hit)
    total_saved = sum(r.tokens_saved for r in results)
    rprint(
        f"\n[green]Done.[/green] {len(results)} documents processed. "
        f"{hits} cache hits. ~{total_saved:,} tokens saved."
    )


# ── Helpers ────────────────────────────────────────────────────────────────

def _resolve_descriptor(
    store: DocStore,
    schema_name: str | None,
    ask: bool,
    client,
) -> SchemaDescriptor:
    if ask:
        existing = store.list_schemas()
        user_input = typer.prompt("Describe the fields you want to extract")
        return orchestrator.elicit_schema(user_input, existing, client, name=schema_name)

    if schema_name:
        existing = store.list_schemas()
        if schema_name in existing:
            versions = existing[schema_name]
            version = versions[-1]
            sample = next(store.root.glob(f"*__{schema_name}__{version}.json"), None)
            if sample is not None:
                with open(sample) as f:
                    data = json.load(f)
                fields = data.get("schema_fields", {})
                if fields:
                    return SchemaDescriptor(name=schema_name, fields=fields, version=version)
            rprint(f"[yellow]Schema '{schema_name}' exists but predates field "
                   f"persistence. Re-eliciting...[/yellow]")
            user_input = typer.prompt("Describe the fields you want to extract")
            return orchestrator.elicit_schema(user_input, existing, client, name=schema_name)
        rprint(f"[yellow]Schema '{schema_name}' not found in store. Eliciting...[/yellow]")
        user_input = typer.prompt("Describe the fields you want to extract")
        return orchestrator.elicit_schema(user_input, existing, client, name=schema_name)

    # No schema provided — ask
    existing = store.list_schemas()
    user_input = typer.prompt("Describe the fields you want to extract")
    return orchestrator.elicit_schema(user_input, existing, client)


def _fmt_cell(value) -> str:
    """Render a result-data value for a table cell. Summarise nested structures
    so they don't wrap character-by-character. Full data is still available
    via `--output json`."""
    if value is None:
        return ""
    if isinstance(value, list):
        return f"[{len(value)} items]"
    if isinstance(value, dict):
        return f"{{{len(value)} keys}}"
    return str(value)


def _build_filter(expr: str):
    """
    Build a simple filter function from an expression like 'paid=false'.
    Supports: field=value, field!=value
    """
    def filter_fn(result):
        try:
            if "!=" in expr:
                field, value = expr.split("!=", 1)
                return str(result.data.get(field.strip(), "")) != value.strip()
            elif "=" in expr:
                field, value = expr.split("=", 1)
                actual = str(result.data.get(field.strip(), "")).lower()
                return actual == value.strip().lower()
        except Exception:
            return True
        return True
    return filter_fn


if __name__ == "__main__":
    app()
