"""Summary report tool: generate_summary.

Reads full.md + metadata.json, calls LLM with the summary report prompt,
and writes summary_report.md.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..models.paper import PaperWorkspace
from ..shared.llm_client import get_llm_client
from ..shared.prompt_utils import fill_prompt, load_prompt


def _format_metadata_block(meta: dict) -> str:
    """Format metadata as a human-readable block for the prompt."""
    lines = []
    if t := meta.get("title"):
        lines.append(f"**Title:** {t}")
    authors = meta.get("authors") or []
    if authors:
        names = [a.get("name", "") if isinstance(a, dict) else str(a) for a in authors]
        lines.append(f"**Authors:** {'; '.join(n for n in names if n)}")
    if y := meta.get("publication_year"):
        lines.append(f"**Year:** {y}")
    if j := meta.get("journal"):
        lines.append(f"**Journal:** {j}")
    if d := meta.get("doi"):
        lines.append(f"**DOI:** {d}")
    if a := meta.get("citation_apa"):
        lines.append(f"**APA:** {a}")
    return "\n".join(lines)


async def _run(paper_dir: str) -> str:
    """Module-level runner (also called by pipeline.py)."""
    ws = PaperWorkspace(paper_dir)

    try:
        full_md = ws.require_ocr()
        meta = ws.require_metadata()
    except FileNotFoundError as exc:
        return json.dumps({"status": "error", "error": str(exc)})

    full_text = full_md.read_text(encoding="utf-8")
    meta_dict = meta.model_dump(exclude_none=True)
    metadata_block = _format_metadata_block(meta_dict)

    prompt_template = load_prompt("summary_report.md")
    prompt = fill_prompt(prompt_template, metadata=metadata_block, document=full_text)

    client = get_llm_client()
    try:
        report = await client.translate(user=prompt)
    except Exception as exc:
        return json.dumps({"status": "error", "error": f"LLM failed: {exc}"})

    out_path = ws.summary_path
    out_path.write_text(report, encoding="utf-8")

    return json.dumps({
        "status": "success",
        "output": str(out_path),
        "chars": len(report),
    })


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def generate_summary(paper_dir: str) -> str:
        """
        Generate a structured deep-reading summary report for a paper.

        Reads full.md (OCR text) and metadata.json, sends them to the LLM
        using the 6-section academic report prompt, and writes summary_report.md.

        Requires:
        - full.md (run ocr_paper first)
        - metadata.json (run extract_metadata first)

        Args:
            paper_dir: **Absolute** path to the paper directory
                (e.g. ``C:/users/me/papers/2511.00517``).
                Relative paths are resolved against the MCP server's CWD,
                which is unpredictable — always pass an absolute path.

        Returns:
            JSON with status and output path.
        """
        return await _run(paper_dir)
