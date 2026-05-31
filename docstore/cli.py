"""
docstore CLI

Commands:
  extract   Run extraction pipeline on a file or directory
  query     Query stored results without LLM calls
  diff      Compare current file against stored version
  schemas   List all schemas in the store
  stats     Show cache stats and token savings
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

from .agents import orchestrator, differ as differ_agent
from .schema import ExtractionSchema, SchemaDescriptor
from .store import DocStore

app = typer.Typer(
    name="docstore",
    help="dbt for unstructured data — extract once, query forever.",
    add_completion=False,
)
console = Console()


def _get_store(store_dir: str) -> DocStore:
    return DocStore(root=Path(store_dir))


# ── extract ────────────────────────────────────────────────────────────────

@app.command()
def extract(
    path: Path = typer.Argument(..., help="File or directory to process"),
    schema: Optional[str] = typer.Option(None, "--schema", "-s", help="Schema name from store"),
    ask: bool = typer.Option(False, "--ask", help="Describe fields interactively"),
    store_dir: str = typer.Option(".docstore", "--store", help="Store directory"),
    model: str = typer.Option("claude-haiku-4-5-20251001", "--model"),
):
    """Extract structured data from a file or directory."""
    import anthropic
    client = anthropic.Anthropic()
    store = _get_store(store_dir)

    # Resolve schema descriptor
    descriptor = _resolve_descriptor(store, schema, ask, client)

    if path.is_dir():
        rprint(f"[gold1]Scanning[/gold1] {path} ...")
        results = orchestrator.run_directory(path, descriptor, store, client, model)
    else:
        results = [orchestrator.run_pipeline(path, descriptor, store, client, model)]

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

    hits  = sum(1 for r in results if r.cache_hit)
    misses = len(results) - hits
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

    # Table output — columns from first result's data keys
    if results:
        keys = list(results[0].data.keys())
        table = Table(title=f"{schema} — {len(results)} records")
        table.add_column("file", style="dim")
        for k in keys:
            table.add_column(k)
        for r in results:
            row = [Path(r.file_path).name] + [str(r.data.get(k, "")) for k in keys]
            table.add_row(*row)
        console.print(table)


# ── diff ───────────────────────────────────────────────────────────────────

@app.command()
def diff(
    file_path: Path = typer.Argument(..., help="File to diff against stored version"),
    schema: str = typer.Option(..., "--schema", "-s"),
    store_dir: str = typer.Option(".docstore", "--store"),
    model: str = typer.Option("claude-haiku-4-5-20251001", "--model"),
):
    """Compare current file against its stored extraction."""
    import anthropic
    client = anthropic.Anthropic()
    store = _get_store(store_dir)

    # Find existing stored entry
    entries = store.list_entries_for_file(file_path)
    matching = [e for e in entries if e[0] == schema]

    if not matching:
        rprint(f"[red]No stored result found for '{schema}' on {file_path.name}[/red]")
        raise typer.Exit(1)

    schema_name, version = matching[0]
    descriptor = SchemaDescriptor(name=schema_name, fields={}, version=version)

    # Get stored result
    stored = store.get(file_path, descriptor)
    if stored is None:
        rprint("[red]Could not retrieve stored result.[/red]")
        raise typer.Exit(1)

    # Run fresh extraction
    rprint(f"[gold1]Re-extracting[/gold1] {file_path.name} ...")

    # Need full descriptor — load from stored metadata
    full_descriptor = SchemaDescriptor(
        name=stored.schema_name,
        fields={},  # fields not stored in result — re-elicit or pass --ask
        version=stored.schema_version,
    )

    from .agents import parser as parser_agent, extractor as extractor_agent
    raw_text = parser_agent.parse(file_path)
    current_data, _ = extractor_agent.extract(raw_text, full_descriptor, client, model)
    current_hash = store.file_hash(file_path)

    result = differ_agent.diff(
        previous=stored.data,
        current=current_data,
        descriptor=full_descriptor,
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
    rprint(f"  Total entries      : {s['total_entries']}")
    rprint(f"  Tokens consumed    : {s['total_tokens_used']:,}")
    rprint(f"  Tokens saved       : {s['total_tokens_saved']:,}")
    rprint(f"  Estimated $ saved  : ${s['estimated_cost_saved_usd']:.4f}")
    if s["schema_counts"]:
        rprint("\n  [bold]By schema:[/bold]")
        for name, count in s["schema_counts"].items():
            rprint(f"    {name:<30} {count} documents")
    rprint("")


# ── shell ──────────────────────────────────────────────────────────────────

@app.command()
def shell(
    path: Path = typer.Argument(..., help="File or directory to process"),
    store_dir: str = typer.Option(".docstore", "--store"),
    model: str = typer.Option("claude-haiku-4-5-20251001", "--model"),
):
    """Interactive shell — describe fields in plain language."""
    import anthropic
    client = anthropic.Anthropic()
    store = _get_store(store_dir)

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
        return orchestrator.elicit_schema(user_input, existing, client)

    if schema_name:
        existing = store.list_schemas()
        if schema_name in existing:
            versions = existing[schema_name]
            # Return a descriptor shell — fields will be matched by name+version
            return SchemaDescriptor(name=schema_name, fields={}, version=versions[-1])
        rprint(f"[yellow]Schema '{schema_name}' not found in store. Eliciting...[/yellow]")
        user_input = typer.prompt("Describe the fields you want to extract")
        return orchestrator.elicit_schema(user_input, existing, client)

    # No schema provided — ask
    existing = store.list_schemas()
    user_input = typer.prompt("Describe the fields you want to extract")
    return orchestrator.elicit_schema(user_input, existing, client)


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
