"""Helpers for extracting MinerU header/footer style blocks and rendering page markdown."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HEADER_TYPES = {"header", "page_header"}
FOOTER_TYPES = {"footer", "page_footer", "page_footnote", "page_number"}


def _textify(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj.strip()
    if isinstance(obj, (int, float, bool)):
        return str(obj)
    if isinstance(obj, list):
        parts = [_textify(x) for x in obj]
        return " ".join(p for p in parts if p).strip()
    if isinstance(obj, dict):
        priority_keys = [
            "text",
            "content",
            "html",
            "latex",
            "title_content",
            "paragraph_content",
            "table_caption_content",
            "image_caption_content",
            "equation_content",
            "page_footnote_content",
            "page_number_content",
            "page_footer_content",
        ]
        parts: List[str] = []
        for key in priority_keys:
            if key in obj:
                txt = _textify(obj.get(key))
                if txt:
                    parts.append(txt)
        if parts:
            return " ".join(parts).strip()
    return ""


def _normalize_block(block: Dict[str, Any], page_idx: Optional[int], source: str) -> Dict[str, Any]:
    t = str(block.get("type", "")).strip()
    text = _textify(block.get("text")) or _textify(block.get("content"))
    return {
        "source_file": source,
        "page_idx": page_idx,
        "type": t,
        "bbox": block.get("bbox"),
        "text": " ".join(text.split()),
    }


def _extract_from_discarded(data: Any, source: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    def handle_discarded(discarded: Iterable[Any], page_idx: Optional[int]) -> None:
        for blk in discarded:
            if isinstance(blk, dict):
                out.append(_normalize_block(blk, page_idx, source))

    if isinstance(data, dict):
        if isinstance(data.get("discarded_blocks"), list):
            handle_discarded(data["discarded_blocks"], data.get("page_idx"))

        pdf_info = data.get("pdf_info")
        if isinstance(pdf_info, list):
            for pi in pdf_info:
                if not isinstance(pi, dict):
                    continue
                handle_discarded(pi.get("discarded_blocks", []), pi.get("page_idx"))

    if isinstance(data, list):
        for idx, item in enumerate(data):
            if isinstance(item, dict) and isinstance(item.get("discarded_blocks"), list):
                handle_discarded(item["discarded_blocks"], item.get("page_idx", idx))

    return out


def _extract_from_flat_or_page_lists(data: Any, source: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(data, list):
        return out

    if data and all(isinstance(x, dict) for x in data):
        for blk in data:
            out.append(_normalize_block(blk, blk.get("page_idx"), source))
        return out

    for page_idx, page_blocks in enumerate(data):
        if not isinstance(page_blocks, list):
            continue
        for blk in page_blocks:
            if isinstance(blk, dict):
                out.append(_normalize_block(blk, page_idx, source))
    return out


def _collect_blocks_from_file(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    source = path.name
    blocks = _extract_from_discarded(data, source)
    blocks.extend(_extract_from_flat_or_page_lists(data, source))
    return blocks


def _choose_body_source(all_blocks: List[Dict[str, Any]]) -> str:
    for preferred in ("content_list_v2.json", "_model.json", "_content_list.json"):
        candidates = [b for b in all_blocks if preferred in b["source_file"]]
        if candidates:
            return candidates[0]["source_file"]
    return all_blocks[0]["source_file"] if all_blocks else ""


def _block_to_md_line(block: Dict[str, Any]) -> str:
    block_type = block["type"]
    txt = block.get("text", "").strip()
    if not txt:
        return ""
    if block_type in HEADER_TYPES:
        return txt
    if block_type in FOOTER_TYPES:
        return f"> {txt}"
    if block_type in {"title"}:
        return f"### {txt}"
    if block_type in {"table", "image", "equation", "equation_interline"}:
        return f"[{block_type}] {txt}"
    return txt


def _render_first_n_pages_markdown(
    blocks: List[Dict[str, Any]],
    body_source: str,
    pages: int,
) -> str:
    selected = [b for b in blocks if b["source_file"] == body_source]
    lines: List[str] = [
        "# MinerU Header/Footer Extraction (First Pages)",
        "",
        f"- Source JSON: `{body_source}`",
        f"- Pages rendered: 1-{pages}",
        "",
    ]

    for p in range(pages):
        page_blocks = [b for b in selected if b.get("page_idx") == p]
        lines.append(f"## Page {p + 1}")

        headers = [b for b in page_blocks if b.get("type") in HEADER_TYPES and b.get("text")]
        if headers:
            lines.append("**Header**")
            for h in headers:
                lines.append(h["text"])
            lines.append("")

        lines.append("**Content**")
        for b in page_blocks:
            md = _block_to_md_line(b)
            if md:
                lines.append(md)
        if not page_blocks:
            lines.append("(No blocks found)")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def ensure_header_footer_first_pages(
    paper_dir: Path,
    pages: int = 3,
) -> Tuple[Path, Path]:
    """Generate header/footer extraction JSON + first-pages markdown if possible."""
    json_paths = sorted(paper_dir.glob("*.json"))
    if not json_paths:
        raise FileNotFoundError(f"No json files found in: {paper_dir}")

    all_blocks: List[Dict[str, Any]] = []
    for jp in json_paths:
        all_blocks.extend(_collect_blocks_from_file(jp))
    if not all_blocks:
        raise RuntimeError("No parseable blocks found in json files.")

    hf_blocks = [
        b for b in all_blocks
        if b.get("type") in HEADER_TYPES or b.get("type") in FOOTER_TYPES
    ]
    dedup: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for b in hf_blocks:
        key = (
            b.get("source_file"),
            b.get("page_idx"),
            b.get("type"),
            json.dumps(b.get("bbox"), ensure_ascii=False, sort_keys=True),
            b.get("text"),
        )
        dedup[key] = b
    hf_blocks = list(dedup.values())

    json_out = paper_dir / "header_footer_extracted.json"
    json_out.write_text(
        json.dumps(
            {
                "paper_dir": str(paper_dir),
                "header_types": sorted(HEADER_TYPES),
                "footer_types": sorted(FOOTER_TYPES),
                "count": len(hf_blocks),
                "items": hf_blocks,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    body_source = _choose_body_source(all_blocks)
    md_out = paper_dir / f"header_footer_first{max(1, pages)}pages.md"
    md_out.write_text(
        _render_first_n_pages_markdown(all_blocks, body_source=body_source, pages=max(1, pages)),
        encoding="utf-8",
    )
    return json_out, md_out
