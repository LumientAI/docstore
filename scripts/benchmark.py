"""
Benchmark script — measures token savings vs baseline.

Baseline: re-read every document and call the LLM every time a question is asked.
docstore: extract once, answer from cache on subsequent queries.

Usage:
  python scripts/benchmark.py ./invoices --schema invoice_schema --runs 3
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from rich import print as rprint
from rich.table import Table
from rich.console import Console

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

from docstore.agents import orchestrator, parser as parser_agent
from docstore.schema import SchemaDescriptor
from docstore.store import DocStore


console = Console()


def baseline_tokens(directory: Path, glob: str = "*.txt") -> int:
    """Estimate tokens consumed if we read all documents every time."""
    supported = {".pdf", ".docx", ".txt", ".md", ".csv"}
    total = 0
    for f in directory.glob(glob):
        if f.suffix.lower() in supported:
            text = parser_agent.parse(f)
            total += parser_agent.estimate_tokens(text)
    return total


def run_benchmark(directory: Path, schema_name: str, runs: int = 3):
    store = DocStore(root=directory / ".docstore")
    client = anthropic.Anthropic()

    # Elicit schema interactively
    existing = store.list_schemas()
    if schema_name in existing:
        versions = existing[schema_name]
        descriptor = SchemaDescriptor(name=schema_name, fields={}, version=versions[-1])
        rprint(f"[dim]Reusing existing schema: {schema_name}[/dim]")
    else:
        rprint(f"[bold]Schema '{schema_name}' not found. Describe the fields:[/bold]")
        user_input = input("> ")
        descriptor = orchestrator.elicit_schema(user_input, existing, client)
        rprint(f"[dim]Created schema: {descriptor.name} v{descriptor.version}[/dim]")

    baseline = baseline_tokens(directory)
    rprint(f"\n[bold]Baseline tokens per query (no cache):[/bold] {baseline:,}")
    rprint(f"[bold]Runs:[/bold] {runs}\n")

    table = Table(title="Benchmark Results")
    table.add_column("Run", justify="right")
    table.add_column("Cache hits", justify="right")
    table.add_column("Cache misses", justify="right")
    table.add_column("Tokens used", justify="right")
    table.add_column("Tokens saved", justify="right")
    table.add_column("Saving %", justify="right")
    table.add_column("Time (s)", justify="right")

    for run in range(1, runs + 1):
        t0 = time.time()
        results = orchestrator.run_directory(directory, descriptor, store, client)
        elapsed = time.time() - t0

        hits   = sum(1 for r in results if r.cache_hit)
        misses = len(results) - hits
        used   = sum(r.tokens_used for r in results)
        saved  = sum(r.tokens_saved for r in results)
        saving_pct = f"{saved / (used + saved) * 100:.1f}%" if (used + saved) > 0 else "—"

        table.add_row(
            str(run),
            str(hits),
            str(misses),
            f"{used:,}",
            f"{saved:,}",
            saving_pct,
            f"{elapsed:.1f}",
        )

    console.print(table)

    # Summary
    s = store.stats()
    rprint(f"\n[bold]Total tokens saved across all runs:[/bold] {s['total_tokens_saved']:,}")
    rprint(f"[bold]Estimated cost saved:[/bold] ${s['estimated_cost_saved_usd']:.4f}")
    rprint(
        f"\n[dim]Baseline cost (re-read everything, {runs} runs): "
        f"~${baseline * runs / 1_000_000 * 0.25:.4f}[/dim]"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="docstore benchmark")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--schema", default="benchmark_schema")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    run_benchmark(args.directory, args.schema, args.runs)
