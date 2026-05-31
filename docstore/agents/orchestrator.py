"""
Orchestrator — elicits schemas from natural language and coordinates the pipeline.

Two responsibilities:
1. Schema elicitation: turn a user's natural language description into a
   canonical SchemaDescriptor, with deduplication against existing schemas.
2. Pipeline coordination: run parser → extractor → validator for a single file,
   with cache hit/miss logic.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic
from tqdm import tqdm

from ..schema import ExtractionResult, SchemaDescriptor
from ..store import DocStore
from . import parser, extractor, validator


MODEL = "claude-haiku-4-5-20251001"

NORMALISE_SYSTEM = """\
You are a schema normaliser. Convert the user's field descriptions into a \
canonical JSON object where:
  - Keys are snake_case field names
  - Values are one of: string, number, boolean, date, list[string], list[object]
Return ONLY the JSON object. No prose, no markdown.\
"""


def elicit_schema(
    user_description: str,
    existing_schemas: dict[str, list[str]],
    client: anthropic.Anthropic | None = None,
) -> SchemaDescriptor:
    """
    Turn a natural language field description into a SchemaDescriptor.

    Presents existing schemas if any match, to encourage cache reuse.
    """
    if client is None:
        client = anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=NORMALISE_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": f"Extract these fields: {user_description}",
            }
        ],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    decoder = json.JSONDecoder()
    start = raw.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in schema response: {raw!r}")
    fields, _ = decoder.raw_decode(raw, start)

    # Infer a schema name from the field set
    name = _infer_schema_name(fields, client)

    return SchemaDescriptor(name=name, fields=fields)


def _infer_schema_name(fields: dict[str, str], client: anthropic.Anthropic) -> str:
    """Ask the model to infer a short schema name from field names."""
    keys = list(fields.keys())
    response = client.messages.create(
        model=MODEL,
        max_tokens=32,
        system="Return a short snake_case schema name (3 words max) based on these field names. Return ONLY the name.",
        messages=[{"role": "user", "content": str(keys)}],
    )
    raw = response.content[0].text.strip().lower()
    raw = re.sub(r"[^a-z0-9_]", "_", raw)
    return raw or "user_schema"


def run_pipeline(
    file_path: Path,
    descriptor: SchemaDescriptor,
    store: DocStore,
    client: anthropic.Anthropic | None = None,
    model: str = MODEL,
) -> ExtractionResult:
    """
    Run the full extraction pipeline for one file.

    Cache hit  → return stored result immediately, zero LLM calls.
    Cache miss → parse → extract → validate → store → return.
    """
    if client is None:
        client = anthropic.Anthropic()

    # Cache hit
    cached = store.get(file_path, descriptor)
    if cached is not None:
        raw_text = parser.parse(file_path)
        tokens_saved = parser.estimate_tokens(raw_text)
        return cached.model_copy(update={"tokens_saved": tokens_saved, "cache_hit": True})

    # Cache miss — run pipeline
    raw_text = parser.parse(file_path)
    estimated_raw_tokens = parser.estimate_tokens(raw_text)

    extracted, extract_tokens = extractor.extract(raw_text, descriptor, client, model)
    valid, issues, validate_tokens = validator.validate(
        extracted, descriptor, raw_text, client, model
    )

    fhash = store.file_hash(file_path)
    result = ExtractionResult(
        schema_name=descriptor.name,
        schema_version=descriptor.version,
        file_path=str(file_path),
        file_hash=fhash,
        data=extracted,
        valid=valid,
        validation_issues=issues,
        cache_hit=False,
        tokens_used=extract_tokens + validate_tokens,
        tokens_saved=0,
        model=model,
        extracted_at=datetime.now(timezone.utc).isoformat(),
    )

    store.set(result)
    return result


def run_directory(
    directory: Path,
    descriptor: SchemaDescriptor,
    store: DocStore,
    client: anthropic.Anthropic | None = None,
    model: str = MODEL,
    glob: str = "*",
    progress: bool = True,
) -> list[ExtractionResult]:
    """
    Run the pipeline over all supported files in a directory.

    progress: show a tqdm bar with running cache hit/miss counts. Pass False
    when embedding docstore in a non-interactive context.
    """
    supported = {".pdf", ".docx", ".txt", ".md", ".csv", ".html", ".json"}
    files = [
        f for f in sorted(directory.glob(glob))
        if f.is_file() and f.suffix.lower() in supported
    ]

    results = []
    hits = misses = 0
    bar = tqdm(files, desc=descriptor.name, unit="doc", disable=not progress)
    for f in bar:
        result = run_pipeline(f, descriptor, store, client, model)
        results.append(result)
        if result.cache_hit:
            hits += 1
        else:
            misses += 1
        bar.set_postfix(hit=hits, miss=misses)

    return results
