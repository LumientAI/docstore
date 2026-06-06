# Agent Integrations

docstore works best as an MCP server plus a small agent instruction: query the
cache before rereading raw documents.

## Claude Desktop

Add docstore to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "docstore": {
      "command": "docstore-server",
      "env": {
        "DOCSTORE_DIR": "/path/to/your/.docstore",
        "DOCSTORE_PROVIDER": "anthropic",
        "ANTHROPIC_API_KEY": "your-key"
      }
    }
  }
}
```

## OpenClaw

Register docstore as a local stdio MCP server:

```bash
openclaw mcp add docstore \
  --command docstore-server \
  --env DOCSTORE_DIR=/path/to/your/.docstore \
  --env DOCSTORE_PROVIDER=anthropic \
  --env ANTHROPIC_API_KEY=your-key

openclaw mcp doctor docstore --probe
```

OpenClaw's MCP registry persists third-party servers for OpenClaw-managed agent
runs. Its stdio definitions use a command plus optional args, env, and cwd.

## Codex

Codex can use docstore in two complementary ways:

- The repo skill at `.agents/skills/docstore/SKILL.md` teaches Codex the cache-aware workflow.
- An MCP server gives Codex live access to `extract`, `query`, `diff`, and `stats`.

For a local install:

```bash
codex mcp add docstore \
  --env DOCSTORE_DIR=/path/to/your/.docstore \
  --env DOCSTORE_PROVIDER=anthropic \
  --env ANTHROPIC_API_KEY=your-key \
  -- docstore-server
```

For a source checkout, pass a command that resolves inside the repo environment:

```bash
codex mcp add docstore \
  --env DOCSTORE_DIR=/path/to/your/.docstore \
  --env DOCSTORE_PROVIDER=anthropic \
  --env ANTHROPIC_API_KEY=your-key \
  -- uv run docstore-server
```

You can also configure a trusted project with `.codex/config.toml`:

```toml
[mcp_servers.docstore]
command = "uv"
args = ["run", "docstore-server"]
cwd = "/path/to/docstore"
env_vars = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY"]

[mcp_servers.docstore.env]
DOCSTORE_DIR = "/path/to/your/.docstore"
DOCSTORE_PROVIDER = "anthropic"
```

## Agent Prompt

```text
Use docstore. Check stats first. If the needed schema exists, query it instead
of rereading raw documents. Extract only missing files or schemas. For invoices,
use fields invoice_no, vendor, amount, currency, due_date, paid.
```

## No-Cost Local Check

Without API credentials, users can still verify the repo and free fake-LLM
benchmark tests:

```bash
uv run pytest tests/test_benchmark.py
uv run ruff check .
```
