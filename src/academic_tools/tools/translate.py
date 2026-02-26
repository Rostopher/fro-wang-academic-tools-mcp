"""Translation tool: translate_paper.

Translates each body section from full_structure.json into Chinese in parallel,
skipping reference/appendix sections. Outputs <stem>_translated.md.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from ..models.paper import PaperWorkspace
from ..shared.llm_client import get_llm_client
from ..shared.prompt_utils import fill_prompt, load_prompt


def _should_translate(section: Dict[str, Any]) -> bool:
    """Skip reference and appendix sections."""
    return not (
        int(section.get("is_reference", 0) or 0) == 1
        or int(section.get("is_appendix", 0) or 0) == 1
    )


def _build_translate_prompt(template: str, text: str) -> str:
    return fill_prompt(template, document=text)


def _build_markdown(sections: List[Dict], translated_texts: List[Optional[str]]) -> str:
    parts = []
    for section, text in zip(sections, translated_texts):
        if text:
            parts.append(text.strip())
    return "\n\n".join(parts)


async def _run(paper_dir: str, concurrency: int = 4) -> str:
    """Module-level runner (also called by pipeline.py)."""
    if concurrency < 1:
        return json.dumps({"status": "error", "error": "concurrency must be >= 1"})

    ws = PaperWorkspace(paper_dir)
    try:
        structure_path = ws.require_structure()
    except FileNotFoundError as exc:
        return json.dumps({"status": "error", "error": str(exc)})

    sections: List[Dict] = json.loads(structure_path.read_text(encoding="utf-8"))
    prompt_template = load_prompt("translation.md")
    client = get_llm_client()
    semaphore = asyncio.Semaphore(concurrency)

    async def translate_one(section: Dict) -> Optional[str]:
        text = section.get("text_content", "").strip()
        if not text or not _should_translate(section):
            return text if text else None
        async with semaphore:
            prompt = _build_translate_prompt(prompt_template, text)
            try:
                return await client.translate(user=prompt, temperature=0.3)
            except Exception as exc:
                return f"[翻译失败: {exc}]\n\n{text}"

    translated_texts = await asyncio.gather(*[translate_one(s) for s in sections])

    output_md = _build_markdown(sections, list(translated_texts))
    out_path = ws.translated_path
    out_path.write_text(output_md, encoding="utf-8")

    translated_count = sum(
        1 for s, t in zip(sections, translated_texts)
        if _should_translate(s) and t
    )
    return json.dumps({
        "status": "success",
        "output": str(out_path),
        "sections_translated": translated_count,
        "sections_skipped": len(sections) - translated_count,
    })


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def translate_paper(
        paper_dir: str,
        concurrency: int = 4,
    ) -> str:
        """
        Translate the paper's sections into Chinese using parallel LLM calls.

        Reads <stem>_structure.json, translates each body section concurrently,
        and writes <stem>_translated.md.

        Skips reference and appendix sections (kept in English).

        Requires: extract_sections must have been run first.

        Args:
            paper_dir: **Absolute** path to the paper directory
                (e.g. ``C:/users/me/papers/2511.00517``).
                Relative paths are resolved against the MCP server's CWD,
                which is unpredictable — always pass an absolute path.
            concurrency: Number of concurrent LLM translation calls (default 4).

        Returns:
            JSON with status and output path.
        """
        return await _run(paper_dir, concurrency=concurrency)
