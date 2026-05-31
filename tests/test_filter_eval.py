"""Tests for the filter AST evaluator — no LLM calls."""

from __future__ import annotations

import pytest

from docstore.store import evaluate_filter


# A realistic-shaped record for tests
SAMPLE = {
    "vendor_name": "ACME LOGISTICS LLC",
    "total_amount": 1150.72,
    "currency": "USD",
    "due_date": "2026-02-16",
    "is_paid": False,
    "tags": ["urgent", "north-america"],
    "notes": None,
}


# ── Leaf comparisons ─────────────────────────────────────────────────────────


def test_eq_match():
    assert evaluate_filter({"field": "currency", "op": "=", "value": "USD"}, SAMPLE) is True


def test_eq_no_match():
    assert evaluate_filter({"field": "currency", "op": "=", "value": "EUR"}, SAMPLE) is False


def test_neq_match():
    assert evaluate_filter({"field": "is_paid", "op": "!=", "value": True}, SAMPLE) is True


def test_gt_lt_ge_le():
    assert evaluate_filter({"field": "total_amount", "op": ">", "value": 1000}, SAMPLE) is True
    assert evaluate_filter({"field": "total_amount", "op": "<", "value": 1000}, SAMPLE) is False
    assert evaluate_filter({"field": "total_amount", "op": ">=", "value": 1150.72}, SAMPLE) is True
    assert evaluate_filter({"field": "total_amount", "op": "<=", "value": 1150.72}, SAMPLE) is True


def test_contains_on_string():
    assert evaluate_filter({"field": "vendor_name", "op": "contains", "value": "ACME"}, SAMPLE) is True
    assert evaluate_filter({"field": "vendor_name", "op": "contains", "value": "FedEx"}, SAMPLE) is False


def test_contains_on_list():
    assert evaluate_filter({"field": "tags", "op": "contains", "value": "urgent"}, SAMPLE) is True


def test_in_match():
    assert evaluate_filter({"field": "currency", "op": "in", "value": ["USD", "EUR"]}, SAMPLE) is True
    assert evaluate_filter({"field": "currency", "op": "in", "value": ["GBP", "JPY"]}, SAMPLE) is False


def test_is_null():
    assert evaluate_filter({"field": "notes", "op": "is_null"}, SAMPLE) is True
    assert evaluate_filter({"field": "vendor_name", "op": "is_null"}, SAMPLE) is False


# ── Null handling on ordered comparisons ─────────────────────────────────────


def test_null_field_never_matches_ordered_comparison():
    """`notes` is None — ordered ops should return False, NOT raise.
    Otherwise the evaluator crashes on incomplete records."""
    for op in (">", "<", ">=", "<="):
        assert evaluate_filter({"field": "notes", "op": op, "value": 5}, SAMPLE) is False


def test_missing_field_treated_as_null():
    """Filtering on a field the record doesn't have shouldn't error."""
    assert evaluate_filter({"field": "nonexistent", "op": "is_null"}, SAMPLE) is True
    assert evaluate_filter({"field": "nonexistent", "op": "=", "value": "x"}, SAMPLE) is False


# ── Compound nodes ──────────────────────────────────────────────────────────


def test_and_both_true():
    ast = {"and": [
        {"field": "is_paid", "op": "=", "value": False},
        {"field": "total_amount", "op": ">", "value": 1000},
    ]}
    assert evaluate_filter(ast, SAMPLE) is True


def test_and_short_circuits_on_false():
    ast = {"and": [
        {"field": "is_paid", "op": "=", "value": True},  # false
        {"field": "total_amount", "op": ">", "value": 1000},
    ]}
    assert evaluate_filter(ast, SAMPLE) is False


def test_or_any_true():
    ast = {"or": [
        {"field": "currency", "op": "=", "value": "EUR"},  # false
        {"field": "currency", "op": "=", "value": "USD"},  # true
    ]}
    assert evaluate_filter(ast, SAMPLE) is True


def test_not_inverts():
    ast = {"not": {"field": "is_paid", "op": "=", "value": False}}
    assert evaluate_filter(ast, SAMPLE) is False


def test_nested_compound():
    """(currency=USD AND amount>1000) OR is_paid=true"""
    ast = {"or": [
        {"and": [
            {"field": "currency", "op": "=", "value": "USD"},
            {"field": "total_amount", "op": ">", "value": 1000},
        ]},
        {"field": "is_paid", "op": "=", "value": True},
    ]}
    assert evaluate_filter(ast, SAMPLE) is True


# ── Error-shaped nodes ──────────────────────────────────────────────────────


def test_error_node_returns_false():
    """When the compiler couldn't map the question, it returns {"error": ...}
    Evaluating that should be a no-match, not a crash."""
    assert evaluate_filter({"error": "Unknown field 'magic_number'"}, SAMPLE) is False


def test_unknown_operator_raises():
    with pytest.raises(ValueError, match="Unknown filter operator"):
        evaluate_filter({"field": "currency", "op": "regex", "value": ".*"}, SAMPLE)
