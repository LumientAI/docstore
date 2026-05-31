"""Environment-derived defaults shared between the CLI and the MCP server.

API keys (ANTHROPIC_API_KEY, OPENAI_API_KEY, GROQ_API_KEY, GEMINI_API_KEY) are
read where they're used, directly by the SDK clients in `docstore.llm`. Only
docstore's own DOCSTORE_*-prefixed knobs live here, where the CLI and the MCP
server would otherwise duplicate the lookup.
"""

from __future__ import annotations

import os
from typing import cast

from docstore.llm import DEFAULT_PROVIDER, ProviderName


DOCSTORE_DIR: str = os.environ.get("DOCSTORE_DIR", ".docstore")
DOCSTORE_PROVIDER: ProviderName = cast(
    ProviderName,
    os.environ.get("DOCSTORE_PROVIDER", DEFAULT_PROVIDER),
)
DOCSTORE_MODEL: str | None = os.environ.get("DOCSTORE_MODEL")
