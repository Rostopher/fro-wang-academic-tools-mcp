"""PaperWorkspace manages the file layout inside a paper_dir."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .metadata import PaperMetadata


class PaperWorkspace:
    """
    Manages the standard file layout for a processed paper directory::

        <paper_dir>/
            full.md
            metadata.json
            paper_status.json
            <stem>_structure.json
            <stem>_translated.md
            summary_report.md
            images/

    All tools read/write through this class so file naming is consistent.
    """

    METADATA_FILE = "metadata.json"
    OCR_FILE = "full.md"
    SUMMARY_FILE = "summary_report.md"
    STATUS_FILE = "paper_status.json"
    SENTINEL_FILE = ".academic_workspace"
    STAGE_NAMES = ("ocr", "metadata", "structure", "translate", "summary", "rename")

    def __init__(self, paper_dir: str | Path) -> None:
        self.dir = Path(paper_dir).expanduser().resolve()

    @property
    def sentinel_path(self) -> Path:
        return self.dir / self.SENTINEL_FILE

    def mark_as_workspace(self) -> None:
        """Write the sentinel file that marks this directory as a paper workspace."""
        self.dir.mkdir(parents=True, exist_ok=True)
        if not self.sentinel_path.exists():
            self.sentinel_path.write_text("academic_tools_workspace\n", encoding="utf-8")

    def is_workspace(self) -> bool:
        """Return True if the sentinel file exists."""
        return self.sentinel_path.exists()

    def require_workspace(self) -> None:
        """Raise if this directory is not a marked paper workspace."""
        if self.is_workspace():
            return
        if self.ocr_markdown.exists():
            self.mark_as_workspace()
            return
        raise PermissionError(
            f"Safety check failed: '{self.dir}' is not a recognised paper "
            f"workspace (missing '{self.SENTINEL_FILE}'). "
            "Only directories that have been initialised by ocr_paper can be "
            "modified or renamed. Pass the correct absolute path."
        )

    @property
    def ocr_markdown(self) -> Path:
        return self.dir / self.OCR_FILE

    @property
    def metadata_path(self) -> Path:
        return self.dir / self.METADATA_FILE

    @property
    def summary_path(self) -> Path:
        return self.dir / self.SUMMARY_FILE

    @property
    def status_path(self) -> Path:
        return self.dir / self.STATUS_FILE

    def _stem(self) -> str:
        """Use the folder name as stem."""
        return self.dir.name

    @property
    def structure_path(self) -> Path:
        return self.dir / f"{self._stem()}_structure.json"

    @property
    def translated_path(self) -> Path:
        return self.dir / f"{self._stem()}_translated.md"

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

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat(timespec="seconds")

    @classmethod
    def _default_stage_payload(cls) -> dict[str, dict[str, Any]]:
        return {
            stage: {
                "status": "pending",
                "started_at": None,
                "finished_at": None,
                "artifact": None,
                "error": None,
            }
            for stage in cls.STAGE_NAMES
        }

    @classmethod
    def normalize_stage_status(cls, status: str) -> str:
        normalized = (status or "").strip().lower()
        if normalized in {"success", "already_exists", "unchanged", "dry_run", "done"}:
            return "done"
        if normalized.startswith("skipped") or normalized == "skipped":
            return "skipped"
        if normalized in {"running", "pending", "error"}:
            return normalized
        return normalized or "pending"

    @classmethod
    def overall_status_from_stages(cls, stages: dict[str, dict[str, Any]]) -> str:
        statuses = [
            cls.normalize_stage_status((stages.get(stage) or {}).get("status", "pending"))
            for stage in cls.STAGE_NAMES
        ]
        if any(status == "error" for status in statuses):
            return "error"
        if any(status == "running" for status in statuses):
            return "running"
        if all(status in {"done", "skipped"} for status in statuses):
            return "done"
        return "pending"

    def load_paper_status(self) -> dict[str, Any]:
        if self.status_path.exists():
            try:
                data = json.loads(self.status_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        else:
            data = {}

        stages = self._default_stage_payload()
        raw_stages = data.get("stages") if isinstance(data.get("stages"), dict) else {}
        for stage in self.STAGE_NAMES:
            raw_stage = raw_stages.get(stage)
            if isinstance(raw_stage, dict):
                stages[stage].update(raw_stage)
            stages[stage]["status"] = self.normalize_stage_status(
                str(stages[stage].get("status", "pending"))
            )

        payload = {
            "pdf_source": data.get("pdf_source"),
            "workspace_dir": str(self.dir),
            "created_at": data.get("created_at") or self._now_iso(),
            "updated_at": data.get("updated_at") or self._now_iso(),
            "overall_status": data.get("overall_status") or self.overall_status_from_stages(stages),
            "stages": stages,
        }
        payload["overall_status"] = self.overall_status_from_stages(payload["stages"])
        return payload

    def save_paper_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.load_paper_status()
        current.update(payload)

        stages = self._default_stage_payload()
        raw_stages = current.get("stages") if isinstance(current.get("stages"), dict) else {}
        for stage in self.STAGE_NAMES:
            raw_stage = raw_stages.get(stage)
            if isinstance(raw_stage, dict):
                stages[stage].update(raw_stage)
            stages[stage]["status"] = self.normalize_stage_status(
                str(stages[stage].get("status", "pending"))
            )

        current["stages"] = stages
        current["workspace_dir"] = str(self.dir)
        current.setdefault("created_at", self._now_iso())
        current["updated_at"] = self._now_iso()
        current["overall_status"] = self.overall_status_from_stages(stages)

        self.dir.mkdir(parents=True, exist_ok=True)
        self.status_path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return current

    def update_stage(
        self,
        stage: str,
        status: str,
        *,
        pdf_source: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        artifact: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        if stage not in self.STAGE_NAMES:
            raise ValueError(f"Unknown stage: {stage}")

        payload = self.load_paper_status()
        if pdf_source is not None:
            payload["pdf_source"] = pdf_source

        stage_payload = payload["stages"][stage]
        normalized_status = self.normalize_stage_status(status)
        stage_payload["status"] = normalized_status
        if started_at is not None:
            stage_payload["started_at"] = started_at
        elif normalized_status == "running" and not stage_payload.get("started_at"):
            stage_payload["started_at"] = self._now_iso()

        if finished_at is not None:
            stage_payload["finished_at"] = finished_at
        elif normalized_status in {"done", "skipped", "error"}:
            stage_payload["finished_at"] = self._now_iso()

        if artifact is not None:
            stage_payload["artifact"] = artifact

        if normalized_status == "error":
            stage_payload["error"] = error
        elif error is not None:
            stage_payload["error"] = error
        else:
            stage_payload["error"] = None

        return self.save_paper_status(payload)

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
