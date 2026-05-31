from __future__ import annotations

from docstore.agents import differ, extractor, orchestrator, validator
from docstore.llm import LLMResponse
from docstore.schema import SchemaDescriptor


class FakeLLM:
    model = "fake-model"

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = responses or []
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        text = self.responses.pop(0)
        return LLMResponse(text=text, input_tokens=10, output_tokens=5, model=self.model)


def test_extractor_uses_llm_wrapper_and_parses_json():
    client = FakeLLM(['{"vendor": "Acme"}'])
    descriptor = SchemaDescriptor(name="invoice", fields={"vendor": "string"})

    data, tokens = extractor.extract("Vendor: Acme", descriptor, client)

    assert data == {"vendor": "Acme"}
    assert tokens == 15
    assert client.calls[0]["system"] == extractor.SYSTEM_PROMPT
    assert client.calls[0]["max_tokens"] == 1024


def test_validator_uses_llm_wrapper_and_parses_json():
    client = FakeLLM(['{"valid": true, "issues": []}'])
    descriptor = SchemaDescriptor(name="invoice", fields={"vendor": "string"})

    valid, issues, tokens = validator.validate(
        {"vendor": "Acme"}, descriptor, "Vendor: Acme", client
    )

    assert valid is True
    assert issues == []
    assert tokens == 15
    assert client.calls[0]["temperature"] == 0


def test_differ_fast_path_skips_llm():
    client = FakeLLM([])
    descriptor = SchemaDescriptor(name="invoice", fields={"vendor": "string"})

    result = differ.diff(
        previous={"vendor": "Acme"},
        current={"vendor": "Acme"},
        descriptor=descriptor,
        file_path="invoice.txt",
        previous_hash="old",
        current_hash="new",
        client=client,
    )

    assert result.changed_fields == []
    assert client.calls == []


def test_schema_elicitation_uses_temperature_zero():
    client = FakeLLM(['{"vendor": "string"}', "vendor_invoice"])

    descriptor = orchestrator.elicit_schema("vendor", {}, client)

    assert descriptor.name == "vendor_invoice"
    assert descriptor.fields == {"vendor": "string"}
    assert [call["temperature"] for call in client.calls] == [0, 0]
