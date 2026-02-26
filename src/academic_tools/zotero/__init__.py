"""Zotero connection layer package (lightweight — no semantic search)."""

from .client import (
    AttachmentDetails,
    convert_to_markdown,
    format_item_metadata,
    generate_bibtex,
    get_attachment_details,
    get_zotero_client,
)
from .utils import format_creators, is_local_mode

__all__ = [
    "AttachmentDetails",
    "convert_to_markdown",
    "format_item_metadata",
    "generate_bibtex",
    "get_attachment_details",
    "get_zotero_client",
    "format_creators",
    "is_local_mode",
]
