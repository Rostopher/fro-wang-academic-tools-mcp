"""Academic Tools MCP Server.

Entry point: instantiates FastMCP and registers all tool modules.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .tools import arxiv
from .tools import ocr
from .tools import metadata
from .tools import structure
from .tools import translate
from .tools import summary
from .tools import rename
from .tools import pipeline
from .tools import zotero as zotero_tools

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

mcp = FastMCP("academic-tools")

# Register all tool modules
arxiv.register(mcp)
ocr.register(mcp)
metadata.register(mcp)
structure.register(mcp)
translate.register(mcp)
summary.register(mcp)
rename.register(mcp)
pipeline.register(mcp)
zotero_tools.register(mcp)
