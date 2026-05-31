"""
Differ subagent — compares two extraction results for the same document.

Called explicitly by the user or orchestrator when a file has changed
and a cached result already exists.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from ..schema import DiffResult, SchemaDescriptor


MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """\
You are a precise data diff analyst. Given two versions of extracted data \
from the same document, identify what changed. \
Return ONLY a JSON object with:
  "changed_fields": list of field names that changed
  "summary": one sentence describing the most important change
Be factual. Only report fields that actually changed.\
"""


def diff(
    previous: dict[str, Any],
    current: dict[str, Any],
    descriptor: SchemaDescriptor,
    file_path: str,
    previous_hash: str,
    current_hash: str,
    client: anthropic.Anthropic | None = None,
    model: str = MODEL,
) -> DiffResult:
    """
    Compare two extraction results and return a structured diff.
    """
    if client is None:
        client = anthropic.Anthropic()

    # Fast path: exact match
    if previous == current:
        return DiffResult(
            schema_name=descriptor.name,
            file_path=file_path,
            changed_fields=[],
            previous=previous,
            current=current,
            summary="No changes detected.",
            previous_hash=previous_hash,
            current_hash=current_hash,
        )

    # Compute structural diff without LLM first
    changed_fields = [
        k for k in set(list(previous.keys()) + list(current.keys()))
        if previous.get(k) != current.get(k)
    ]

    user_message = f"""Schema: {json.dumps(descriptor.fields, indent=2)}

Previous version:
{json.dumps(previous, indent=2)}

Current version:
{json.dumps(current, indent=2)}

Changed fields (detected): {changed_fields}

Summarise the changes."""

    response = client.messages.create(
        model=model,
        max_tokens=256,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    import re
    import json as _json
    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    _decoder = _json.JSONDecoder()
    _start = raw.find("{")
    if _start == -1:
        raise ValueError(f"No JSON object found in differ response: {raw!r}")
    result, _ = _decoder.raw_decode(raw, _start)

    return DiffResult(
        schema_name=descriptor.name,
        file_path=file_path,
        changed_fields=result.get("changed_fields", changed_fields),
        previous=previous,
        current=current,
        summary=result.get("summary", "Changes detected."),
        previous_hash=previous_hash,
        current_hash=current_hash,
    )
