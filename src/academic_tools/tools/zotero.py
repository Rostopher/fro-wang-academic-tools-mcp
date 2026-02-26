"""Zotero tools (~10 essential ones, no semantic search).

Each tool wraps the low-level zotero/ connection layer.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from ..zotero.client import (
    convert_to_markdown,
    format_item_metadata,
    generate_bibtex,
    get_attachment_details,
    get_zotero_client,
)
from ..zotero.bibtex_client import ZoteroBetterBibTexAPI
from ..zotero.utils import format_creators


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def zotero_search_items(
        query: str,
        limit: int = 10,
        include_abstract: bool = False,
    ) -> str:
        """
        Search Zotero library by keyword.

        Args:
            query: Search term.
            limit: Max number of results (1-100).
            include_abstract: Include abstract in results.

        Returns:
            Markdown-formatted list of matching items.
        """
        zot = get_zotero_client()
        limit = max(1, min(100, limit))
        items = zot.items(q=query, limit=limit)
        if not items:
            return "No items found."
        parts = [format_item_metadata(item, include_abstract=include_abstract) for item in items]
        return "\n\n---\n\n".join(parts)

    @mcp.tool()
    async def zotero_get_item_metadata(
        item_key: str,
        format: str = "markdown",
    ) -> str:
        """
        Get detailed metadata for a Zotero item by its key.

        Args:
            item_key: Zotero item key (e.g. 'ABC123DE').
            format: 'markdown' or 'bibtex'.

        Returns:
            Formatted metadata string.
        """
        zot = get_zotero_client()
        item = zot.item(item_key)
        if format == "bibtex":
            return generate_bibtex(item)
        return format_item_metadata(item, include_abstract=True)

    @mcp.tool()
    async def zotero_get_item_fulltext(item_key: str) -> str:
        """
        Get the full text of a Zotero item's best attachment (PDF/HTML).

        Attempts to retrieve via Zotero's full-text index first, then falls
        back to downloading and converting the attachment.

        Args:
            item_key: Zotero item key.

        Returns:
            Markdown text of the attachment content.
        """
        zot = get_zotero_client()

        # Try full-text index first (fast, no download required)
        try:
            fulltext = zot.fulltext_item(item_key)
            if fulltext and fulltext.get("content"):
                return fulltext["content"]
        except Exception:
            pass

        # Fallback: find attachment and convert
        item = zot.item(item_key)
        attachment = get_attachment_details(zot, item)
        if attachment is None:
            return "No attachment found for this item."

        try:
            attachment_file = zot.dump(attachment.key, attachment.filename)
            return convert_to_markdown(attachment_file)
        except Exception as exc:
            return f"Could not retrieve full text: {exc}"

    @mcp.tool()
    async def zotero_get_collections(include_items_count: bool = False) -> str:
        """
        List all collections in the Zotero library with their hierarchy.

        Args:
            include_items_count: Also show number of items per collection.

        Returns:
            Formatted collection tree.
        """
        zot = get_zotero_client()
        collections = zot.collections()
        if not collections:
            return "No collections found."

        # Build hierarchy
        by_key: Dict[str, Any] = {c["key"]: c for c in collections}
        lines = []
        for col in sorted(collections, key=lambda c: c["data"].get("name", "")):
            data = col["data"]
            parent = data.get("parentCollection", "")
            indent = "  " if parent else ""
            name = data.get("name", "(unnamed)")
            key = col["key"]
            line = f"{indent}- **{name}** (`{key}`)"
            if include_items_count:
                line += f"  [{data.get('numItems', '?')} items]"
            lines.append(line)

        return "\n".join(lines)

    @mcp.tool()
    async def zotero_get_collection_items(
        collection_key: str,
        limit: int = 25,
        include_abstract: bool = False,
    ) -> str:
        """
        Get items in a specific Zotero collection.

        Args:
            collection_key: Zotero collection key.
            limit: Max items to return.
            include_abstract: Include abstract in results.

        Returns:
            Formatted list of items.
        """
        zot = get_zotero_client()
        items = zot.collection_items(collection_key, limit=limit)
        if not items:
            return "Collection is empty or not found."
        parts = [format_item_metadata(item, include_abstract=include_abstract) for item in items]
        return "\n\n---\n\n".join(parts)

    @mcp.tool()
    async def zotero_get_tags(query: Optional[str] = None) -> str:
        """
        List all tags in the Zotero library.

        Args:
            query: Optional filter string to narrow results.

        Returns:
            List of tag names and counts.
        """
        zot = get_zotero_client()
        tags = zot.tags()
        if query:
            tags = [t for t in tags if query.lower() in t["tag"].lower()]
        if not tags:
            return "No tags found."
        lines = [f"- {t['tag']}" for t in sorted(tags, key=lambda t: t["tag"])]
        return "\n".join(lines)

    @mcp.tool()
    async def zotero_get_recent(limit: int = 10, include_abstract: bool = False) -> str:
        """
        Get recently added/modified items in Zotero.

        Args:
            limit: Number of recent items to return.
            include_abstract: Include abstract.

        Returns:
            Formatted list of recent items.
        """
        zot = get_zotero_client()
        items = zot.items(sort="dateModified", direction="desc", limit=limit)
        if not items:
            return "No items found."
        parts = [format_item_metadata(item, include_abstract=include_abstract) for item in items]
        return "\n\n---\n\n".join(parts)

    @mcp.tool()
    async def zotero_get_annotations(item_key: str) -> str:
        """
        Get PDF annotations for a Zotero item.

        Tries Better BibTeX (if running), then Zotero API children.

        Args:
            item_key: Zotero item key.

        Returns:
            Formatted annotations as Markdown.
        """
        # Try BBT first
        try:
            bbt = ZoteroBetterBibTexAPI()
            if bbt.is_zotero_running():
                zot = get_zotero_client()
                item = zot.item(item_key)
                bibtex_key = item.get("data", {}).get("key", item_key)
                annotations = bbt.get_annotations(bibtex_key)
                if annotations:
                    return _format_annotations_md(annotations)
        except Exception:
            pass

        # Fallback: Zotero API children
        try:
            zot = get_zotero_client()
            children = zot.children(item_key)
            annotations = []
            for child in children:
                cd = child.get("data", {})
                if cd.get("itemType") == "annotation":
                    annotations.append({
                        "type": cd.get("annotationType", ""),
                        "text": cd.get("annotationText", ""),
                        "comment": cd.get("annotationComment", ""),
                        "page": cd.get("annotationPageLabel", ""),
                        "color": cd.get("annotationColor", ""),
                    })
            if annotations:
                return _format_annotations_md(annotations)
        except Exception:
            pass

        return "No annotations found."

    @mcp.tool()
    async def zotero_get_notes(item_key: str) -> str:
        """
        Get notes attached to a Zotero item.

        Args:
            item_key: Zotero item key.

        Returns:
            Notes formatted as Markdown.
        """
        zot = get_zotero_client()
        children = zot.children(item_key)
        notes = [
            c["data"].get("note", "")
            for c in children
            if c.get("data", {}).get("itemType") == "note"
        ]
        if not notes:
            return "No notes found."
        return "\n\n---\n\n".join(notes)

    @mcp.tool()
    async def zotero_create_note(item_key: str, note_content: str) -> str:
        """
        Create a note attached to a Zotero item.

        Args:
            item_key: Parent item key.
            note_content: Note body (HTML or plain text).

        Returns:
            Confirmation with the new note's key.
        """
        zot = get_zotero_client()
        template = zot.item_template("note")
        template["note"] = note_content
        template["parentItem"] = item_key
        result = zot.create_items([template])
        created = result.get("successful", {})
        if created:
            new_key = list(created.values())[0].get("key", "unknown")
            return f"Note created with key: {new_key}"
        failed = result.get("failed", {})
        return f"Failed to create note: {failed}"


def _format_annotations_md(annotations: List[Dict[str, Any]]) -> str:
    lines = [f"## Annotations ({len(annotations)} total)\n"]
    for ann in annotations:
        text = ann.get("text", "").strip()
        comment = ann.get("comment", "").strip()
        page = ann.get("page", "")
        ann_type = ann.get("type", "highlight")
        color = ann.get("color", "")

        line = f"> **[{ann_type.capitalize()}]**"
        if page:
            line += f" — Page {page}"
        if color:
            line += f" · {color}"
        lines.append(line)
        if text:
            lines.append(f"> \"{text}\"")
        if comment:
            lines.append(f"\n*{comment}*")
        lines.append("")

    return "\n".join(lines)
