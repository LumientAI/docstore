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
from scripts.generate_txt_invoices import generate_corpus


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
DIRECT_CONTEXT_SYSTEM = """\
You answer questions over invoice documents. Return ONLY valid JSON.\
"""
DIRECT_CONTEXT_QUERY = """\
Find every unpaid invoice in the documents below. Return a JSON array where \
each item has invoice_no, vendor, amount, currency, and due_date.\
"""


def benchmark_schema() -> SchemaDescriptor:
    return SchemaDescriptor(name=BENCHMARK_SCHEMA_NAME, fields=BENCHMARK_SCHEMA_FIELDS)


def baseline_tokens(directory: Path, glob: str = "*.txt") -> int:
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


def summarize_direct_context_query(
    scenario: str,
    documents: int,
    returned_records: int,
    elapsed_seconds: float,
    tokens_used: int,
    usd_per_mtok: float,
) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "documents": documents,
        "returned_records": returned_records,
        "cache_hits": 0,
        "cache_misses": 0,
        "tokens_used": tokens_used,
        "tokens_saved": 0,
        "savings_percent": 0.0,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "estimated_cost_usd": round(tokens_used / 1_000_000 * usd_per_mtok, 6),
    }


def run_extract_scenario(
    scenario: str,
    directory: Path,
    descriptor: SchemaDescriptor,
    store: DocStore,
    client,
    model: str,
    usd_per_mtok: float,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    results = orchestrator.run_directory(
        directory,
        descriptor,
        store,
        client,
        model,
        glob="invoice_*.txt",
        progress=False,
    )
    return summarize_extract(scenario, results, time.perf_counter() - t0, usd_per_mtok)


def run_cached_query_scenario(
    descriptor: SchemaDescriptor,
    store: DocStore,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    unpaid = store.query(descriptor.name, lambda r: r.data.get("paid") is False)
    return summarize_query("cached_query", len(unpaid), time.perf_counter() - t0)


def build_direct_context(directory: Path, glob: str = "invoice_*.txt") -> tuple[str, int]:
    parts = []
    documents = 0
    for f in sorted(directory.glob(glob)):
        if f.is_file() and f.suffix.lower() in SUPPORTED_SUFFIXES:
            text = parser_agent.parse(f)
            parts.append(f"<document path={json.dumps(str(f))}>\n{text}\n</document>")
            documents += 1
    return "\n\n".join(parts), documents


def count_json_records(raw: str) -> int:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
        cleaned = cleaned.removesuffix("```").strip()

    start_candidates = [i for i in (cleaned.find("["), cleaned.find("{")) if i != -1]
    if not start_candidates:
        return 0

    try:
        value, _ = json.JSONDecoder().raw_decode(cleaned, min(start_candidates))
    except json.JSONDecodeError:
        return 0

    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("invoices", "results", "items", "data"):
            nested = value.get(key)
            if isinstance(nested, list):
                return len(nested)
        return 1
    return 0


def run_direct_context_query_scenario(
    directory: Path,
    client,
    model: str,
    usd_per_mtok: float,
) -> dict[str, Any]:
    context, documents = build_direct_context(directory)
    t0 = time.perf_counter()
    response = client.complete(
        system=DIRECT_CONTEXT_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": f"{DIRECT_CONTEXT_QUERY}\n\n{context}",
            }
        ],
        max_tokens=2048,
        temperature=0,
    )
    elapsed = time.perf_counter() - t0
    return summarize_direct_context_query(
        "direct_context_query",
        documents,
        count_json_records(response.text),
        elapsed,
        response.tokens_used,
        usd_per_mtok,
    )


def summarize_repeated_query_projection(
    direct_context: dict[str, Any] | None,
    cached_query: dict[str, Any],
    query_repetitions: int,
) -> dict[str, Any]:
    cached_tokens = cached_query["tokens_used"] * query_repetitions
    cached_cost = round(cached_query["estimated_cost_usd"] * query_repetitions, 6)
    cached_time = round(cached_query["elapsed_seconds"] * query_repetitions, 3)

    projection: dict[str, Any] = {
        "query_repetitions": query_repetitions,
        "cached_query": {
            "tokens_used": cached_tokens,
            "estimated_cost_usd": cached_cost,
            "elapsed_seconds": cached_time,
        },
        "direct_context_query": None,
    }
    if direct_context is None:
        return projection

    direct_tokens = direct_context["tokens_used"] * query_repetitions
    direct_cost = round(direct_context["estimated_cost_usd"] * query_repetitions, 6)
    direct_time = round(direct_context["elapsed_seconds"] * query_repetitions, 3)
    projection["direct_context_query"] = {
        "tokens_used": direct_tokens,
        "estimated_cost_usd": direct_cost,
        "elapsed_seconds": direct_time,
    }
    projection["tokens_saved_by_cache"] = max(direct_tokens - cached_tokens, 0)
    projection["cost_saved_by_cache_usd"] = round(max(direct_cost - cached_cost, 0), 6)
    projection["seconds_saved_by_cache"] = round(max(direct_time - cached_time, 0), 3)
    return projection


def prepare_corpus(directory: Path, count: int, seed: int, generate: bool) -> int:
    if generate:
        return len(generate_corpus(directory, count=count, seed=seed))
    return len(list(directory.glob("invoice_*.txt")))


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
    query_repetitions: int = 3,
    skip_direct_baseline: bool = False,
) -> dict[str, Any]:
    document_count = prepare_corpus(directory, count, seed, generate)
    store_dir = directory / ".docstore"
    if fresh and store_dir.exists():
        shutil.rmtree(store_dir)

    descriptor = benchmark_schema()
    store = DocStore(root=store_dir)
    model = resolve_model(provider, model)
    client = create_llm_client(provider, model)

    cold = run_extract_scenario(
        "cold_extract", directory, descriptor, store, client, model, usd_per_mtok
    )
    warm = run_extract_scenario(
        "warm_extract", directory, descriptor, store, client, model, usd_per_mtok
    )
    direct = None
    if not skip_direct_baseline:
        direct = run_direct_context_query_scenario(directory, client, model, usd_per_mtok)
    query = run_cached_query_scenario(descriptor, store)
    scenarios = [cold, warm]
    if direct is not None:
        scenarios.append(direct)
    scenarios.append(query)

    return {
        "corpus": {
            "directory": str(directory),
            "documents": document_count,
            "ground_truth": str(directory / "ground_truth.jsonl"),
            "baseline_tokens_per_full_read": baseline_tokens(directory),
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
        "scenarios": scenarios,
        "projection": summarize_repeated_query_projection(direct, query, query_repetitions),
    }


def print_table(report: dict[str, Any]) -> None:
    corpus = report["corpus"]
    llm = report["llm"]
    rprint(
        f"\n[bold]docstore benchmark[/bold] "
        f"({corpus['documents']} synthetic invoices, {llm['provider']}:{llm['model']})"
    )
    rprint(f"[dim]Baseline full-read tokens: {corpus['baseline_tokens_per_full_read']:,}[/dim]\n")

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

    projection = report.get("projection", {})
    direct_projection = projection.get("direct_context_query")
    cached_projection = projection.get("cached_query", {})
    repetitions = projection.get("query_repetitions", 0)
    if direct_projection is not None:
        rprint(
            f"\n[bold]Repeated query projection[/bold] ({repetitions} runs): "
            f"direct context uses {direct_projection['tokens_used']:,} tokens "
            f"(${direct_projection['estimated_cost_usd']:.6f}); "
            f"cached query uses {cached_projection.get('tokens_used', 0):,} tokens "
            f"(${cached_projection.get('estimated_cost_usd', 0):.6f})."
        )
        rprint(
            f"[dim]Projected cache savings: "
            f"{projection.get('tokens_saved_by_cache', 0):,} tokens, "
            f"${projection.get('cost_saved_by_cache_usd', 0):.6f}[/dim]"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="docstore public cache benchmark")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-generate", action="store_true", help="Use existing invoice_*.txt files")
    parser.add_argument("--keep-cache", action="store_true", help="Do not delete <directory>/.docstore")
    parser.add_argument(
        "--provider",
        choices=["anthropic", "openai", "groq", "gemini"],
        default=DEFAULT_PROVIDER,
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--usd-per-mtok", type=float, default=1.0)
    parser.add_argument(
        "--query-repetitions",
        type=int,
        default=3,
        help="Projected number of repeated questions over the same corpus",
    )
    parser.add_argument(
        "--skip-direct-baseline",
        action="store_true",
        help="Skip the direct LLM full-context query baseline",
    )
    parser.add_argument("--output", choices=["table", "json"], default="table")
    args = parser.parse_args()

    report = run_benchmark(
        args.directory,
        count=args.count,
        seed=args.seed,
        provider=args.provider,
        model=args.model,
        generate=not args.no_generate,
        fresh=not args.keep_cache,
        usd_per_mtok=args.usd_per_mtok,
        query_repetitions=args.query_repetitions,
        skip_direct_baseline=args.skip_direct_baseline,
    )

    if args.output == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_table(report)


if __name__ == "__main__":
    main()
