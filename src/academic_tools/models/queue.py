"""Persistent processing queue helpers for paper jobs."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .paper import PaperWorkspace


class ProcessingQueue:
    """Manage `processing_queue.json` under a papers base directory."""

    FILE_NAME = "processing_queue.json"
    _locks: dict[str, asyncio.Lock] = {}

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.path = self.base_dir / self.FILE_NAME

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat(timespec="seconds")

    @classmethod
    def _lock_for(cls, path: Path) -> asyncio.Lock:
        key = str(path)
        lock = cls._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            cls._locks[key] = lock
        return lock

    def _default_payload(self) -> dict[str, Any]:
        return {
            "base_dir": str(self.base_dir),
            "updated_at": self._now_iso(),
            "summary": {
                "total": 0,
                "done": 0,
                "running": 0,
                "pending": 0,
                "error": 0,
            },
            "papers": [],
        }

    def load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        else:
            data = {}

        payload = self._default_payload()
        payload.update({k: v for k, v in data.items() if k != "summary"})
        payload["papers"] = payload.get("papers") or []
        payload["summary"] = self.refresh_summary(payload["papers"])
        payload["updated_at"] = self._now_iso()
        payload["base_dir"] = str(self.base_dir)
        return payload

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        payload["base_dir"] = str(self.base_dir)
        payload["papers"] = payload.get("papers") or []
        payload["summary"] = self.refresh_summary(payload["papers"])
        payload["updated_at"] = self._now_iso()

        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)
        return payload

    def relative_path(self, path: str | Path | None) -> str | None:
        if not path:
            return None
        candidate = Path(path).expanduser().resolve()
        try:
            return str(candidate.relative_to(self.base_dir))
        except ValueError:
            return str(candidate)

    def refresh_summary(self, papers: list[dict[str, Any]]) -> dict[str, int]:
        summary = {"total": len(papers), "done": 0, "running": 0, "pending": 0, "error": 0}
        for paper in papers:
            status = str(paper.get("status") or "pending")
            if status not in {"done", "running", "pending", "error"}:
                status = "pending"
            summary[status] += 1
        return summary

    def _find_paper_index(
        self,
        papers: list[dict[str, Any]],
        workspace_dir: str | Path,
        *,
        pdf_path: str | Path | None = None,
        job_id: str | None = None,
    ) -> int | None:
        rel_workspace = self.relative_path(workspace_dir)
        for idx, paper in enumerate(papers):
            if paper.get("workspace_dir") == rel_workspace:
                return idx
        rel_pdf = self.relative_path(pdf_path)
        for idx, paper in enumerate(papers):
            if job_id and paper.get("job_id") == job_id:
                return idx
            if rel_pdf and paper.get("pdf_path") == rel_pdf:
                return idx
        return None

    def _current_stage_from_status(self, paper_status: dict[str, Any]) -> str | None:
        stages = paper_status.get("stages") or {}
        for stage in PaperWorkspace.STAGE_NAMES:
            if (stages.get(stage) or {}).get("status") == "running":
                return stage
        return None

    def _progress_from_status(self, paper_status: dict[str, Any]) -> float:
        stages = paper_status.get("stages") or {}
        total = len(PaperWorkspace.STAGE_NAMES)
        completed = 0.0
        for stage in PaperWorkspace.STAGE_NAMES:
            status = (stages.get(stage) or {}).get("status", "pending")
            if status in {"done", "skipped"}:
                completed += 1.0
            elif status == "running":
                completed += 0.5
        return round(min(completed / max(total, 1), 1.0), 3)

    def upsert_paper(
        self,
        payload: dict[str, Any],
        *,
        workspace_dir: str | Path,
        paper_status: dict[str, Any],
        pdf_path: str | Path | None = None,
        job_id: str | None = None,
        finished_at: str | None = None,
    ) -> dict[str, Any]:
        papers = payload.setdefault("papers", [])
        idx = self._find_paper_index(papers, workspace_dir, pdf_path=pdf_path, job_id=job_id)
        entry = papers[idx] if idx is not None else {}

        overall_status = str(paper_status.get("overall_status") or "pending")
        current_stage = self._current_stage_from_status(paper_status)
        if overall_status == "done":
            current_stage = None

        new_entry = {
            "pdf_path": self.relative_path(pdf_path or paper_status.get("pdf_source")),
            "workspace_dir": self.relative_path(workspace_dir),
            "status": overall_status,
            "current_stage": current_stage,
            "progress": self._progress_from_status(paper_status),
            "error": None,
            "job_id": job_id if job_id is not None else entry.get("job_id"),
            "added_at": entry.get("added_at") or self._now_iso(),
            "finished_at": finished_at,
        }

        if overall_status == "error":
            stages = paper_status.get("stages") or {}
            new_entry["error"] = next(
                (
                    (stages.get(stage) or {}).get("error")
                    for stage in PaperWorkspace.STAGE_NAMES
                    if (stages.get(stage) or {}).get("status") == "error"
                ),
                None,
            )
        elif overall_status == "running":
            new_entry["finished_at"] = None
        elif overall_status == "done":
            new_entry["finished_at"] = finished_at or self._now_iso()

        if idx is None:
            papers.append(new_entry)
        else:
            papers[idx] = new_entry
        payload["summary"] = self.refresh_summary(papers)
        return new_entry

    async def update_locked(self, updater: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
        lock = self._lock_for(self.path)
        async with lock:
            payload = self.load()
            updater(payload)
            return self.save(payload)
