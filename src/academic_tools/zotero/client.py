"""Zotero client wrapper — ported from zotero-mcp, stripped of semantic search."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union
from urllib.parse import unquote, urlparse

from pyzotero import zotero

from ..config import settings
from .utils import format_creators


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AttachmentDetails:
    """Details about a Zotero attachment."""
    key: str
    title: str
    filename: str
    content_type: str
    href: Optional[str] = None


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def get_zotero_client() -> zotero.Zotero:
    """
    Return an authenticated Zotero client using values from settings / env.

    Raises:
        ValueError: If required env vars are missing for remote mode.
    """
    local = settings.ZOTERO_LOCAL

    if not local:
        raise ValueError(
            "Zotero integration is local read-only. Set ZOTERO_LOCAL=true, open "
            "Zotero Desktop, and enable the local HTTP/API server. Remote Zotero "
            "API access and write operations are not supported by this MCP."
        )

    return zotero.Zotero(
        library_id="0",
        library_type="user",
        api_key=None,
        local=True,
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_item_metadata(item: Dict[str, Any], include_abstract: bool = True) -> str:
    """Format a Zotero item dict as readable Markdown."""
    data = item.get("data", {})
    item_type = data.get("itemType", "unknown")

    lines = [
        f"# {data.get('title', 'Untitled')}",
        f"**Type:** {item_type}",
        f"**Item Key:** {data.get('key')}",
    ]

    if date := data.get("date"):
        lines.append(f"**Date:** {date}")

    if creators := data.get("creators", []):
        lines.append(f"**Authors:** {format_creators(creators)}")

    if item_type == "journalArticle":
        if journal := data.get("publicationTitle"):
            info = f"**Journal:** {journal}"
            if v := data.get("volume"):
                info += f", Vol. {v}"
            if i := data.get("issue"):
                info += f", Issue {i}"
            if p := data.get("pages"):
                info += f", pp. {p}"
            lines.append(info)
    elif item_type == "book":
        if publisher := data.get("publisher"):
            lines.append(f"**Publisher:** {publisher}")
    elif item_type == "conferencePaper":
        if conf := data.get("conferenceName") or data.get("proceedingsTitle"):
            lines.append(f"**Conference:** {conf}")

    if doi := data.get("DOI"):
        lines.append(f"**DOI:** {doi}")
    if url := data.get("url"):
        lines.append(f"**URL:** {url}")

    if tags := data.get("tags"):
        tag_list = [f"`{t['tag']}`" for t in tags]
        if tag_list:
            lines.append(f"**Tags:** {' '.join(tag_list)}")

    if include_abstract and (abstract := data.get("abstractNote")):
        lines.extend(["", "## Abstract", abstract])

    if "meta" in item and item["meta"].get("numChildren", 0) > 0:
        lines.append(f"**Attachments/Notes:** {item['meta']['numChildren']}")

    return "\n\n".join(lines)


def generate_bibtex(item: Dict[str, Any]) -> str:
    """
    Generate BibTeX for a Zotero item.
    Tries Better BibTeX first (if Zotero is running locally), then falls back
    to basic field mapping.
    """
    data = item.get("data", {})
    item_key = data.get("key", "")
    item_type = data.get("itemType", "misc")

    if item_type in ("attachment", "note"):
        raise ValueError(f"Cannot export BibTeX for item type '{item_type}'")

    # Try Better BibTeX local JSON-RPC
    try:
        from .bibtex_client import ZoteroBetterBibTexAPI
        bbt = ZoteroBetterBibTexAPI()
        if bbt.is_zotero_running():
            return bbt.export_bibtex(item_key)
    except Exception:
        pass  # fall through to manual generation

    # Manual BibTeX fallback
    type_map = {
        "journalArticle": "article",
        "book": "book",
        "bookSection": "incollection",
        "conferencePaper": "inproceedings",
        "thesis": "phdthesis",
        "report": "techreport",
        "webpage": "misc",
        "manuscript": "unpublished",
    }

    creators = data.get("creators", [])
    first_surname = ""
    if creators:
        first = creators[0]
        first_surname = (
            first.get("lastName")
            or (first.get("name", "").split()[-1] if first.get("name") else "")
        ).replace(" ", "")

    year = data.get("date", "")[:4] if data.get("date") else "nodate"
    cite_key = f"{first_surname}{year}_{item_key}"
    bib_type = type_map.get(item_type, "misc")

    lines = [f"@{bib_type}{{{cite_key},"]

    field_map = [
        ("title", "title"),
        ("publicationTitle", "journal"),
        ("volume", "volume"),
        ("issue", "number"),
        ("pages", "pages"),
        ("publisher", "publisher"),
        ("DOI", "doi"),
        ("url", "url"),
    ]
    for zf, bf in field_map:
        if value := data.get(zf):
            value = value.replace("{", "\\{").replace("}", "\\}")
            lines.append(f"  {bf} = {{{value}}},")

    authors = []
    for c in creators:
        if c.get("creatorType") == "author":
            if "lastName" in c and "firstName" in c:
                authors.append(f"{c['lastName']}, {c['firstName']}")
            elif "name" in c:
                authors.append(c["name"])
    if authors:
        lines.append(f"  author = {{{' and '.join(authors)}}},")

    if year != "nodate":
        lines.append(f"  year = {{{year}}},")

    # Trim trailing comma from last field
    if lines[-1].endswith(","):
        lines[-1] = lines[-1][:-1]
    lines.append("}")

    return "\n".join(lines)


def get_attachment_details(
    zot: zotero.Zotero, item: Dict[str, Any]
) -> Optional[AttachmentDetails]:
    """Find the best attachment (PDF > HTML > other) for a Zotero item."""
    data = item.get("data", {})
    item_type = data.get("itemType")
    item_key = data.get("key")

    if item_type == "attachment":
        enclosure = item.get("links", {}).get("enclosure", {})
        return AttachmentDetails(
            key=item_key,
            title=data.get("title", "Untitled"),
            filename=data.get("filename", ""),
            content_type=data.get("contentType", ""),
            href=enclosure.get("href"),
        )

    try:
        children = zot.children(item_key)
        pdfs, htmls, others = [], [], []
        for child in children:
            cd = child.get("data", {})
            if cd.get("itemType") != "attachment":
                continue
            ct = cd.get("contentType", "")
            enclosure = child.get("links", {}).get("enclosure", {})
            entry = (
                child.get("key", ""),
                cd.get("title", "Untitled"),
                cd.get("filename", ""),
                ct,
                enclosure.get("href"),
            )
            if ct == "application/pdf":
                pdfs.append(entry)
            elif ct.startswith("text/html"):
                htmls.append(entry)
            else:
                others.append(entry)

        for category in (pdfs, htmls, others):
            if category:
                key, title, filename, content_type, href = category[0]
                return AttachmentDetails(
                    key=key,
                    title=title,
                    filename=filename,
                    content_type=content_type,
                    href=href,
                )
    except Exception:
        pass

    return None


def convert_to_markdown(file_path: Union[str, Path]) -> str:
    """Convert a local file (PDF, HTML, …) to Markdown via markitdown."""
    try:
        from markitdown import MarkItDown
        value = str(file_path)
        parsed = urlparse(value)
        if parsed.scheme == "file":
            value = unquote(parsed.path)
        result = MarkItDown().convert(value)
        return result.text_content
    except Exception as exc:
        return f"Error converting file to Markdown: {exc}"
