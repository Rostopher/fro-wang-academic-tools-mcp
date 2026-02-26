"""Zotero utility helpers."""

from __future__ import annotations

from typing import Dict, List

from ..config import settings


def format_creators(creators: List[Dict[str, str]]) -> str:
    """Format a Zotero creators list into a human-readable author string."""
    names = []
    for creator in creators:
        if "firstName" in creator and "lastName" in creator:
            names.append(f"{creator['lastName']}, {creator['firstName']}")
        elif "name" in creator:
            names.append(creator["name"])
    return "; ".join(names) if names else "No authors listed"


def is_local_mode() -> bool:
    """Return True if ZOTERO_LOCAL is enabled in settings."""
    return settings.ZOTERO_LOCAL
