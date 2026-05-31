"""
Validator subagent — checks that extracted fields are plausible.

One LLM call per document per schema, only on cache miss.
Returns {valid: bool, issues: list[str]}.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..llm import LLMClient, create_llm_client
from ..schema import SchemaDescriptor


MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """\
You are a strict data quality validator. Return ONLY a JSON object:
  {"valid": <bool>, "issues": [<string>, ...]}

Flag a field as an issue ONLY if one of these is clearly true:
  - Required field is null when the source document clearly contains it.
  - Type mismatch: value type does not match the schema's declared type.
  - The value is not present in or derivable from the source text.

DO NOT flag:
  - Math reconciliation (subtotal vs total, tax inclusion). These are not your concern.
  - The internal shape of nested objects when the schema declares list[object].
  - Stylistic differences (uppercase/lowercase, date format) if the value is correct.
  - Anything you have to reason about beyond "is this value in the source".

If you are uncertain, the value is valid. Default to {"valid": true, "issues": []}.\
"""


def validate(
    extracted: dict[str, Any],
    descriptor: SchemaDescriptor,
    original_text: str,
    client: LLMClient | None = None,
    model: str = MODEL,
) -> tuple[bool, list[str], int]:
    """
    Validate extracted data against the schema and source text.

    Returns:
        (valid, issues, tokens_used)
    """
    if client is None:
        client = create_llm_client(model=model)

    user_message = f"""Schema fields: {json.dumps(descriptor.fields, indent=2)}

Extracted data: {json.dumps(extracted, indent=2)}

Source document excerpt (first 2000 chars):
---
{original_text[:2000]}
---

Is the extracted data valid and plausible?"""

    response = client.complete(
        system=SYSTEM_PROMPT,
        max_tokens=512,
        temperature=0,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.text
    tokens_used = response.tokens_used

    # Strip fenced code blocks
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    # Extract the first complete JSON object, ignoring any trailing text
    decoder = json.JSONDecoder()
    start = raw.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in validator response: {raw!r}")
    result, _ = decoder.raw_decode(raw, start)
    return result.get("valid", False), result.get("issues", []), tokens_used
