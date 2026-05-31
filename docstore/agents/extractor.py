"""
Extractor subagent — extracts structured fields from document text.

One LLM call per document per schema.
System prompt is intentionally narrow: return only JSON.
"""

from __future__ import annotations

import json
import re

import anthropic

from docstore.schema import SchemaDescriptor


MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """\
You are a precise data extractor. Given a document and a target schema, \
extract the requested fields and return ONLY a valid JSON object matching \
the schema exactly. No prose, no markdown, no explanation. \
If a field cannot be found, use null. \
Never invent values that are not present in the document.\
"""


def extract(
    text: str,
    descriptor: SchemaDescriptor,
    client: anthropic.Anthropic | None = None,
    model: str = MODEL,
) -> tuple[dict, int]:
    """
    Extract fields from text according to descriptor.

    Returns:
        (extracted_dict, tokens_used)
    """
    if client is None:
        client = anthropic.Anthropic()

    user_message = f"""Document:
---
{text}
---

Extract the following fields and return a JSON object:
{descriptor.to_prompt_fragment()}

Return ONLY the JSON object."""

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    tokens_used = response.usage.input_tokens + response.usage.output_tokens

    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    decoder = json.JSONDecoder()
    start = raw.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in extractor response: {raw!r}")
    extracted, _ = decoder.raw_decode(raw, start)
    return extracted, tokens_used
