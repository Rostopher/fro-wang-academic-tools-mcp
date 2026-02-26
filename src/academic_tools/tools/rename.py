"""Rename tool: rename_paper_folder.

Renames a paper_dir to the standard format:
  Authors-VenueAbbr-Year-TitleWords
using data from metadata.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..models.paper import PaperWorkspace
from ..shared.utils import (
    abbreviate_venue,
    format_authors,
    sanitize_for_filename,
    title_first_words,
)


def _resolve_collision(dest: Path) -> Path:
    """If dest already exists, append -v2, -v3, … until a free name is found."""
    if not dest.exists():
        return dest
    base = dest.name
    parent = dest.parent
    for i in range(2, 100):
        candidate = parent / f"{base}-v{i}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Too many name collisions (100+). Please clean up manually.")


def _build_folder_name(meta_dict: dict) -> str:
    authors = format_authors(meta_dict.get("authors") or [])
    year = (
        meta_dict.get("publication_year")
        or meta_dict.get("year")
        or "UNKNOWN"
    )
    venue = (
        meta_dict.get("venue_abbr")
        or abbreviate_venue(meta_dict.get("journal") or meta_dict.get("venue") or "")
    )
    title = title_first_words(meta_dict.get("title") or "")

    parts = [
        sanitize_for_filename(str(authors)),
        sanitize_for_filename(str(venue)),
        sanitize_for_filename(str(year)),
        sanitize_for_filename(title),
    ]
    return "-".join(parts)


async def _run(paper_dir: str, dry_run: bool = False) -> str:
    """Module-level runner (also called by pipeline.py)."""
    ws = PaperWorkspace(paper_dir)

    # Safety guard: refuse to rename directories not created by this toolset.
    try:
        ws.require_workspace()
    except PermissionError as exc:
        return json.dumps({"status": "error", "error": str(exc)})

    try:
        meta = ws.require_metadata()
    except FileNotFoundError as exc:
        return json.dumps({"status": "error", "error": str(exc)})

    meta_dict = meta.model_dump(exclude_none=True)
    target_name = _build_folder_name(meta_dict)
    target_dir = _resolve_collision(ws.dir.parent / target_name)

    result = {
        "old_path": str(ws.dir),
        "new_path": str(target_dir),
        "new_name": target_dir.name,
    }

    if dry_run:
        return json.dumps({"status": "dry_run", **result})

    if target_dir == ws.dir:
        return json.dumps({"status": "unchanged", **result})

    ws.dir.rename(target_dir)
    return json.dumps({"status": "success", **result})


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def rename_paper_folder(
        paper_dir: str,
        dry_run: bool = False,
    ) -> str:
        """
        Rename a paper directory to the standard format:
        "Authors-Venue-Year-TitleWords"

        Uses metadata.json for author, year, journal, and title information.

        The naming rules:
        - 1 author  → Surname
        - 2 authors → Surname1 and Surname2
        - 3+        → Surname1 et al
        - Venue     → abbreviation of journal/conference name
        - Title     → first 5 meaningful words

        Requires: metadata.json (run extract_metadata first).

        Args:
            paper_dir: **Absolute** path to the paper directory to rename
                (e.g. ``C:/users/me/papers/2511.00517``).
                Relative paths are resolved against the MCP server's CWD,
                which is unpredictable — always pass an absolute path.
            dry_run: If True, return the new name without actually renaming.

        Returns:
            JSON with old_path, new_path, and status.
        """
        return await _run(paper_dir, dry_run=dry_run)
