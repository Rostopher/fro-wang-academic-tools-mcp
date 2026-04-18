"""Zotero tools (local-first, read-only, no semantic search).

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


def _json_success(**payload: Any) -> str:
    return json.dumps({"status": "success", **payload}, ensure_ascii=False, indent=2)


def _json_error(exc: Exception, *, context: str) -> str:
    return json.dumps(
        {
            "status": "error",
            "error": str(exc),
            "context": context,
        },
        ensure_ascii=False,
        indent=2,
    )


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
            JSON string with search results and formatted Markdown content.
        """
        try:
            zot = get_zotero_client()
            limit = max(1, min(100, limit))
            items = zot.items(q=query, limit=limit)
            if not items:
                return json.dumps({"status": "success", "items": []}, ensure_ascii=False, indent=2)
            parts = [format_item_metadata(item, include_abstract=include_abstract) for item in items]
            return _json_success(
                items=items,
                count=len(items),
                content="\n\n---\n\n".join(parts),
            )
        except Exception as exc:
            return _json_error(exc, context="zotero_search_items")

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
            JSON string with formatted metadata.
        """
        try:
            zot = get_zotero_client()
            item = zot.item(item_key)
            if format == "bibtex":
                return _json_success(item_key=item_key, format="bibtex", content=generate_bibtex(item))
            return _json_success(
                item_key=item_key,
                format="markdown",
                item=item,
                content=format_item_metadata(item, include_abstract=True),
            )
        except Exception as exc:
            return _json_error(exc, context="zotero_get_item_metadata")

    @mcp.tool()
    async def zotero_get_item_fulltext(item_key: str) -> str:
        """
        Get the full text of a Zotero item's best attachment (PDF/HTML).

        Attempts to retrieve via Zotero's full-text index first, then falls
        back to downloading and converting the attachment.

        Args:
            item_key: Zotero item key.

        Returns:
            JSON string with Markdown text of the attachment content.
        """
        try:
            zot = get_zotero_client()

            # Try full-text index first (fast, no download required)
            try:
                fulltext = zot.fulltext_item(item_key)
                if fulltext and fulltext.get("content"):
                    return _json_success(
                        item_key=item_key,
                        source="zotero_fulltext_index",
                        content=fulltext["content"],
                    )
            except Exception:
                pass

            # Fallback: find attachment and convert
            item = zot.item(item_key)
            attachment = get_attachment_details(zot, item)
            if attachment is None:
                return _json_success(item_key=item_key, content="", message="No attachment found for this item.")

            try:
                attachment_file = zot.dump(attachment.key, attachment.filename)
                return _json_success(
                    item_key=item_key,
                    source="attachment",
                    attachment_key=attachment.key,
                    content=convert_to_markdown(attachment_file),
                )
            except Exception as exc:
                if attachment.href:
                    content = convert_to_markdown(attachment.href)
                    if not content.startswith("Error converting file to Markdown:"):
                        return _json_success(
                            item_key=item_key,
                            source="attachment_href",
                            attachment_key=attachment.key,
                            content=content,
                        )
                return _json_error(exc, context="zotero_get_item_fulltext.attachment")
        except Exception as exc:
            return _json_error(exc, context="zotero_get_item_fulltext")

    @mcp.tool()
    async def zotero_get_collections(include_items_count: bool = False) -> str:
        """
        List all collections in the Zotero library with their hierarchy.

        Args:
            include_items_count: Also show number of items per collection.

        Returns:
            JSON string with formatted collection tree.
        """
        try:
            zot = get_zotero_client()
            collections = zot.collections()
            if not collections:
                return _json_success(collections=[], count=0, content="", message="No collections found.")

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

            return _json_success(
                collections=collections,
                count=len(collections),
                content="\n".join(lines),
            )
        except Exception as exc:
            return _json_error(exc, context="zotero_get_collections")

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
            JSON string with collection items and formatted content.
        """
        try:
            zot = get_zotero_client()
            items = zot.collection_items(collection_key, limit=limit)
            if not items:
                return _json_success(
                    collection_key=collection_key,
                    items=[],
                    content="",
                    message="Collection is empty or not found.",
                )
            parts = [format_item_metadata(item, include_abstract=include_abstract) for item in items]
            return _json_success(
                collection_key=collection_key,
                items=items,
                count=len(items),
                content="\n\n---\n\n".join(parts),
            )
        except Exception as exc:
            return _json_error(exc, context="zotero_get_collection_items")

    @mcp.tool()
    async def zotero_get_tags(query: Optional[str] = None) -> str:
        """
        List all tags in the Zotero library.

        Args:
            query: Optional filter string to narrow results.

        Returns:
            JSON string with tag names and formatted content.
        """
        try:
            zot = get_zotero_client()
            tags = zot.tags()
            def tag_name(tag: Any) -> str:
                if isinstance(tag, dict):
                    return str(tag.get("tag", ""))
                return str(tag)

            if query:
                tags = [t for t in tags if query.lower() in tag_name(t).lower()]
            if not tags:
                return _json_success(tags=[], content="", message="No tags found.")
            lines = [f"- {tag_name(t)}" for t in sorted(tags, key=tag_name)]
            return _json_success(tags=tags, count=len(tags), content="\n".join(lines))
        except Exception as exc:
            return _json_error(exc, context="zotero_get_tags")

    @mcp.tool()
    async def zotero_get_recent(limit: int = 10, include_abstract: bool = False) -> str:
        """
        Get recently added/modified items in Zotero.

        Args:
            limit: Number of recent items to return.
            include_abstract: Include abstract.

        Returns:
            JSON string with recent items and formatted content.
        """
        try:
            zot = get_zotero_client()
            items = zot.items(sort="dateModified", direction="desc", limit=limit)
            if not items:
                return _json_success(items=[], content="", message="No items found.")
            parts = [format_item_metadata(item, include_abstract=include_abstract) for item in items]
            return _json_success(
                items=items,
                count=len(items),
                content="\n\n---\n\n".join(parts),
            )
        except Exception as exc:
            return _json_error(exc, context="zotero_get_recent")

    @mcp.tool()
    async def zotero_get_annotations(item_key: str) -> str:
        """
        Get PDF annotations for a Zotero item.

        Tries Better BibTeX (if running), then Zotero API children.

        Args:
            item_key: Zotero item key.

        Returns:
            JSON string with annotations and formatted Markdown.
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
                    return _json_success(
                        item_key=item_key,
                        source="better_bibtex",
                        annotations=annotations,
                        count=len(annotations),
                        content=_format_annotations_md(annotations),
                    )
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
                return _json_success(
                    item_key=item_key,
                    source="zotero_children",
                    annotations=annotations,
                    count=len(annotations),
                    content=_format_annotations_md(annotations),
                )
            return _json_success(
                item_key=item_key,
                annotations=[],
                count=0,
                content="",
                message="No annotations found.",
            )
        except Exception as exc:
            return _json_error(exc, context="zotero_get_annotations")

        return _json_success(item_key=item_key, annotations=[], count=0, content="", message="No annotations found.")

    @mcp.tool()
    async def zotero_get_notes(item_key: str) -> str:
        """
        Get notes attached to a Zotero item.

        Args:
            item_key: Zotero item key.

        Returns:
            JSON string with notes and formatted Markdown.
        """
        try:
            zot = get_zotero_client()
            children = zot.children(item_key)
            notes = [
                c["data"].get("note", "")
                for c in children
                if c.get("data", {}).get("itemType") == "note"
            ]
            if not notes:
                return _json_success(item_key=item_key, notes=[], content="", message="No notes found.")
            return _json_success(
                item_key=item_key,
                notes=notes,
                count=len(notes),
                content="\n\n---\n\n".join(notes),
            )
        except Exception as exc:
            return _json_error(exc, context="zotero_get_notes")


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
