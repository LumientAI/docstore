"""
Validator subagent — checks that extracted fields are plausible.

One LLM call per document per schema, only on cache miss.
Returns {valid: bool, issues: list[str]}.
"""

from __future__ import annotations

import json
import re
from typing import Any

import anthropic

from ..schema import SchemaDescriptor


MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """\
You are a data quality validator. Given extracted data and the source schema, \
check whether the values are plausible and internally consistent. \
Return ONLY a JSON object with two fields:
  "valid": true or false
  "issues": list of strings describing any problems found (empty list if valid)
Be strict but fair. Flag nulls for required-looking fields, \
implausible values, and type mismatches. Do not invent issues.\
"""


def validate(
    extracted: dict[str, Any],
    descriptor: SchemaDescriptor,
    original_text: str,
    client: anthropic.Anthropic | None = None,
    model: str = MODEL,
) -> tuple[bool, list[str], int]:
    """
    Validate extracted data against the schema and source text.

    Returns:
        (valid, issues, tokens_used)
    """
    if client is None:
        client = anthropic.Anthropic()

    user_message = f"""Schema fields: {json.dumps(descriptor.fields, indent=2)}

Extracted data: {json.dumps(extracted, indent=2)}

Source document excerpt (first 2000 chars):
---
{original_text[:2000]}
---

Is the extracted data valid and plausible?"""

    response = client.messages.create(
        model=model,
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    tokens_used = response.usage.input_tokens + response.usage.output_tokens

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
