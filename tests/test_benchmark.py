from __future__ import annotations

import json

from docstore.llm import LLMResponse
from scripts import benchmark
from scripts.generate_txt_invoices import generate_corpus


class FakeLLM:
    model = "fake-benchmark-model"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        return LLMResponse(
            text=json.dumps(
                {
                    "vendor": "Acme Logistics LLC",
                    "invoice_no": f"INV-FAKE-{self.calls}",
                    "amount": 123.45,
                    "currency": "USD",
                    "due_date": "2026-01-31",
                    "paid": False,
                }
            ),
            input_tokens=20,
            output_tokens=5,
            model=self.model,
        )


def test_benchmark_schema_is_fixed():
    descriptor = benchmark.benchmark_schema()

    assert descriptor.name == "invoice_benchmark"
    assert descriptor.fields == {
        "vendor": "string",
        "invoice_no": "string",
        "amount": "number",
        "currency": "string",
        "due_date": "date",
        "paid": "boolean",
    }


def test_generate_corpus_writes_ground_truth(tmp_path):
    records = generate_corpus(tmp_path, count=3, seed=7)

    invoices = sorted(tmp_path.glob("invoice_*.txt"))
    ground_truth = tmp_path / "ground_truth.jsonl"
    lines = [json.loads(line) for line in ground_truth.read_text().splitlines()]

    assert len(records) == 3
    assert len(invoices) == 3
    assert len(lines) == 3
    assert lines[0]["file"] == "invoice_0001.txt"
    assert set(lines[0]["data"]) == {
        "vendor",
        "amount",
        "currency",
        "due_date",
        "paid",
        "invoice_no",
    }


def test_summarize_extract_math():
    class Result:
        def __init__(self, cache_hit, tokens_used, tokens_saved):
            self.cache_hit = cache_hit
            self.tokens_used = tokens_used
            self.tokens_saved = tokens_saved

    summary = benchmark.summarize_extract(
        "example",
        [
            Result(False, 100, 0),
            Result(False, 50, 0),
            Result(True, 50, 50),
        ],
        elapsed_seconds=1.23456,
        usd_per_mtok=2.0,
    )

    assert summary == {
        "scenario": "example",
        "documents": 3,
        "cache_hits": 1,
        "cache_misses": 2,
        "tokens_used": 150,
        "tokens_saved": 50,
        "savings_percent": 25.0,
        "elapsed_seconds": 1.235,
        "estimated_cost_usd": 0.0003,
    }


def test_json_output_shape_is_parseable(tmp_path, monkeypatch):
    fake = FakeLLM()

    monkeypatch.setattr(benchmark, "create_llm_client", lambda provider, model: fake)

    report = benchmark.run_benchmark(
        tmp_path,
        count=1,
        seed=9,
        provider="anthropic",
        model="fake-benchmark-model",
    )

    encoded = json.dumps(report, sort_keys=True)
    decoded = json.loads(encoded)

    assert decoded["corpus"]["documents"] == 1
    assert [row["scenario"] for row in decoded["scenarios"]] == [
        "cold_extract",
        "warm_extract",
        "cached_query",
    ]


def test_fake_llm_cold_then_warm_cache_behavior(tmp_path, monkeypatch):
    fake = FakeLLM()

    monkeypatch.setattr(benchmark, "create_llm_client", lambda provider, model: fake)

    report = benchmark.run_benchmark(
        tmp_path,
        count=2,
        seed=11,
        provider="anthropic",
        model="fake-benchmark-model",
    )
    cold, warm, query = report["scenarios"]

    assert fake.calls == 2
    assert cold["documents"] == 2
    assert cold["cache_hits"] == 0
    assert cold["cache_misses"] == 2
    assert cold["tokens_used"] == 50
    assert warm["documents"] == 2
    assert warm["cache_hits"] == 2
    assert warm["cache_misses"] == 0
    assert warm["tokens_used"] == 0
    assert warm["tokens_saved"] == 50
    assert query["scenario"] == "cached_query"
    assert query["tokens_used"] == 0
