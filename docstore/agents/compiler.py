"""
Compiler subagent — translates a natural-language question into a JSON
filter AST that can be evaluated against cached extraction results.

One LLM call per question. No code execution; the LLM emits structured
JSON that a pure-Python evaluator interprets.
"""

from __future__ import annotations

import json
import re
from typing import Any

import anthropic


MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT_TEMPLATE = """\
You compile natural-language questions into a JSON filter AST. \
The user has cached structured records under a known schema. \
Translate their question into a filter that selects the matching records.

Available fields (use these EXACT names — do not invent or rename):
{fields_block}

Filter AST grammar:
  Comparison: {{"field": "<name>", "op": "<op>", "value": <literal>}}
    op ∈ {{=, !=, >, <, >=, <=, contains, in, is_null}}
    "is_null" omits "value". "in" takes a list value.
  Compound:   {{"and": [<filter>, ...]}} | {{"or": [<filter>, ...]}} | {{"not": <filter>}}

Rules:
  - Only use fields from the list above. If the question references a field
    that isn't there, return {{"error": "explanation"}} instead of a filter.
  - Map synonyms to the canonical field name (e.g. "paid" → "is_paid" if that
    is the actual field).
  - For boolean fields, use true/false (lowercase JSON literals).
  - For dates, use ISO 8601 strings (YYYY-MM-DD).
  - Return ONLY the JSON object. No prose, no markdown, no explanation.\
"""


def _system_prompt(schema_fields: dict[str, str]) -> str:
    fields_block = "\n".join(f"  - {name}: {ftype}" for name, ftype in schema_fields.items())
    return SYSTEM_PROMPT_TEMPLATE.format(fields_block=fields_block)


def compile_filter(
    question: str,
    schema_fields: dict[str, str],
    client: anthropic.Anthropic | None = None,
    model: str = MODEL,
) -> dict[str, Any]:
    """
    Compile a natural-language question into a filter AST.

    Returns the AST dict on success, or {"error": "..."} if the LLM couldn't
    map the question to the available fields.
    """
    if client is None:
        client = anthropic.Anthropic()

    response = client.messages.create(
        model=model,
        max_tokens=512,
        temperature=0,
        system=_system_prompt(schema_fields),
        messages=[{"role": "user", "content": question}],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    decoder = json.JSONDecoder()
    start = raw.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in compiler response: {raw!r}")
    ast, _ = decoder.raw_decode(raw, start)
    return ast


def filter_to_string(node: dict[str, Any]) -> str:
    """Render a filter AST as a human-readable SQL-ish string (for display)."""
    if "and" in node:
        return " AND ".join(filter_to_string(c) for c in node["and"])
    if "or" in node:
        return "(" + " OR ".join(filter_to_string(c) for c in node["or"]) + ")"
    if "not" in node:
        return f"NOT {filter_to_string(node['not'])}"
    if "error" in node:
        return f"<error: {node['error']}>"
    field, op = node["field"], node["op"]
    if op == "is_null":
        return f"{field} IS NULL"
    value = node.get("value")
    if op == "in":
        return f"{field} IN {value}"
    return f"{field} {op} {value!r}"
