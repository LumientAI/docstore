"""
Invoice extraction example.

Demonstrates:
1. Defining a schema via ExtractionSchema subclass
2. Running extraction over a directory
3. Querying without LLM calls
4. Diffing a changed document
"""

from pathlib import Path

from dotenv import load_dotenv

from docstore import DocStore, ExtractionSchema

load_dotenv()


# ── Define schema ──────────────────────────────────────────────────────────

class InvoiceSchema(ExtractionSchema):
    vendor: str
    amount: float
    currency: str
    due_date: str
    paid: bool
    line_items: list


# ── Run extraction ─────────────────────────────────────────────────────────

def main():
    from docstore.agents.orchestrator import run_directory
    from docstore.llm import create_llm_client

    invoices_dir = Path("./sample_invoices")
    if not invoices_dir.exists():
        print(f"Create a directory at {invoices_dir} with some .txt or .pdf invoices.")
        return

    store = DocStore(root=invoices_dir / ".docstore")
    client = create_llm_client()
    descriptor = InvoiceSchema.to_descriptor()

    print(f"Schema: {descriptor.name} v{descriptor.version}")
    print(f"Fields: {list(descriptor.fields.keys())}\n")

    # Run pipeline — cache misses on first run
    print("Run 1 (cold cache):")
    results = run_directory(invoices_dir, descriptor, store, client)
    for r in results:
        status = "HIT" if r.cache_hit else "MISS"
        print(f"  {Path(r.file_path).name:<30} [{status}] tokens={r.tokens_used}")

    print("\nRun 2 (warm cache):")
    results = run_directory(invoices_dir, descriptor, store, client)
    for r in results:
        status = "HIT" if r.cache_hit else "MISS"
        saved = f"saved={r.tokens_saved}" if r.cache_hit else ""
        print(f"  {Path(r.file_path).name:<30} [{status}] {saved}")

    # Query without LLM — find unpaid invoices
    print("\nUnpaid invoices:")
    unpaid = store.query(descriptor.name, lambda r: r.data.get("paid") is False)
    for r in unpaid:
        print(f"  {Path(r.file_path).name}: {r.data.get('vendor')} — {r.data.get('amount')} {r.data.get('currency')}")

    # Stats
    s = store.stats()
    print("\nStats:")
    print(f"  Documents              : {s['total_entries']}")
    print(f"  Tokens absorbed by cache: {s['total_tokens_cached']:,}")
    print(f"  Cost to re-extract all : ${s['estimated_cost_to_recompute_usd']:.4f}")


if __name__ == "__main__":
    main()
