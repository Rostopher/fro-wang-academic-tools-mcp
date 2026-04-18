"""arXiv tools: search_papers, download_paper.

Ported from arxiv-mcp-server with direct HTTP search (bypasses arxiv package URL
encoding issues for date range filters).
"""

from __future__ import annotations

import json
import logging
import asyncio
import time
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
_PDF_MIN_BYTES = 5
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


def _is_valid_pdf(path: Path) -> bool:
    """Return True when a downloaded file looks like a non-empty PDF."""
    if not path.exists() or not path.is_file():
        return False
    if path.stat().st_size < _PDF_MIN_BYTES:
        return False
    with path.open("rb") as fh:
        return fh.read(5) == b"%PDF-"


def _download_pdf_with_retries(
    pdf_url: str,
    pdf_path: Path,
    *,
    retries: int = 3,
    timeout: float = 60.0,
) -> None:
    """Download a PDF to a temporary .part file, then atomically replace final path."""
    part_path = pdf_path.with_name(f".{pdf_path.name}.part")
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        if part_path.exists():
            part_path.unlink()

        try:
            received = 0
            with httpx.stream(
                "GET",
                pdf_url,
                follow_redirects=True,
                timeout=timeout,
                headers={"User-Agent": "fro-wang-academic-tools-mcp/0.1"},
            ) as resp:
                resp.raise_for_status()
                expected_length = resp.headers.get("Content-Length")
                with part_path.open("wb") as fh:
                    for chunk in resp.iter_bytes():
                        if not chunk:
                            continue
                        received += len(chunk)
                        fh.write(chunk)

            if expected_length is not None and received != int(expected_length):
                raise RuntimeError(
                    f"Incomplete download: received {received} bytes, expected {expected_length}"
                )
            if not _is_valid_pdf(part_path):
                raise RuntimeError("Downloaded file is empty or not a valid PDF")

            part_path.replace(pdf_path)
            return
        except Exception as exc:
            last_error = exc
            if part_path.exists():
                part_path.unlink()
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 5))

    raise RuntimeError(f"Failed to download PDF after {retries} attempts: {last_error}")


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
            if _is_valid_pdf(pdf_path):
                return json.dumps({
                    "status": "already_exists",
                    "path": str(pdf_path),
                    "paper_id": paper_id,
                })
            pdf_path.unlink()

        try:
            search = arxiv.Search(id_list=[paper_id])
            paper = next(arxiv.Client().results(search))
            pdf_url = getattr(paper, "pdf_url", None) or f"https://arxiv.org/pdf/{paper_id}"
            await asyncio.to_thread(_download_pdf_with_retries, pdf_url, pdf_path)
            return json.dumps({
                "status": "success",
                "path": str(pdf_path),
                "title": paper.title,
                "paper_id": paper_id,
            })
        except Exception as exc:
            part_path = pdf_path.with_name(f".{pdf_path.name}.part")
            if part_path.exists():
                part_path.unlink()
            if pdf_path.exists():
                pdf_path.unlink()
            return json.dumps({"status": "error", "error": str(exc), "paper_id": paper_id})
