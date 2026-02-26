"""General utility functions shared across tools."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Union

# ── Author formatting ─────────────────────────────────────────

_STOPWORDS = {"and", "of", "the", "in", "on", "for", "a", "an", "to", "with", "from", "by"}


def get_surname(full_name: str) -> str:
    """Extract surname from a full name string."""
    if not full_name:
        return "Unknown"
    if "," in full_name:
        return full_name.split(",", 1)[0].strip() or "Unknown"
    parts = [p for p in re.split(r"\s+", full_name.strip()) if p]
    return parts[-1] if parts else "Unknown"


def format_authors(authors: List[Any]) -> str:
    """
    Format a list of authors to a standard string for folder naming.

    Handles list of dicts (with "name" key) or plain strings.

    - 1 author  → "Surname"
    - 2 authors → "Surname1 and Surname2"
    - 3+        → "Surname1 et al"
    """
    if not authors:
        return "Unknown"

    names: List[str] = []
    for a in authors:
        if isinstance(a, str):
            names.append(a.strip())
        elif isinstance(a, dict):
            n = a.get("name", "")
            if n:
                names.append(n.strip())

    names = [n for n in names if n]
    if not names:
        return "Unknown"

    surnames = [get_surname(n) for n in names]
    if len(surnames) == 1:
        return surnames[0]
    if len(surnames) == 2:
        return f"{surnames[0]} and {surnames[1]}"
    return f"{surnames[0]} et al"


# ── Venue / journal formatting ────────────────────────────────

def abbreviate_venue(venue: Optional[str]) -> str:
    """Create a short abbreviation for a journal or conference name."""
    if not venue:
        return "UNKNOWN"
    v = venue.strip()
    if not v:
        return "UNKNOWN"

    # Already looks like an acronym (e.g. "NeurIPS", "ICLR", "AAAI")
    if re.fullmatch(r"[A-Z0-9]{2,10}", v.replace(" ", "")):
        return v.replace(" ", "")

    words = re.findall(r"[A-Za-z0-9]+", v)
    initials = [w[0].upper() for w in words if w.lower() not in _STOPWORDS]
    if len(initials) >= 2:
        return "".join(initials)

    compact = re.sub(r"[^A-Za-z0-9]", "", v)
    return compact[:10].upper() if compact else "UNKNOWN"


# ── Title formatting ──────────────────────────────────────────

def title_first_words(title: Optional[str], limit: int = 5) -> str:
    """Take the first N meaningful words from a title for use in filenames."""
    if not title:
        return "Untitled"
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*", title)
    if not words:
        return "Untitled"
    return " ".join(words[:limit])


# ── Filename sanitization ─────────────────────────────────────

_INVALID_CHARS = r'<>:"/\\|?*'


def sanitize_for_filename(text: str) -> str:
    """Remove / replace characters that are invalid in Windows filenames."""
    if not text:
        return "UNKNOWN"
    cleaned = text
    for ch in _INVALID_CHARS:
        cleaned = cleaned.replace(ch, " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "UNKNOWN"


# ── Misc helpers ──────────────────────────────────────────────

def normalize_doi(doi: Optional[str]) -> Optional[str]:
    """Strip common DOI URL prefixes, returning the bare DOI string."""
    if not doi:
        return None
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            return doi[len(prefix):]
    return doi
