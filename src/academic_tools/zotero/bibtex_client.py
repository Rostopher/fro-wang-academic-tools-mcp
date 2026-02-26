"""Better BibTeX JSON-RPC client — ported from zotero-mcp (lightweight)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import requests


class ZoteroBetterBibTexAPI:
    """
    Thin client for Zotero's Better BibTeX local JSON-RPC API.
    Only works when Zotero desktop + BBT plugin are running.
    """

    def __init__(self, port: str = "23119", database: str = "Zotero") -> None:
        if database == "Juris-M":
            port = "24119"
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}/better-bibtex/json-rpc"
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "python/fro-wang-academic-tools-mcp",
            "Accept": "application/json",
        }

    def _make_request(self, method: str, params: List[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        try:
            resp = requests.post(self.base_url, headers=self.headers, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                err = data["error"]
                raise RuntimeError(f"BBT API error: {err.get('message', err)}")
            return data.get("result", {})
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"Connection error (is Zotero+BBT running?): {exc}")

    def is_zotero_running(self) -> bool:
        """Return True if Zotero + Better BibTeX are accessible."""
        try:
            resp = requests.get(
                f"http://127.0.0.1:{self.port}/better-bibtex/cayw?probe=true",
                headers=self.headers,
                timeout=5,
            )
            return resp.text.strip() == "ready"
        except Exception:
            return False

    def export_bibtex(self, item_key: str, library_id: int = 1) -> str:
        """Export BibTeX for a Zotero item key via BBT."""
        translator_id = "ca65189f-8815-4afe-8c8b-8c7c15f0edca"  # Better BibTeX

        # Step 1: item key → citation key
        mapping = self._make_request("item.citationkey", [[f"{library_id}:{item_key}"]])
        citation_key = mapping.get(f"{library_id}:{item_key}")
        if not citation_key:
            raise RuntimeError(f"No citation key found for {item_key}")

        # Step 2: citation key → BibTeX export
        result = self._make_request("item.export", [[citation_key], translator_id])

        if isinstance(result, str):
            return result
        if isinstance(result, list) and result:
            return result[0] if isinstance(result[0], str) else str(result[0])
        if isinstance(result, dict) and "bibtex" in result:
            return result["bibtex"]
        return str(result)

    def search_citekeys(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search Zotero items by query, return list of {citekey, title, year}."""
        try:
            results = self._make_request("item.search", [query])
            return [
                {
                    "citekey": r["citekey"],
                    "title": r.get("title", ""),
                    "year": r.get("year", ""),
                    "libraryID": r.get("libraryID"),
                }
                for r in (results or [])[:limit]
                if r.get("citekey")
            ]
        except Exception:
            return []

    def get_annotations(self, citekey: str, library_id: int = 1) -> List[Dict[str, Any]]:
        """
        Return annotations for a given citation key.
        Returns a list of processed annotation dicts.
        """
        try:
            attachments = self._make_request("item.attachments", [citekey, library_id])
            annotations = []
            for att in (attachments or []):
                for raw_ann in att.get("annotations", []):
                    annotations.append({
                        "type": raw_ann.get("annotationType", ""),
                        "text": raw_ann.get("annotationText", ""),
                        "comment": raw_ann.get("annotationComment", ""),
                        "page": raw_ann.get("annotationPageLabel", ""),
                        "color": raw_ann.get("annotationColor", ""),
                        "date": raw_ann.get("dateModified", ""),
                    })
            return annotations
        except Exception:
            return []
