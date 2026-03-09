"""arXiv tools: search_papers, download_paper.

Ported from arxiv-mcp-server with direct HTTP search (bypasses arxiv package URL
encoding issues for date range filters).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import arxiv
import httpx
import xml.etree.ElementTree as ET
from dateutil import parser as dateutil_parser
from mcp.server.fastmcp import FastMCP

from ..config import settings

logger = logging.getLogger(__name__)

_ARXIV_API_URL = "https://export.arxiv.org/api/query"
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_arxiv_entry(entry: ET.Element) -> Dict[str, Any]:
    """Parse a single Atom <entry> element into a dict."""

    def text(tag: str) -> str:
        el = entry.find(tag, _NS)
        return (el.text or "").strip() if el is not None else ""

    paper_id = text("atom:id").split("/abs/")[-1].split("v")[0]
    categories = [c.get("term", "") for c in entry.findall("atom:category", _NS)]
    authors = [
        a.findtext("atom:name", "", _NS)
        for a in entry.findall("atom:author", _NS)
    ]
    published = text("atom:published")
    year = published[:4] if published else ""

    return {
        "id": paper_id,
        "title": text("atom:title").replace("\n", " "),
        "authors": authors,
        "abstract": text("atom:summary").replace("\n", " "),
        "published": published,
        "year": year,
        "categories": categories,
        "pdf_url": f"https://arxiv.org/pdf/{paper_id}",
        "abs_url": f"https://arxiv.org/abs/{paper_id}",
    }


async def _raw_search(
    query: str,
    max_results: int = 10,
    sort_by: str = "relevance",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    categories: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Search arXiv via raw HTTP to avoid URL-encoding issues with date filters."""
    query_parts = []
    if query.strip():
        query_parts.append(f"({query})")
    if categories:
        cat_filter = " OR ".join(f"cat:{c}" for c in categories)
        query_parts.append(f"({cat_filter})")
    if date_from or date_to:
        start = (
            dateutil_parser.parse(date_from).strftime("%Y%m%d0000")
            if date_from
            else "199107010000"
        )
        end = (
            dateutil_parser.parse(date_to).strftime("%Y%m%d2359")
            if date_to
            else datetime.now().strftime("%Y%m%d2359")
        )
        query_parts.append(f"submittedDate:[{start}+TO+{end}]")

    if not query_parts:
        raise ValueError("No search criteria provided")

    final_query = " AND ".join(query_parts)
    sort_map = {"relevance": "relevance", "date": "submittedDate"}
    encoded = quote(final_query, safe="+:[]")
    url = (
        f"{_ARXIV_API_URL}?search_query={encoded}"
        f"&max_results={max_results}"
        f"&sortBy={sort_map.get(sort_by, 'relevance')}"
        f"&sortOrder=descending"
    )

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=30)
        resp.raise_for_status()

    root = ET.fromstring(resp.text)
    return [_parse_arxiv_entry(e) for e in root.findall("atom:entry", _NS)]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def search_papers(
        query: str,
        max_results: int = 10,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        categories: Optional[List[str]] = None,
        sort_by: str = "relevance",
    ) -> str:
        """
        Search for papers on arXiv.

        Args:
            query: Search query (supports arXiv search syntax).
            max_results: Maximum number of results (1-50).
            date_from: Filter from date (YYYY-MM-DD).
            date_to: Filter to date (YYYY-MM-DD).
            categories: arXiv category filters, e.g. ["cs.AI", "cs.LG"].
            sort_by: 'relevance' or 'date'.

        Returns:
            JSON string containing list of matching papers.
        """
        max_results = max(1, min(50, max_results))
        try:
            results = await _raw_search(
                query=query,
                max_results=max_results,
                sort_by=sort_by,
                date_from=date_from,
                date_to=date_to,
                categories=categories,
            )
            return json.dumps(results, ensure_ascii=False, indent=2)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    @mcp.tool()
    async def download_paper(
        paper_id: str,
        download_dir: Optional[str] = None,
    ) -> str:
        """
        Download a paper PDF from arXiv.

        Args:
            paper_id: arXiv paper ID (e.g. '2310.12345' or '2310.12345v2').
            download_dir: Directory to save the PDF. Prefer an absolute path to avoid
                ambiguity across MCP clients. If "cwd"/"auto", uses <cwd>/papers.
                If omitted, uses ARXIV_STORAGE_PATH (relative paths are resolved under cwd).

        Returns:
            JSON string with status and the absolute path to the downloaded PDF.
        """
        if download_dir and download_dir.strip().lower() in {"cwd", "auto"}:
            storage = Path.cwd() / "papers"
        else:
            raw = Path((download_dir or settings.ARXIV_STORAGE_PATH).strip()).expanduser()
            storage = raw if raw.is_absolute() else (Path.cwd() / raw)
        storage = storage.resolve()
        storage.mkdir(parents=True, exist_ok=True)
        pdf_path = storage / f"{paper_id}.pdf"

        if pdf_path.exists():
            return json.dumps({
                "status": "already_exists",
                "path": str(pdf_path),
                "paper_id": paper_id,
            })

        try:
            search = arxiv.Search(id_list=[paper_id])
            paper = next(arxiv.Client().results(search))
            paper.download_pdf(dirpath=str(storage), filename=f"{paper_id}.pdf")
            return json.dumps({
                "status": "success",
                "path": str(pdf_path),
                "title": paper.title,
                "paper_id": paper_id,
            })
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc), "paper_id": paper_id})
