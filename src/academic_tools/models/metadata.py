"""Unified paper metadata model — merges basic_meta_data + scholar_metadata."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Author(BaseModel):
    name: str
    institution: Optional[str] = None


class PaperMetadata(BaseModel):
    """
    Single unified metadata model for a paper.

    Populated in two phases:
    - Phase 1 (LLM extraction from OCR text): title, authors, abstract, doi,
      publication_year, github
    - Phase 2 (Academic API enrichment via Crossref / OpenAlex): journal,
      venue_abbr, citation_apa, citation_bibtex, citation_count, openalex_id,
      referenced_works
    """

    # ── Phase 1: LLM extraction ───────────────────────────────
    title: str = ""
    authors: List[Author] = Field(default_factory=list)
    abstract: Optional[str] = None
    doi: Optional[str] = None
    publication_year: Optional[int] = None  # unified — no more year/published_year aliases
    github: Optional[str] = None

    # ── Phase 2: Academic API enrichment ─────────────────────
    journal: Optional[str] = None
    venue_abbr: Optional[str] = None          # abbreviated venue name used in folder rename
    citation_apa: Optional[str] = None
    citation_bibtex: Optional[str] = None
    citation_count: Optional[int] = None      # from Crossref
    openalex_id: Optional[str] = None
    referenced_works: List[str] = Field(default_factory=list)  # OpenAlex work IDs

    # ── Provenance ────────────────────────────────────────────
    extraction_source: Optional[str] = None   # e.g. "llm_deepseek"
    enrichment_source: Optional[str] = None   # "crossref" | "openalex" | "both"

    def is_extraction_complete(self) -> bool:
        """Returns True if Phase 1 fields are filled."""
        return bool(self.title and self.authors)

    def is_enrichment_complete(self) -> bool:
        """Returns True if Phase 2 fields are partially filled."""
        return bool(self.journal or self.citation_bibtex or self.openalex_id)

    def author_names(self) -> List[str]:
        return [a.name for a in self.authors if a.name]
