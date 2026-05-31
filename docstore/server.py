"""
docstore MCP server

Exposes four tools to any MCP-compatible client (Claude Desktop, etc.):
  - extract   Run extraction on a file, return structured result
  - query     Query stored results by schema name and optional filter
  - diff      Compare current file against stored version
  - stats     Return cache statistics
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

load_dotenv()

from .agents import orchestrator, differ as differ_agent, parser as parser_agent
from .agents import extractor as extractor_agent
from .schema import SchemaDescriptor
from .store import DocStore


STORE_DIR = os.environ.get("DOCSTORE_DIR", ".docstore")
MODEL = os.environ.get("DOCSTORE_MODEL", "claude-haiku-4-5-20251001")

server = Server("docstore")
store = DocStore(root=Path(STORE_DIR))

# Lazy-init the Anthropic client so importing this module doesn't require an
# API key — only the tool handlers that actually make LLM calls do.
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="extract",
            description=(
                "Extract structured fields from a document file. "
                "Returns cached result if the file has not changed. "
                "If no schema is specified, asks the user to describe the fields."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the file"},
                    "fields": {
                        "type": "object",
                        "description": "Schema fields as {field_name: type}. "
                                       "If omitted, will attempt to reuse an existing schema.",
                        "additionalProperties": {"type": "string"},
                    },
                    "schema_name": {
                        "type": "string",
                        "description": "Name of an existing schema in the store",
                    },
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="query",
            description=(
                "Query all stored extraction results for a given schema. "
                "No LLM calls — returns immediately from cache."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "schema_name": {"type": "string"},
                    "filter": {
                        "type": "string",
                        "description": "Simple filter expression e.g. 'paid=false'",
                    },
                },
                "required": ["schema_name"],
            },
        ),
        Tool(
            name="diff",
            description=(
                "Compare the current version of a file against its stored extraction. "
                "Returns changed fields and a plain-language summary."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "schema_name": {"type": "string"},
                },
                "required": ["file_path", "schema_name"],
            },
        ),
        Tool(
            name="stats",
            description="Return cache hit statistics and token savings for the store.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "extract":
        return await _handle_extract(arguments)
    elif name == "query":
        return await _handle_query(arguments)
    elif name == "diff":
        return await _handle_diff(arguments)
    elif name == "stats":
        return await _handle_stats()
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def _handle_extract(args: dict) -> list[TextContent]:
    file_path = Path(args["file_path"])
    if not file_path.exists():
        return [TextContent(type="text", text=f"File not found: {file_path}")]

    fields = args.get("fields")
    schema_name = args.get("schema_name")

    if fields:
        descriptor = SchemaDescriptor(
            name=schema_name or "mcp_schema",
            fields=fields,
        )
    elif schema_name:
        existing = store.list_schemas()
        if schema_name in existing:
            versions = existing[schema_name]
            descriptor = SchemaDescriptor(
                name=schema_name, fields={}, version=versions[-1]
            )
        else:
            return [TextContent(
                type="text",
                text=f"Schema '{schema_name}' not found. Available: {list(existing.keys())}"
            )]
    else:
        # Try to find any existing schema for this file
        entries = store.list_entries_for_file(file_path)
        if entries:
            schema_name, version = entries[0]
            descriptor = SchemaDescriptor(name=schema_name, fields={}, version=version)
        else:
            return [TextContent(
                type="text",
                text="No schema provided and no existing schema found for this file. "
                     "Please provide 'fields' or 'schema_name'."
            )]

    result = orchestrator.run_pipeline(file_path, descriptor, store, _get_client(), MODEL)
    return [TextContent(type="text", text=json.dumps({
        "data": result.data,
        "valid": result.valid,
        "cache_hit": result.cache_hit,
        "tokens_used": result.tokens_used,
        "tokens_saved": result.tokens_saved,
        "validation_issues": result.validation_issues,
    }, indent=2))]


async def _handle_query(args: dict) -> list[TextContent]:
    schema_name = args["schema_name"]
    filter_expr = args.get("filter")

    def filter_fn(result):
        if not filter_expr:
            return True
        try:
            if "!=" in filter_expr:
                field, value = filter_expr.split("!=", 1)
                return str(result.data.get(field.strip(), "")) != value.strip()
            elif "=" in filter_expr:
                field, value = filter_expr.split("=", 1)
                actual = str(result.data.get(field.strip(), "")).lower()
                return actual == value.strip().lower()
        except Exception:
            return True
        return True

    results = store.query(schema_name, filter_fn)
    if not results:
        return [TextContent(type="text", text=f"No results found for schema '{schema_name}'.")]

    output = [
        {"file": r.file_path, **r.data}
        for r in results
    ]
    return [TextContent(type="text", text=json.dumps(output, indent=2))]


async def _handle_diff(args: dict) -> list[TextContent]:
    file_path = Path(args["file_path"])
    schema_name = args["schema_name"]

    entries = store.list_entries_for_file(file_path)
    matching = [e for e in entries if e[0] == schema_name]
    if not matching:
        return [TextContent(
            type="text",
            text=f"No stored result for schema '{schema_name}' on {file_path.name}"
        )]

    sname, version = matching[0]
    descriptor = SchemaDescriptor(name=sname, fields={}, version=version)
    stored = store.get(file_path, descriptor)
    if not stored:
        return [TextContent(type="text", text="Could not retrieve stored result.")]

    raw_text = parser_agent.parse(file_path)
    current_data, _ = extractor_agent.extract(raw_text, descriptor, _get_client(), MODEL)
    current_hash = store.file_hash(file_path)

    result = differ_agent.diff(
        previous=stored.data,
        current=current_data,
        descriptor=descriptor,
        file_path=str(file_path),
        previous_hash=stored.file_hash,
        current_hash=current_hash,
        client=_get_client(),
        model=MODEL,
    )

    return [TextContent(type="text", text=json.dumps({
        "changed_fields": result.changed_fields,
        "summary": result.summary,
        "previous": result.previous,
        "current": result.current,
    }, indent=2))]


async def _handle_stats() -> list[TextContent]:
    s = store.stats()
    return [TextContent(type="text", text=json.dumps(dict(s), indent=2))]


def main():
    import asyncio
    asyncio.run(stdio_server(server))


if __name__ == "__main__":
    main()
