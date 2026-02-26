"""Structure extraction tool: extract_sections.

Ports the logic from section_data_extractor_skill:
  1. Read full.md
  2. Call LLM with section extraction prompt → JSON structure
  3. Match headings to line numbers (fuzzy matching via difflib)
  4. Inject text_content per section
  5. Write <stem>_structure.json and return summary
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from ..models.paper import PaperWorkspace
from ..models.structure import SectionList
from ..shared.llm_client import get_llm_client
from ..shared.prompt_utils import fill_prompt, load_prompt


# ---------------------------------------------------------------------------
# Structure utilities (ported from structure_utils.py)
# ---------------------------------------------------------------------------

_MD_TITLE_THRESHOLD = 0.8
_SENTENCE_THRESHOLD = 0.7


def _find_title_line(title: str, md_lines: List[str], start: int, end: int) -> Optional[int]:
    """Fuzzy-match a heading title to a line number range."""
    title_clean = title.strip().lower()

    # 1. Try markdown heading match
    for i in range(start, min(end, len(md_lines))):
        line = md_lines[i].strip()
        if re.match(r"^#+\s+", line):
            heading_text = re.sub(r"^#+\s+", "", line).strip().lower()
            ratio = difflib.SequenceMatcher(None, title_clean, heading_text).ratio()
            if ratio > _MD_TITLE_THRESHOLD:
                return i
            if title_clean in {"abstract", "introduction", "conclusion", "references"}:
                if title_clean in heading_text:
                    return i

    # 2. Try sentence-level match
    best_ratio, best_i = 0.0, None
    for i in range(start, min(end, len(md_lines))):
        line = md_lines[i].strip()
        if not line:
            continue
        ratio = difflib.SequenceMatcher(None, title_clean, line.lower()).ratio()
        if ratio > best_ratio:
            best_ratio, best_i = ratio, i

    return best_i if best_ratio >= _SENTENCE_THRESHOLD else None


def _attach_line_numbers(structure: List[Dict], md_lines: List[str]) -> List[Dict]:
    """For each section in the structure, find its start line number."""
    result = []
    file_end = len(md_lines)
    quarter_end = max(int(file_end * 0.25), 1)
    last_global = -1

    for item in structure:
        level = int(item.get("level", 0))
        title = item.get("title", "")

        if level == 0:
            search_start, search_end = 0, quarter_end
        else:
            search_start = max(last_global + 1, 0)
            search_end = file_end

        line_no = _find_title_line(title, md_lines, search_start, search_end)
        if line_no is not None:
            last_global = line_no

        sub_title_list = []
        last_sub = line_no
        for sub in item.get("sub_title_list", []):
            sub_text = sub.get("title", "") if isinstance(sub, dict) else str(sub)
            sub_start = (last_sub + 1) if last_sub is not None else search_start
            sub_line = _find_title_line(sub_text, md_lines, sub_start, file_end)
            if sub_line is not None:
                last_sub = sub_line
                last_global = max(last_global, sub_line)
            entry = dict(sub) if isinstance(sub, dict) else {"title": sub_text}
            entry["line_number"] = sub_line
            sub_title_list.append(entry)

        result.append({
            **item,
            "line_number": line_no,
            "sub_title_list": sub_title_list,
        })

    return result


def _add_text_content(sections: List[Dict], md_lines: List[str]) -> List[Dict]:
    """Slice full.md based on line numbers and inject text_content."""
    file_end = len(md_lines)

    enriched = []
    for idx, section in enumerate(sections):
        start_line = section.get("line_number")
        if start_line is None:
            enriched.append({**section, "text_content": ""})
            continue

        # Next section's start line = end of current section
        end_line = file_end
        for j in range(idx + 1, len(sections)):
            next_start = sections[j].get("line_number")
            if next_start is not None:
                end_line = next_start
                break

        text = "".join(md_lines[start_line:end_line]).strip()
        enriched.append({**section, "text_content": text})

    return enriched


def _validate_structure_items(raw: Any) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    Runtime guard for section list shape.

    This protects internal processing even if future code paths bypass
    Pydantic model validation.
    """
    if not isinstance(raw, list):
        return None, "LLM returned unexpected format (expected list)"

    normalized: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            typename = type(item).__name__
            return None, f"LLM returned invalid section at index {idx}: expected object, got {typename}"

        sub_titles = item.get("sub_title_list", [])
        if sub_titles is None:
            sub_titles = []
        elif not isinstance(sub_titles, list):
            typename = type(sub_titles).__name__
            return None, (
                f"LLM returned invalid sub_title_list at index {idx}: "
                f"expected list, got {typename}"
            )

        normalized.append({
            **item,
            "sub_title_list": sub_titles,
        })

    return normalized, None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

async def _run(paper_dir: str) -> str:
    """Module-level runner (also called by pipeline.py)."""
    ws = PaperWorkspace(paper_dir)
    try:
        full_md = ws.require_ocr()
    except FileNotFoundError as exc:
        return json.dumps({"status": "error", "error": str(exc)})

    markdown_content = full_md.read_text(encoding="utf-8")
    md_lines = markdown_content.splitlines(keepends=True)

    prompt_template = load_prompt("section_extraction.md")
    prompt = fill_prompt(prompt_template, document=markdown_content)

    client = get_llm_client()
    try:
        structure_model = await client.get_model(
            user=prompt,
            response_model=SectionList,
            temperature=0.0,
        )
    except Exception as exc:
        return json.dumps({"status": "error", "error": f"LLM failed or returned invalid JSON/schema: {exc}"})

    raw_structure = structure_model.model_dump(mode="python")
    structure, validation_error = _validate_structure_items(raw_structure)
    if validation_error:
        return json.dumps({"status": "error", "error": validation_error})
    assert structure is not None

    structure_with_lines = _attach_line_numbers(structure, md_lines)
    structure_with_text = _add_text_content(structure_with_lines, md_lines)

    out_path = ws.structure_path
    out_path.write_text(
        json.dumps(structure_with_text, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    body_sections = [s for s in structure_with_text if s.get("is_body") == 1]
    return json.dumps({
        "status": "success",
        "output": str(out_path),
        "total_sections": len(structure_with_text),
        "body_sections": len(body_sections),
    })


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def extract_sections(paper_dir: str) -> str:
        """
        Extract the hierarchical section structure from full.md using LLM.

        Output: <paper_dir>/<stem>_structure.json — a flat list of sections,
        each with: title, level, is_reference, is_appendix, is_body,
        figures, tables, line_number, text_content.

        Requires: full.md must exist (run ocr_paper first).

        Args:
            paper_dir: **Absolute** path to the paper directory
                (e.g. ``C:/users/me/papers/2511.00517``).
                Relative paths are resolved against the MCP server's CWD,
                which is unpredictable — always pass an absolute path.

        Returns:
            JSON summary with section count and output path.
        """
        return await _run(paper_dir)
