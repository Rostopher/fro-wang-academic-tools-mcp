"""PaperWorkspace — manages the file layout inside a paper_dir."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .metadata import PaperMetadata


class PaperWorkspace:
    """
    Manages the standard file layout for a processed paper directory::

        <paper_dir>/
            full.md                   ← OCR output
            metadata.json             ← unified metadata (extraction + enrichment)
            <stem>_structure.json     ← section structure (LLM extraction)
            <stem>_translated.md      ← translated markdown
            summary_report.md         ← deep-reading report
            images/                   ← embedded images from OCR

    All tools read/write through this class so file naming is consistent.
    """

    METADATA_FILE = "metadata.json"
    OCR_FILE = "full.md"
    SUMMARY_FILE = "summary_report.md"
    SENTINEL_FILE = ".academic_workspace"  # marks directory as a valid paper workspace

    def __init__(self, paper_dir: str | Path) -> None:
        self.dir = Path(paper_dir).expanduser().resolve()

    @property
    def sentinel_path(self) -> Path:
        return self.dir / self.SENTINEL_FILE

    def mark_as_workspace(self) -> None:
        """Write the sentinel file that marks this directory as a paper workspace."""
        self.dir.mkdir(parents=True, exist_ok=True)
        if not self.sentinel_path.exists():
            self.sentinel_path.write_text(
                "academic_tools_workspace\n", encoding="utf-8"
            )

    def is_workspace(self) -> bool:
        """Return True if the sentinel file exists."""
        return self.sentinel_path.exists()

    def require_workspace(self) -> None:
        """Raise if this directory is not a marked paper workspace.

        This is a safety guard for destructive operations (delete, rename).
        Any directory that went through ocr_paper will have the sentinel file.
        Backward-compat: if full.md already exists (old run), auto-stamp the
        sentinel rather than hard-failing, so existing workspaces keep working.
        """
        if self.is_workspace():
            return
        # Graceful upgrade: a directory that already has full.md is treated as
        # a legitimate workspace and gets stamped automatically.
        if self.ocr_markdown.exists():
            self.mark_as_workspace()
            return
        raise PermissionError(
            f"Safety check failed: '{self.dir}' is not a recognised paper "
            f"workspace (missing '{self.SENTINEL_FILE}'). "
            "Only directories that have been initialised by ocr_paper can be "
            "modified or renamed. Pass the correct absolute path."
        )

    # ── Fixed-name files ──────────────────────────────────────

    @property
    def ocr_markdown(self) -> Path:
        return self.dir / self.OCR_FILE

    @property
    def metadata_path(self) -> Path:
        return self.dir / self.METADATA_FILE

    @property
    def summary_path(self) -> Path:
        return self.dir / self.SUMMARY_FILE

    # ── Stem-based files (named after the paper stem) ─────────

    def _stem(self) -> str:
        """Use the folder name as stem (strip trailing version suffixes)."""
        return self.dir.name

    @property
    def structure_path(self) -> Path:
        return self.dir / f"{self._stem()}_structure.json"

    @property
    def translated_path(self) -> Path:
        return self.dir / f"{self._stem()}_translated.md"

    # ── Metadata helpers ──────────────────────────────────────

    def load_metadata(self) -> Optional[PaperMetadata]:
        if not self.metadata_path.exists():
            return None
        try:
            return PaperMetadata.model_validate_json(
                self.metadata_path.read_text(encoding="utf-8")
            )
        except Exception:
            return None

    def save_metadata(self, meta: PaperMetadata) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path.write_text(
            meta.model_dump_json(indent=2, exclude_none=False),
            encoding="utf-8",
        )

    # ── Existence checks ──────────────────────────────────────

    def status(self) -> dict:
        """Return completion status for each pipeline stage."""
        return {
            "paper_dir": str(self.dir),
            "ocr": self.ocr_markdown.exists(),
            "metadata": self.metadata_path.exists(),
            "structure": self.structure_path.exists(),
            "translated": self.translated_path.exists(),
            "summary": self.summary_path.exists(),
        }

    def require_ocr(self) -> Path:
        if not self.ocr_markdown.exists():
            raise FileNotFoundError(
                f"OCR output not found: {self.ocr_markdown}. "
                "Run ocr_paper first."
            )
        return self.ocr_markdown

    def require_metadata(self) -> PaperMetadata:
        meta = self.load_metadata()
        if meta is None:
            raise FileNotFoundError(
                f"metadata.json not found in {self.dir}. "
                "Run extract_metadata first."
            )
        return meta

    def require_structure(self) -> Path:
        if not self.structure_path.exists():
            raise FileNotFoundError(
                f"Structure file not found: {self.structure_path}. "
                "Run extract_sections first."
            )
        return self.structure_path

    def __repr__(self) -> str:
        return f"PaperWorkspace({self.dir})"
