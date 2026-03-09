from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

from academic_tools.models.paper import PaperWorkspace
from academic_tools.models.queue import ProcessingQueue


if "mcp.server.fastmcp" not in sys.modules:
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")

    class FastMCP:
        def tool(self):
            def decorator(func):
                return func

            return decorator

    fastmcp_module.FastMCP = FastMCP
    server_module = types.ModuleType("mcp.server")
    server_module.fastmcp = fastmcp_module
    mcp_module = types.ModuleType("mcp")
    mcp_module.server = server_module
    sys.modules["mcp"] = mcp_module
    sys.modules["mcp.server"] = server_module
    sys.modules["mcp.server.fastmcp"] = fastmcp_module

if "pydantic_settings" not in sys.modules:
    pydantic_settings_module = types.ModuleType("pydantic_settings")

    class BaseSettings:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    def SettingsConfigDict(**kwargs):
        return kwargs

    pydantic_settings_module.BaseSettings = BaseSettings
    pydantic_settings_module.SettingsConfigDict = SettingsConfigDict
    sys.modules["pydantic_settings"] = pydantic_settings_module

from academic_tools.tools import pipeline


class _CapturingMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


@pytest.fixture(autouse=True)
def _reset_pipeline_job_globals() -> None:
    pipeline.JOB_STORE.clear()
    pipeline.JOB_TASKS.clear()
    pipeline.JOB_LOOP_ID = None
    pipeline._JOB_SEMAPHORE = None


def test_paper_workspace_updates_stage_status(tmp_path: Path) -> None:
    ws = PaperWorkspace(tmp_path / "paper-a")

    ws.update_stage("ocr", "running", pdf_source=str(tmp_path / "a.pdf"))
    running = ws.load_paper_status()
    assert running["overall_status"] == "running"
    assert running["stages"]["ocr"]["status"] == "running"
    assert running["pdf_source"].endswith("a.pdf")

    ws.update_stage("ocr", "success", artifact="full.md")
    done = ws.load_paper_status()
    assert done["stages"]["ocr"]["status"] == "done"
    assert done["stages"]["ocr"]["artifact"] == "full.md"


@pytest.mark.asyncio
async def test_processing_queue_locked_updates(tmp_path: Path) -> None:
    base_dir = tmp_path / "papers"
    ws1 = PaperWorkspace(base_dir / "paper-1")
    ws2 = PaperWorkspace(base_dir / "paper-2")
    ws1.update_stage("ocr", "running", pdf_source=str(base_dir / "1.pdf"))
    ws2.update_stage("ocr", "done", pdf_source=str(base_dir / "2.pdf"), artifact="full.md")

    queue = ProcessingQueue(base_dir)

    async def write_one(ws: PaperWorkspace, job_id: str) -> None:
        await queue.update_locked(
            lambda payload: queue.upsert_paper(
                payload,
                workspace_dir=ws.dir,
                paper_status=ws.load_paper_status(),
                pdf_path=ws.load_paper_status()["pdf_source"],
                job_id=job_id,
            )
        )

    await asyncio.gather(write_one(ws1, "job-1"), write_one(ws2, "job-2"))

    payload = json.loads((base_dir / "processing_queue.json").read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == 2
    assert payload["summary"]["running"] == 1
    assert payload["summary"]["pending"] == 1
    assert payload["summary"]["done"] == 0


@pytest.mark.asyncio
async def test_run_pipeline_writes_status_at_step_completion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paper_dir = tmp_path / "paper-run"

    async def fake_ocr(pdf_path: str, output_dir: str) -> str:
        ws = PaperWorkspace(output_dir)
        ws.dir.mkdir(parents=True, exist_ok=True)
        ws.ocr_markdown.write_text("ocr", encoding="utf-8")
        return json.dumps({"status": "success", "full_md": str(ws.ocr_markdown)})

    async def fake_meta(current_dir: str) -> str:
        ws = PaperWorkspace(current_dir)
        ws.metadata_path.write_text("{}", encoding="utf-8")
        return json.dumps({"status": "success", "output": str(ws.metadata_path)})

    def fake_header_footer(paper_dir: str | Path, pages: int = 3):
        target = Path(paper_dir) / "header_footer_first3pages.md"
        target.write_text("prepared", encoding="utf-8")
        return None, target

    monkeypatch.setattr(pipeline, "_ocr", fake_ocr)
    monkeypatch.setattr(pipeline, "_meta", fake_meta)
    monkeypatch.setattr(pipeline, "ensure_header_footer_first_pages", fake_header_footer)

    result = await pipeline._run_pipeline_impl(
        paper_dir=str(paper_dir),
        pdf_path=str(tmp_path / "source.pdf"),
        steps=["ocr", "metadata"],
        skip_completed=False,
    )

    assert result["status"] == "complete"

    status_payload = json.loads((paper_dir / "paper_status.json").read_text(encoding="utf-8"))
    assert status_payload["stages"]["ocr"]["status"] == "done"
    assert status_payload["stages"]["metadata"]["status"] == "done"
    assert status_payload["stages"]["structure"]["status"] == "skipped"
    assert status_payload["overall_status"] == "done"

    queue_payload = json.loads((tmp_path / "processing_queue.json").read_text(encoding="utf-8"))
    assert queue_payload["summary"]["done"] == 1
    assert queue_payload["papers"][0]["status"] == "done"


@pytest.mark.asyncio
async def test_batch_process_papers_accepts_existing_workspace_without_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_dir = tmp_path / "papers"
    workspace_dir = base_dir / "existing-work"
    ws = PaperWorkspace(workspace_dir)
    ws.mark_as_workspace()
    ws.save_paper_status({"pdf_source": None})

    async def fake_runner(job_id: str) -> None:
        return None

    monkeypatch.setattr(pipeline, "_job_runner", fake_runner)

    mcp = _CapturingMCP()
    pipeline.register(mcp)
    batch_process = mcp.tools["batch_process_papers"]

    raw = await batch_process(
        directory=str(base_dir),
        steps=["metadata"],
        skip_completed=True,
        translate_concurrency=4,
        dry_run_rename=False,
    )
    payload = json.loads(raw)
    assert payload["status"] == "ok"
    assert payload["total"] == 1
    assert payload["started"] == 1
    assert payload["skipped"] == 0
    assert len(payload["job_ids"]) == 1

    queue_payload = json.loads((base_dir / "processing_queue.json").read_text(encoding="utf-8"))
    assert queue_payload["summary"]["total"] == 1
    assert len(queue_payload["papers"]) == 1


@pytest.mark.asyncio
async def test_batch_process_papers_merges_pdf_and_existing_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_dir = tmp_path / "papers"
    base_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = base_dir / "a.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    done_ws = PaperWorkspace(base_dir / "a-work")
    done_ws.mark_as_workspace()
    done_ws.save_paper_status({"pdf_source": str(pdf_path), "stages": {
        "ocr": {"status": "done"},
        "metadata": {"status": "done"},
        "structure": {"status": "done"},
        "translate": {"status": "done"},
        "summary": {"status": "done"},
        "rename": {"status": "done"},
    }})

    orphan_ws = PaperWorkspace(base_dir / "orphan-work")
    orphan_ws.mark_as_workspace()
    orphan_ws.save_paper_status({"pdf_source": None})

    async def fake_runner(job_id: str) -> None:
        return None

    monkeypatch.setattr(pipeline, "_job_runner", fake_runner)

    mcp = _CapturingMCP()
    pipeline.register(mcp)
    batch_process = mcp.tools["batch_process_papers"]

    raw = await batch_process(
        directory=str(base_dir),
        steps=["metadata"],
        skip_completed=True,
        translate_concurrency=4,
        dry_run_rename=False,
    )
    payload = json.loads(raw)
    assert payload["status"] == "ok"
    assert payload["total"] == 2
    assert payload["started"] == 1
    assert payload["skipped"] == 1
    assert len(payload["job_ids"]) == 1

    queue_payload = json.loads((base_dir / "processing_queue.json").read_text(encoding="utf-8"))
    assert queue_payload["summary"]["total"] == 2
    assert len(queue_payload["papers"]) == 2


@pytest.mark.asyncio
async def test_retry_job_rejects_done_state(tmp_path: Path) -> None:
    mcp = _CapturingMCP()
    pipeline.register(mcp)
    retry_job = mcp.tools["retry_job"]

    done_job = pipeline._new_job(
        paper_dir=str(tmp_path / "paper"),
        pdf_path="",
        steps=["metadata"],
        skip_completed=True,
        translate_concurrency=4,
        dry_run_rename=False,
    )
    done_job["state"] = "done"
    done_job["finished_at"] = pipeline._now_iso()

    raw = await retry_job(done_job["job_id"])
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert "Only failed/canceled jobs can be retried." in payload["error"]


@pytest.mark.asyncio
async def test_job_runner_marks_partial_failed_as_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir(parents=True, exist_ok=True)

    async def fake_run_pipeline_impl(**kwargs):
        return {
            "status": "partial_failed",
            "error": "Metadata failed, aborting",
            "final_dir": str(paper_dir),
        }

    async def fake_sync_queue_status(*args, **kwargs):
        return None

    monkeypatch.setattr(pipeline, "_run_pipeline_impl", fake_run_pipeline_impl)
    monkeypatch.setattr(pipeline, "_sync_queue_status", fake_sync_queue_status)

    job = pipeline._new_job(
        paper_dir=str(paper_dir),
        pdf_path="",
        steps=["metadata"],
        skip_completed=True,
        translate_concurrency=4,
        dry_run_rename=False,
    )

    await pipeline._job_runner(job["job_id"])

    saved = pipeline.JOB_STORE[job["job_id"]]
    assert saved["state"] == "error"
    assert saved["error"] == "Metadata failed, aborting"
    assert saved["progress"] == 1.0
