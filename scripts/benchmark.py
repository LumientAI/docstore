"""
Reproducible public benchmark for docstore's extraction cache.

The benchmark uses synthetic invoices and a fixed schema so runs are comparable:
  1. cold_extract: empty cache, all files miss and call the LLM
  2. warm_extract: same files/schema, all files hit cache and use zero tokens
  3. cached_query: query cached JSON locally with no parser or LLM calls

Usage:
  uv run python scripts/benchmark.py /tmp/docstore-bench --count 30 --provider groq
  uv run python scripts/benchmark.py /tmp/docstore-bench --output json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from rich import print as rprint
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

from docstore.agents import orchestrator, parser as parser_agent
from docstore.llm import DEFAULT_PROVIDER, ProviderName, create_llm_client, resolve_model
from docstore.schema import ExtractionResult, SchemaDescriptor
from docstore.store import DocStore


console = Console()

BENCHMARK_SCHEMA_NAME = "invoice_benchmark"
BENCHMARK_SCHEMA_FIELDS = {
    "vendor": "string",
    "invoice_no": "string",
    "amount": "number",
    "currency": "string",
    "due_date": "date",
    "paid": "boolean",
}
SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".csv", ".html", ".json"}


def benchmark_schema() -> SchemaDescriptor:
    return SchemaDescriptor(name=BENCHMARK_SCHEMA_NAME, fields=BENCHMARK_SCHEMA_FIELDS)


def baseline_tokens(directory: Path, glob: str = "*") -> int:
    total = 0
    for f in directory.glob(glob):
        if f.is_file() and f.suffix.lower() in SUPPORTED_SUFFIXES:
            text = parser_agent.parse(f)
            total += parser_agent.estimate_tokens(text)
    return total


def summarize_extract(
    scenario: str,
    results: list[ExtractionResult],
    elapsed_seconds: float,
    usd_per_mtok: float,
) -> dict[str, Any]:
    hits = sum(1 for r in results if r.cache_hit)
    misses = len(results) - hits
    tokens_used = sum(r.tokens_used for r in results if not r.cache_hit)
    tokens_saved = sum(r.tokens_saved for r in results if r.cache_hit)
    denominator = tokens_used + tokens_saved
    savings_percent = round(tokens_saved / denominator * 100, 1) if denominator else 0.0
    return {
        "scenario": scenario,
        "documents": len(results),
        "cache_hits": hits,
        "cache_misses": misses,
        "tokens_used": tokens_used,
        "tokens_saved": tokens_saved,
        "savings_percent": savings_percent,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "estimated_cost_usd": round(tokens_used / 1_000_000 * usd_per_mtok, 6),
    }


def summarize_query(
    scenario: str,
    records: int,
    elapsed_seconds: float,
) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "documents": records,
        "cache_hits": records,
        "cache_misses": 0,
        "tokens_used": 0,
        "tokens_saved": 0,
        "savings_percent": 100.0,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "estimated_cost_usd": 0.0,
    }


def run_extract_scenario(
    scenario: str,
    directory: Path,
    descriptor: SchemaDescriptor,
    store: DocStore,
    client,
    model: str,
    usd_per_mtok: float,
    glob: str = "*",
) -> dict[str, Any]:
    t0 = time.perf_counter()
    results = orchestrator.run_directory(
        directory,
        descriptor,
        store,
        client,
        model,
        glob=glob,
        progress=True,
    )
    return summarize_extract(scenario, results, time.perf_counter() - t0, usd_per_mtok)


def run_cached_query_scenario(
    descriptor: SchemaDescriptor,
    store: DocStore,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    results = store.query(descriptor.name)
    return summarize_query("cached_query", len(results), time.perf_counter() - t0)


def prepare_corpus(directory: Path, count: int, seed: int, generate: bool, glob: str = "invoice_*.txt") -> int:
    if generate:
        from scripts.generate_txt_invoices import generate_corpus
        return len(generate_corpus(directory, count=count, seed=seed))
    files = [
        f for f in directory.glob(glob)
        if f.is_file() and f.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    return len(files)


def run_benchmark(
    directory: Path,
    *,
    count: int = 30,
    seed: int = 42,
    provider: ProviderName = DEFAULT_PROVIDER,
    model: str | None = None,
    generate: bool = True,
    fresh: bool = True,
    usd_per_mtok: float = 1.0,
    schema_name: str | None = None,
    schema_fields: dict[str, str] | None = None,
    glob: str = "invoice_*.txt",
) -> dict[str, Any]:
    document_count = prepare_corpus(directory, count, seed, generate, glob=glob)
    store_dir = directory / ".docstore"
    if fresh and store_dir.exists():
        shutil.rmtree(store_dir)

    if schema_name and schema_fields:
        descriptor = SchemaDescriptor(name=schema_name, fields=schema_fields)
    else:
        descriptor = benchmark_schema()

    store = DocStore(root=store_dir)
    model = resolve_model(provider, model)
    client = create_llm_client(provider, model)

    cold = run_extract_scenario(
        "cold_extract", directory, descriptor, store, client, model, usd_per_mtok, glob=glob
    )
    warm = run_extract_scenario(
        "warm_extract", directory, descriptor, store, client, model, usd_per_mtok, glob=glob
    )
    query = run_cached_query_scenario(descriptor, store)

    return {
        "corpus": {
            "directory": str(directory),
            "documents": document_count,
            "ground_truth": str(directory / "ground_truth.jsonl"),
        },
        "schema": {
            "name": descriptor.name,
            "version": descriptor.version,
            "fields": descriptor.fields,
        },
        "llm": {
            "provider": provider,
            "model": model,
            "usd_per_mtok": usd_per_mtok,
        },
        "scenarios": [cold, warm, query],
    }


def print_table(report: dict[str, Any]) -> None:
    corpus = report["corpus"]
    llm = report["llm"]
    rprint(
        f"\n[bold]docstore benchmark[/bold] "
        f"({corpus['documents']} documents, {llm['provider']}:{llm['model']})"
    )
    if "baseline_tokens_per_full_read" in corpus:
        rprint(f"[dim]Baseline full-read tokens: {corpus['baseline_tokens_per_full_read']:,}[/dim]")
    rprint("")

    table = Table(title="Cache Benchmark")
    table.add_column("Scenario")
    table.add_column("Docs", justify="right")
    table.add_column("Hits", justify="right")
    table.add_column("Misses", justify="right")
    table.add_column("Tokens used", justify="right")
    table.add_column("Tokens saved", justify="right")
    table.add_column("Saving", justify="right")
    table.add_column("Time (s)", justify="right")
    table.add_column("Cost", justify="right")

    for row in report["scenarios"]:
        table.add_row(
            row["scenario"],
            str(row["documents"]),
            str(row["cache_hits"]),
            str(row["cache_misses"]),
            f"{row['tokens_used']:,}",
            f"{row['tokens_saved']:,}",
            f"{row['savings_percent']:.1f}%",
            f"{row['elapsed_seconds']:.3f}",
            f"${row['estimated_cost_usd']:.6f}",
        )

    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(description="docstore public cache benchmark")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-generate", action="store_true",
                        help="Skip corpus generation — use existing files in the directory")
    parser.add_argument("--keep-cache", action="store_true", help="Do not delete <directory>/.docstore")
    parser.add_argument("--schema", default=None, help="Schema name (default: invoice_benchmark)")
    parser.add_argument("--ask", action="store_true", help="Describe schema fields interactively")
    parser.add_argument("--glob", default=None,
                        help="File glob pattern (default: invoice_*.txt, or * when --no-generate is set)")
    parser.add_argument(
        "--provider",
        choices=["anthropic", "openai", "groq", "gemini"],
        default=DEFAULT_PROVIDER,
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--usd-per-mtok", type=float, default=1.0)
    parser.add_argument("--output", choices=["table", "json"], default="table")
    args = parser.parse_args()

    # Resolve glob: explicit > infer from --no-generate > invoice default
    glob = args.glob or ("*" if args.no_generate else "invoice_*.txt")

    # Resolve schema
    schema_name = args.schema
    schema_fields: dict[str, str] | None = None
    if args.ask or (schema_name and schema_name != BENCHMARK_SCHEMA_NAME):
        if not schema_name:
            schema_name = input("Schema name: ").strip() or "benchmark_schema"
        description = input(f"Describe the fields to extract from {args.directory.name}: ").strip()
        client = create_llm_client(args.provider, args.model)
        store = DocStore(root=args.directory / ".docstore")
        from docstore.agents.orchestrator import elicit_schema
        descriptor = elicit_schema(description, store.list_schemas(), client=client, name=schema_name)
        schema_name = descriptor.name
        schema_fields = dict(descriptor.fields)

    report = run_benchmark(
        args.directory,
        count=args.count,
        seed=args.seed,
        provider=args.provider,
        model=args.model,
        generate=not args.no_generate,
        fresh=not args.keep_cache,
        usd_per_mtok=args.usd_per_mtok,
        schema_name=schema_name,
        schema_fields=schema_fields,
        glob=glob,
    )

    if args.output == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_table(report)


if __name__ == "__main__":
    main()
