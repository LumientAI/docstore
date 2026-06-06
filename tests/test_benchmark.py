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
        if kwargs["system"] == benchmark.DIRECT_CONTEXT_SYSTEM:
            return LLMResponse(
                text=json.dumps(
                    [
                        {
                            "vendor": "Acme Logistics LLC",
                            "invoice_no": "INV-DIRECT-1",
                            "amount": 123.45,
                            "currency": "USD",
                            "due_date": "2026-01-31",
                        },
                        {
                            "vendor": "Cascadia Cloud Services",
                            "invoice_no": "INV-DIRECT-2",
                            "amount": 456.78,
                            "currency": "USD",
                            "due_date": "2026-02-28",
                        },
                    ]
                ),
                input_tokens=200,
                output_tokens=30,
                model=self.model,
            )
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


def test_count_json_records_accepts_common_shapes():
    assert benchmark.count_json_records('[{"invoice_no": "1"}, {"invoice_no": "2"}]') == 2
    assert benchmark.count_json_records('{"invoices": [{"invoice_no": "1"}]}') == 1
    assert benchmark.count_json_records("not json") == 0


def test_projection_math_with_direct_context():
    projection = benchmark.summarize_repeated_query_projection(
        {
            "tokens_used": 230,
            "estimated_cost_usd": 0.00023,
            "elapsed_seconds": 1.2,
        },
        {
            "tokens_used": 0,
            "estimated_cost_usd": 0.0,
            "elapsed_seconds": 0.01,
        },
        query_repetitions=3,
    )

    assert projection == {
        "query_repetitions": 3,
        "cached_query": {
            "tokens_used": 0,
            "estimated_cost_usd": 0.0,
            "elapsed_seconds": 0.03,
        },
        "direct_context_query": {
            "tokens_used": 690,
            "estimated_cost_usd": 0.00069,
            "elapsed_seconds": 3.6,
        },
        "tokens_saved_by_cache": 690,
        "cost_saved_by_cache_usd": 0.00069,
        "seconds_saved_by_cache": 3.57,
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
        "direct_context_query",
        "cached_query",
    ]
    assert decoded["projection"]["query_repetitions"] == 3


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
    cold, warm, direct, cached_query = report["scenarios"]

    assert fake.calls == 3
    assert cold["documents"] == 2
    assert cold["cache_hits"] == 0
    assert cold["cache_misses"] == 2
    assert cold["tokens_used"] == 50
    assert warm["documents"] == 2
    assert warm["cache_hits"] == 2
    assert warm["cache_misses"] == 0
    assert warm["tokens_used"] == 0
    assert warm["tokens_saved"] == 50
    assert direct["scenario"] == "direct_context_query"
    assert direct["tokens_used"] == 230
    assert direct["returned_records"] == 2
    assert cached_query["scenario"] == "cached_query"
    assert cached_query["tokens_used"] == 0
    assert report["projection"]["tokens_saved_by_cache"] == 690


def test_skip_direct_baseline_keeps_original_three_scenarios(tmp_path, monkeypatch):
    fake = FakeLLM()

    monkeypatch.setattr(benchmark, "create_llm_client", lambda provider, model: fake)

    report = benchmark.run_benchmark(
        tmp_path,
        count=2,
        seed=11,
        provider="anthropic",
        model="fake-benchmark-model",
        skip_direct_baseline=True,
    )

    assert fake.calls == 2
    assert [row["scenario"] for row in report["scenarios"]] == [
        "cold_extract",
        "warm_extract",
        "cached_query",
    ]
    assert report["projection"]["query_repetitions"] == 3
    assert report["projection"]["cached_query"]["tokens_used"] == 0
    assert report["projection"]["cached_query"]["estimated_cost_usd"] == 0.0
    assert report["projection"]["direct_context_query"] is None
