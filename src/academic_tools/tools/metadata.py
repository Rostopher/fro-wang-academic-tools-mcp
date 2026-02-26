"""Metadata tool: extract_metadata — LLM extraction + API enrichment in one step.

Pipeline:
  1. Read all text from header_footer_first3pages.md
  2. Call DeepSeek/LLM to extract: title, authors, abstract, doi, year, github
  3. Use doi (preferred) or title to query Crossref → get journal, citation_apa,
     citation_bibtex, citation_count
  4. Use doi or title to query OpenAlex → get openalex_id, referenced_works
  5. Cross-validate: if API title confidence is high, prefer API title
  6. Write unified metadata.json and return it
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP

from ..models.metadata import Author, PaperMetadata
from ..models.paper import PaperWorkspace
from ..shared.llm_client import get_llm_client
from ..shared.prompt_utils import fill_prompt, load_prompt
from ..shared.utils import normalize_doi
from .header_footer import ensure_header_footer_first_pages


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------

async def _llm_extract(text: str) -> Dict[str, Any]:
    """Call LLM to extract structured metadata from paper front matter."""
    prompt_template = load_prompt("metadata_extraction.md")
    prompt = fill_prompt(prompt_template, document=text)
    client = get_llm_client()
    return await client.get_json(user=prompt, temperature=0.0)


# ---------------------------------------------------------------------------
# Academic API enrichment helpers (pure stdlib, no third-party)
# ---------------------------------------------------------------------------

_HEADERS = {"User-Agent": "AcademicToolsMCP/1.0 (mailto:support@example.com)"}


def _http_get(url: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
    req = Request(url, headers=_HEADERS)
    try:
        with urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def _crossref_by_doi(doi: str) -> Optional[Dict[str, Any]]:
    doi = normalize_doi(doi)
    if not doi:
        return None
    return _http_get(f"https://api.crossref.org/works/{doi}")


def _crossref_by_title(title: str, year: Optional[int]) -> Optional[Dict[str, Any]]:
    if not title:
        return None
    params: Dict[str, Any] = {"query.title": title, "rows": 1}
    if year:
        params["filter"] = f"from-pub-date:{year}-01-01,until-pub-date:{year}-12-31"
    data = _http_get(f"https://api.crossref.org/works?{urlencode(params)}")
    items = (data or {}).get("message", {}).get("items", [])
    return {"message": items[0]} if items else None


def _openalex_by_doi(doi: str) -> Optional[Dict[str, Any]]:
    doi_url = f"https://doi.org/{normalize_doi(doi)}"
    data = _http_get(f"https://api.openalex.org/works?{urlencode({'filter': f'doi:{doi_url}', 'per-page': 1})}")
    results = (data or {}).get("results", [])
    return results[0] if results else None


def _openalex_by_title(title: str) -> Optional[Dict[str, Any]]:
    if not title:
        return None
    data = _http_get(f"https://api.openalex.org/works?{urlencode({'search': title, 'per-page': 1})}")
    results = (data or {}).get("results", [])
    return results[0] if results else None


def _parse_crossref(msg_wrapper: Optional[Dict]) -> Dict[str, Any]:
    if not msg_wrapper:
        return {}
    msg = msg_wrapper.get("message", msg_wrapper)

    # Title
    title_field = msg.get("title") or []
    title = title_field[0] if isinstance(title_field, list) and title_field else (title_field or "")

    # Authors
    authors: List[str] = []
    for a in (msg.get("author") or []):
        if not isinstance(a, dict):
            continue
        name = " ".join(filter(None, [a.get("given"), a.get("family")])).strip()
        if name:
            authors.append(name)

    # Journal
    ct = msg.get("container-title") or []
    journal = ct[0] if isinstance(ct, list) and ct else (ct or "")

    # Year
    year = None
    issued = (msg.get("issued") or {}).get("date-parts", [])
    if issued and isinstance(issued, list) and issued[0]:
        try:
            year = int(issued[0][0])
        except (TypeError, ValueError):
            pass

    # DOI
    doi = normalize_doi(msg.get("DOI"))

    # Citation count
    citation_count = msg.get("is-referenced-by-count")

    return {
        "title": title or None,
        "authors": authors,
        "journal": journal or None,
        "publication_year": year,
        "doi": doi,
        "citation_count": citation_count,
    }


def _parse_openalex(oa: Optional[Dict]) -> Dict[str, Any]:
    if not oa:
        return {}
    openalex_id = oa.get("id")
    referenced = oa.get("referenced_works", [])
    return {
        "openalex_id": openalex_id,
        "referenced_works": referenced,
    }


def _fetch_citation_apa(doi: Optional[str]) -> Optional[str]:
    doi = normalize_doi(doi)
    if not doi:
        return None
    req = Request(
        f"https://doi.org/{doi}",
        headers={**_HEADERS, "Accept": "text/x-bibliography; style=apa"},
    )
    try:
        with urlopen(req, timeout=8) as r:
            if r.status != 200:
                return None
            return " ".join(r.read().decode("utf-8", errors="replace").strip().split())
    except Exception:
        return None


def _fetch_citation_bibtex(doi: Optional[str]) -> Optional[str]:
    doi = normalize_doi(doi)
    if not doi:
        return None
    req = Request(
        f"https://doi.org/{doi}",
        headers={**_HEADERS, "Accept": "application/x-bibtex"},
    )
    try:
        with urlopen(req, timeout=8) as r:
            if r.status != 200:
                return None
            return " ".join(r.read().decode("utf-8", errors="replace").strip().split())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main enrichment logic
# ---------------------------------------------------------------------------

def _build_llm_only_metadata(extracted: Dict[str, Any]) -> PaperMetadata:
    """Build metadata from LLM extraction only (no external enrichment)."""
    authors_raw = extracted.get("authors") or []
    authors = [
        Author(
            name=a.get("name", "") if isinstance(a, dict) else str(a),
            institution=a.get("institution") if isinstance(a, dict) else None,
        )
        for a in authors_raw
    ]
    return PaperMetadata(
        title=extracted.get("title") or "",
        authors=authors,
        abstract=extracted.get("abstract"),
        doi=normalize_doi(extracted.get("doi")),
        publication_year=extracted.get("publication_year"),
        github=extracted.get("github"),
        extraction_source="llm",
    )


def _enrich_with_facts(extracted: Dict[str, Any]) -> Tuple[PaperMetadata, Dict[str, Any]]:
    """
    Build metadata with segmented enrichment and return structured enrichment facts.

    Each enrichment stage is isolated so one failure does not hide others:
    - crossref
    - openalex
    - citation
    """
    title = extracted.get("title") or ""
    doi = normalize_doi(extracted.get("doi"))
    year: Optional[int] = extracted.get("publication_year")
    llm_only = _build_llm_only_metadata(extracted)

    facts: Dict[str, Any] = {
        "crossref": {"status": "skipped"},
        "openalex": {"status": "skipped"},
        "citation": {"status": "skipped"},
    }

    # --- Crossref ---
    cr_data: Optional[Dict] = None
    cr: Dict[str, Any] = {}
    try:
        if doi:
            cr_data = _crossref_by_doi(doi)
            if not cr_data and title:
                cr_data = _crossref_by_title(title, year)
        elif title:
            cr_data = _crossref_by_title(title, year)

        cr = _parse_crossref(cr_data)
        facts["crossref"] = {
            "status": "success" if cr_data else "not_found",
            "used_query": "doi" if doi else "title",
            "matched": bool(cr_data),
        }
    except Exception as exc:
        cr_data = None
        cr = {}
        facts["crossref"] = {"status": "error", "error": str(exc)}

    # --- OpenAlex ---
    oa_data: Optional[Dict] = None
    oa: Dict[str, Any] = {}
    try:
        if doi:
            oa_data = _openalex_by_doi(doi)
            if not oa_data and title:
                oa_data = _openalex_by_title(title)
        elif title:
            oa_data = _openalex_by_title(title)

        oa = _parse_openalex(oa_data)
        facts["openalex"] = {
            "status": "success" if oa_data else "not_found",
            "used_query": "doi" if doi else "title",
            "matched": bool(oa_data),
        }
    except Exception as exc:
        oa_data = None
        oa = {}
        facts["openalex"] = {"status": "error", "error": str(exc)}

    # --- DOI resolution (API may give a better DOI) ---
    final_doi = doi or cr.get("doi")

    # --- Cross-validate title: if API found a confident match, prefer its title ---
    api_title = cr.get("title") or ""
    final_title = title
    if api_title and _title_similarity(title, api_title) > 0.7:
        final_title = api_title  # API title is cleaner (proper casing, no OCR artefacts)

    # --- Authors ---
    llm_authors = [a for a in llm_only.authors if a.name]
    api_author_names: List[str] = cr.get("authors") or []
    # Merge: if LLM found fewer authors than API, supplement
    if len(api_author_names) > len(llm_authors):
        llm_authors = [Author(name=n) for n in api_author_names]

    # --- Citations ---
    apa = None
    bibtex = None
    try:
        if final_doi:
            apa = _fetch_citation_apa(final_doi)
            bibtex = _fetch_citation_bibtex(final_doi)
            facts["citation"] = {
                "status": "success" if (apa or bibtex) else "not_found",
                "doi": final_doi,
                "apa_found": bool(apa),
                "bibtex_found": bool(bibtex),
            }
        else:
            facts["citation"] = {"status": "skipped", "reason": "no_doi"}
    except Exception as exc:
        facts["citation"] = {"status": "error", "error": str(exc), "doi": final_doi}

    # Determine enrichment source
    sources = []
    if cr_data:
        sources.append("crossref")
    if oa_data:
        sources.append("openalex")

    metadata = PaperMetadata(
        title=final_title,
        authors=llm_authors,
        abstract=extracted.get("abstract"),
        doi=final_doi,
        publication_year=year or cr.get("publication_year"),
        github=extracted.get("github"),
        journal=cr.get("journal"),
        citation_apa=apa,
        citation_bibtex=bibtex,
        citation_count=cr.get("citation_count"),
        openalex_id=oa.get("openalex_id"),
        referenced_works=oa.get("referenced_works") or [],
        extraction_source="llm",
        enrichment_source="+".join(sources) if sources else None,
    )

    stage_statuses = [
        facts["crossref"].get("status"),
        facts["openalex"].get("status"),
        facts["citation"].get("status"),
    ]
    has_error = any(s == "error" for s in stage_statuses)
    has_success = any(s == "success" for s in stage_statuses)
    has_signal = bool(sources) or bool(apa) or bool(bibtex)
    if has_error:
        enrichment_status = "degraded"
    elif has_success and has_signal:
        enrichment_status = "success"
    else:
        enrichment_status = "no_data"

    facts["enrichment_status"] = enrichment_status
    facts["degraded"] = has_error
    return metadata, facts


def _title_similarity(a: str, b: str) -> float:
    """Very simple character-level overlap ratio."""
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return 0.0
    common = sum(1 for c in set(a) if c in b)
    return common / max(len(set(a)), len(set(b)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

async def _run(paper_dir: str) -> str:
    """Module-level runner (also called by pipeline.py)."""
    ws = PaperWorkspace(paper_dir)
    try:
        ws.require_ocr()
    except FileNotFoundError as exc:
        return json.dumps({"status": "error", "error": str(exc)})

    input_md = ws.dir / "header_footer_first3pages.md"
    if not input_md.exists():
        try:
            _, input_md = ensure_header_footer_first_pages(ws.dir, pages=3)
        except Exception as exc:
            return json.dumps({
                "status": "error",
                "error": f"Failed to prepare metadata input markdown: {exc}",
                "hint": "Ensure MinerU JSON outputs exist in paper_dir before extract_metadata.",
            })

    text = input_md.read_text(encoding="utf-8")

    try:
        extracted = await _llm_extract(text)
    except Exception as exc:
        return json.dumps({"status": "error", "error": f"LLM extraction failed: {exc}"})

    try:
        metadata, enrichment_facts = _enrich_with_facts(extracted)
    except Exception as exc:
        metadata = _build_llm_only_metadata(extracted)
        enrichment_facts = {
            "enrichment_status": "failed",
            "degraded": True,
            "error": str(exc),
            "crossref": {"status": "error"},
            "openalex": {"status": "error"},
            "citation": {"status": "error"},
        }

    ws.save_metadata(metadata)
    return json.dumps({
        "status": "success",
        "output": str(ws.metadata_path),
        "metadata": metadata.model_dump(exclude_none=False),
        "enrichment_facts": enrichment_facts,
    }, ensure_ascii=False, indent=2)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def extract_metadata(paper_dir: str) -> str:
        """
        Extract and enrich paper metadata from an OCR result directory.

        Steps:
        1. Read all text from header_footer_first3pages.md
        2. Call LLM (DeepSeek) to extract title, authors, abstract, doi, year, github
        3. Query Crossref + OpenAlex to enrich with journal, citations, references
        4. Cross-validate title (prefer API title if confidence is high)
        5. Write metadata.json and return it

        Requires:
        - full.md must exist in paper_dir (run ocr_paper first)
        - MinerU JSON outputs should exist; header_footer_first3pages.md will be
          auto-generated when missing

        Args:
            paper_dir: **Absolute** path to the paper directory
                (e.g. ``C:/users/me/papers/2511.00517`` on Windows or
                ``/home/me/papers/2511.00517`` on Linux/macOS).
                Relative paths are resolved against the MCP server's CWD,
                which is unpredictable — always pass an absolute path.

        Returns:
            JSON string with unified status envelope:
            {
              "status": "success" | "error",
              "output": "<paper_dir>/metadata.json",
              "metadata": { ... unified PaperMetadata ... },
              "enrichment_facts": {
                "enrichment_status": "success" | "degraded" | "no_data" | "failed",
                "degraded": true/false,
                "crossref": { ... },
                "openalex": { ... },
                "citation": { ... }
              }
            }
        """
        return await _run(paper_dir)
