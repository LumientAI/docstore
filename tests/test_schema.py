"""Tests for schema primitives."""

from docstore.schema import ExtractionSchema, SchemaDescriptor


def test_descriptor_version_is_deterministic():
    d1 = SchemaDescriptor(name="s", fields={"a": "string", "b": "number"})
    d2 = SchemaDescriptor(name="s", fields={"a": "string", "b": "number"})
    assert d1.version == d2.version


def test_descriptor_version_changes_on_field_add():
    d1 = SchemaDescriptor(name="s", fields={"a": "string"})
    d2 = SchemaDescriptor(name="s", fields={"a": "string", "b": "number"})
    assert d1.version != d2.version


def test_descriptor_version_changes_on_field_rename():
    d1 = SchemaDescriptor(name="s", fields={"amount": "number"})
    d2 = SchemaDescriptor(name="s", fields={"total": "number"})
    assert d1.version != d2.version


def test_extraction_schema_to_descriptor():
    class InvoiceSchema(ExtractionSchema):
        vendor: str
        amount: float
        paid: bool

    descriptor = InvoiceSchema.to_descriptor()
    assert descriptor.name == "InvoiceSchema"
    assert descriptor.fields["vendor"] == "string"
    assert descriptor.fields["amount"] == "number"
    assert descriptor.fields["paid"] == "boolean"


def test_descriptor_prompt_fragment():
    d = SchemaDescriptor(name="s", fields={"vendor": "string", "amount": "number"})
    fragment = d.to_prompt_fragment()
    assert "vendor" in fragment
    assert "amount" in fragment


def test_cache_token():
    d = SchemaDescriptor(name="invoice_schema", fields={"vendor": "string"})
    token = d.cache_token()
    assert token.startswith("invoice_schema:")
    assert len(token) > 15
