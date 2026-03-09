"""Pipeline orchestration tools.

Long-running workflows can exceed MCP client tool-call timeouts. This module
supports both:
1) direct `process_paper` (best-effort, may timeout on some clients)
2) async job mode via `start/get/cancel` tools
"""

from __future__ import annotations

import asyncio
import json
import random
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from ..config import settings
from ..models.paper import PaperWorkspace
from ..models.queue import ProcessingQueue
from .header_footer import ensure_header_footer_first_pages
from .metadata import _run as _meta
from .ocr import _run as _ocr
from .rename import _run as _rename
from .structure import _run as _structure
from .summary import _run as _summary
from .translate import _run as _translate

ALL_STEPS = ["ocr", "metadata", "structure", "translate", "summary", "rename"]
STEP_ORDER = {name: i for i, name in enumerate(ALL_STEPS, start=1)}
MAX_JOB_EVENTS = 200
JOB_TTL_SECONDS = 24 * 3600
MAX_JOB_STORE_SIZE = 1000
TERMINAL_JOB_STATES = {"done", "error", "canceled"}

JOB_STORE: Dict[str, Dict[str, Any]] = {}
JOB_TASKS: Dict[str, asyncio.Task] = {}
JOB_LOOP_ID: Optional[int] = None
_JOB_SEMAPHORE: Optional[asyncio.Semaphore] = None

STEP_JOKES = {
    "ocr": [
        "OCR is reading faster than my morning coffee kicks in.",
        "Pixels are becoming paragraphs. Civilization advances.",
    ],
    "metadata": [
        "Metadata time: giving your paper a passport.",
        "We are naming things, one citation at a time.",
    ],
    "structure": [
        "Now organizing chaos into sections.",
        "Turning markdown into a map.",
    ],
    "translate": [
        "Translation in progress: same ideas, different words.",
        "Converting research into another language without losing the plot.",
    ],
    "summary": [
        "Summarizing: because we cannot all read 30 pages before lunch.",
        "Compressing signal, keeping the science.",
    ],
    "rename": [
        "Renaming folder so future-you says thanks.",
        "A tidy folder is a happy folder.",
    ],
}


def _is_step_success(status: str) -> bool:
    normalized = status.strip().lower()
    return (
        normalized in ("success", "already_exists", "unchanged", "dry_run")
        or normalized.startswith("skipped")
    )


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_iso(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _prune_jobs() -> None:
    if not JOB_STORE:
        return

    now = datetime.now()
    cutoff = now - timedelta(seconds=JOB_TTL_SECONDS)

    # Remove old terminal jobs by TTL.
    for job_id, job in list(JOB_STORE.items()):
        if job.get("state") not in TERMINAL_JOB_STATES:
            continue
        ts = _parse_iso(str(job.get("finished_at") or job.get("created_at") or ""))
        if ts and ts < cutoff:
            JOB_STORE.pop(job_id, None)
            JOB_TASKS.pop(job_id, None)

    # Keep bounded store size by evicting oldest terminal jobs first.
    overflow = len(JOB_STORE) - MAX_JOB_STORE_SIZE
    if overflow <= 0:
        return

    sortable: List[tuple[str, datetime]] = []
    for job_id, job in JOB_STORE.items():
        if job.get("state") not in TERMINAL_JOB_STATES:
            continue
        ts = _parse_iso(str(job.get("finished_at") or job.get("created_at") or ""))
        sortable.append((job_id, ts or datetime.min))

    sortable.sort(key=lambda item: item[1])
    for job_id, _ in sortable[:overflow]:
        JOB_STORE.pop(job_id, None)
        JOB_TASKS.pop(job_id, None)


def _ensure_job_loop_consistency() -> Optional[dict]:
    global JOB_LOOP_ID

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        return {
            "status": "error",
            "error": "No running event loop found for async job operations.",
        }

    current_loop_id = id(current_loop)
    if JOB_LOOP_ID is None:
        JOB_LOOP_ID = current_loop_id
        return None

    if JOB_LOOP_ID != current_loop_id:
        return {
            "status": "error",
            "error": (
                "Async job loop mismatch: background jobs must run on one persistent event loop."
            ),
            "expected_loop_id": JOB_LOOP_ID,
            "current_loop_id": current_loop_id,
            "hint": "Use a single long-lived FastMCP event loop (default stdio mode).",
        }

    return None


def _emit_progress(step: str, phase: str, message: str) -> None:
    print(f"[process_paper][{_now_iso()}][{step}][{phase}] {message}", file=sys.stderr, flush=True)


def _step_joke(step: str) -> str:
    jokes = STEP_JOKES.get(step, ["One step closer to done."])
    return random.choice(jokes)


def _get_job_semaphore() -> asyncio.Semaphore:
    global _JOB_SEMAPHORE
    if _JOB_SEMAPHORE is None:
        _JOB_SEMAPHORE = asyncio.Semaphore(max(int(settings.MAX_CONCURRENT_JOBS), 1))
    return _JOB_SEMAPHORE


async def _sync_queue_status(
    ws: PaperWorkspace,
    *,
    pdf_path: str = "",
    job_id: Optional[str] = None,
    finished_at: Optional[str] = None,
) -> None:
    queue = ProcessingQueue(ws.dir.parent)
    paper_status = ws.load_paper_status()

    def updater(payload: dict[str, Any]) -> None:
        queue.upsert_paper(
            payload,
            workspace_dir=ws.dir,
            paper_status=paper_status,
            pdf_path=pdf_path,
            job_id=job_id,
            finished_at=finished_at,
        )

    await queue.update_locked(updater)


def _validate_pipeline_input(paper_dir: str, pdf_path: str, steps: List[str]) -> Optional[dict]:
    paper_dir_path = Path(paper_dir).expanduser()
    if paper_dir_path.suffix.lower() == ".pdf":
        return {
            "status": "error",
            "error": (
                "`paper_dir` must be a directory for a single paper workspace, "
                "not a PDF file path."
            ),
            "hint": (
                "Use `paper_dir` like `.../papers/arxiv-2502.08691-work` and "
                "pass the PDF as `pdf_path`."
            ),
        }

    if "ocr" in steps and pdf_path:
        pdf_input = Path(pdf_path).expanduser()
        if pdf_input.exists() and pdf_input.is_dir():
            return {
                "status": "error",
                "error": "`pdf_path` points to a directory. It must be a .pdf file path.",
                "hint": (
                    "Example: `pdf_path='F:/.../papers/arxiv-2502.08691.pdf'`, "
                    "`paper_dir='F:/.../papers/arxiv-2502.08691-work'`."
                ),
            }
        if pdf_input.suffix.lower() != ".pdf":
            return {
                "status": "error",
                "error": "`pdf_path` must end with `.pdf`.",
                "hint": (
                    "Example: `pdf_path='F:/.../papers/arxiv-2502.08691.pdf'`, "
                    "`paper_dir='F:/.../papers/arxiv-2502.08691-work'`."
                ),
            }
    return None


def _build_result_ref(result: dict) -> dict:
    artifacts: List[str] = []
    details = result.get("step_details") or {}
    for detail in details.values():
        if isinstance(detail, dict):
            artifact = detail.get("artifact")
            if artifact:
                artifacts.append(str(artifact))

    # de-duplicate while preserving order
    deduped: List[str] = []
    seen = set()
    for item in artifacts:
        if item not in seen:
            deduped.append(item)
            seen.add(item)

    return {
        "final_dir": result.get("final_dir"),
        "artifacts": deduped,
    }


def _job_event(job_id: str, step: str, phase: str, message: str) -> None:
    _emit_progress(step, phase, message)
    job = JOB_STORE.get(job_id)
    if not job:
        return

    evt = {
        "ts": _now_iso(),
        "step": step,
        "phase": phase,
        "message": message,
    }
    events = job.setdefault("events", [])
    events.append(evt)
    if len(events) > MAX_JOB_EVENTS:
        del events[:-MAX_JOB_EVENTS]

    job["current_step"] = step
    job["last_message"] = message
    if step in STEP_ORDER:
        # start: 0%, end: 100% of current step
        base = (STEP_ORDER[step] - 1) / max(len(ALL_STEPS), 1)
        if phase == "start":
            progress = base
        elif phase in ("end", "skip", "error"):
            progress = STEP_ORDER[step] / max(len(ALL_STEPS), 1)
        else:
            progress = base
        job["progress"] = round(progress, 3)


async def _run_pipeline_impl(
    paper_dir: str,
    pdf_path: str = "",
    steps: Optional[List[str]] = None,
    skip_completed: bool = True,
    translate_concurrency: int = 4,
    dry_run_rename: bool = False,
    job_id: Optional[str] = None,
) -> dict:
    if steps is None:
        steps = ALL_STEPS
    else:
        steps = list(steps)

    invalid = _validate_pipeline_input(paper_dir, pdf_path, steps)
    if invalid:
        return invalid

    ws = PaperWorkspace(paper_dir)
    step_results: dict = {}
    step_details: dict = {}
    current_dir = paper_dir
    if pdf_path:
        ws.save_paper_status({"pdf_source": str(Path(pdf_path).expanduser().resolve())})
    await _sync_queue_status(ws, pdf_path=pdf_path, job_id=job_id)

    def emit(step: str, phase: str, message: str) -> None:
        if job_id:
            _job_event(job_id, step, phase, message)
        else:
            _emit_progress(step, phase, message)

    async def mark_stage(stage: str, status: str, **kwargs: Any) -> None:
        ws.update_stage(stage, status, **kwargs)
        await _sync_queue_status(ws, pdf_path=pdf_path, job_id=job_id)

    async def run_step(name: str, coro) -> bool:
        started_at = _now_iso()
        await mark_stage(name, "running", started_at=started_at)
        emit(name, "start", f"Starting `{name}` step.")
        try:
            raw = await coro
            result = json.loads(raw)
            status = result.get("status", "unknown")
            step_results[name] = status
            artifact = (
                result.get("output")
                or result.get("full_md")
                or result.get("new_path")
                or result.get("output_dir")
            )
            message = f"`{name}` finished with status `{status}`."
            if artifact:
                message += f" Artifact: {artifact}"
            joke = _step_joke(name)
            step_details[name] = {
                "status": status,
                "started_at": started_at,
                "finished_at": _now_iso(),
                "message": message,
                "joke": joke,
                "artifact": artifact,
            }
            await mark_stage(
                name,
                status,
                started_at=started_at,
                finished_at=step_details[name]["finished_at"],
                artifact=str(artifact) if artifact else None,
                error=result.get("error"),
            )
            emit(name, "end", f"{message} {joke}")
            return status in ("success", "already_exists", "unchanged", "dry_run")
        except asyncio.CancelledError:
            await mark_stage(name, "error", started_at=started_at, error="Job canceled by user.")
            raise
        except Exception as exc:
            step_results[name] = f"error: {exc}"
            step_details[name] = {
                "status": "error",
                "started_at": started_at,
                "finished_at": _now_iso(),
                "message": f"`{name}` crashed with exception: {exc}",
                "joke": "Even good pipelines trip sometimes.",
            }
            await mark_stage(
                name,
                "error",
                started_at=started_at,
                finished_at=step_details[name]["finished_at"],
                error=str(exc),
            )
            emit(name, "error", f"`{name}` crashed: {exc}")
            return False

    # --- Step 1: OCR ---
    if "ocr" in steps:
        if skip_completed and (ws.dir / "full.md").exists():
            await mark_stage("ocr", "done", artifact=str(ws.dir / "full.md"))
            step_results["ocr"] = "already_exists"
            step_details["ocr"] = {
                "status": "already_exists",
                "started_at": None,
                "finished_at": _now_iso(),
                "message": "OCR skipped because full.md already exists.",
                "joke": _step_joke("ocr"),
                "artifact": str(ws.dir / "full.md"),
            }
            emit("ocr", "skip", "OCR skipped: full.md already exists.")
        elif not pdf_path:
            await mark_stage("ocr", "skipped")
            step_results["ocr"] = "skipped (no pdf_path)"
            step_details["ocr"] = {
                "status": "skipped (no pdf_path)",
                "started_at": None,
                "finished_at": _now_iso(),
                "message": "OCR skipped because no `pdf_path` was provided.",
                "joke": _step_joke("ocr"),
            }
            emit("ocr", "skip", "OCR skipped: no pdf_path.")
        else:
            ok = await run_step("ocr", _ocr(pdf_path, paper_dir))
            if not ok:
                return {
                    "steps": step_results,
                    "step_details": step_details,
                    "error": "OCR failed, aborting",
                    "status": "partial_failed",
                    "final_dir": current_dir,
                }
    else:
        await mark_stage("ocr", "skipped")
        step_results["ocr"] = "skipped"
        step_details["ocr"] = {
            "status": "skipped",
            "started_at": None,
            "finished_at": _now_iso(),
            "message": "OCR skipped because it is not in `steps`.",
            "joke": _step_joke("ocr"),
        }

    # --- Step 2: Metadata ---
    if "metadata" in steps:
        if skip_completed and ws.metadata_path.exists():
            await mark_stage("metadata", "done", artifact=str(ws.metadata_path))
            step_results["metadata"] = "already_exists"
            step_details["metadata"] = {
                "status": "already_exists",
                "started_at": None,
                "finished_at": _now_iso(),
                "message": "Metadata skipped because metadata.json already exists.",
                "joke": _step_joke("metadata"),
                "artifact": str(ws.metadata_path),
            }
            emit("metadata", "skip", "Metadata skipped: metadata.json already exists.")
        else:
            input_md = ws.dir / "header_footer_first3pages.md"
            if not input_md.exists():
                emit("metadata", "start", "Preparing metadata input markdown from MinerU JSON.")
                try:
                    _, generated_md = ensure_header_footer_first_pages(ws.dir, pages=3)
                    emit("metadata", "end", f"Prepared metadata input markdown: {generated_md}")
                except Exception as exc:
                    await mark_stage("metadata", "error", error=str(exc))
                    step_results["metadata"] = f"error: {exc}"
                    step_details["metadata"] = {
                        "status": "error",
                        "started_at": None,
                        "finished_at": _now_iso(),
                        "message": f"Failed to prepare metadata input markdown: {exc}",
                        "joke": "Even good pipelines trip sometimes.",
                    }
                    emit("metadata", "error", f"Failed to prepare metadata input markdown: {exc}")
                    return {
                        "steps": step_results,
                        "step_details": step_details,
                        "error": "Metadata failed, aborting",
                        "status": "partial_failed",
                        "final_dir": current_dir,
                    }
            ok = await run_step("metadata", _meta(current_dir))
            if not ok:
                return {
                    "steps": step_results,
                    "step_details": step_details,
                    "error": "Metadata failed, aborting",
                    "status": "partial_failed",
                    "final_dir": current_dir,
                }
    else:
        await mark_stage("metadata", "skipped")
        step_results["metadata"] = "skipped"
        step_details["metadata"] = {
            "status": "skipped",
            "started_at": None,
            "finished_at": _now_iso(),
            "message": "Metadata skipped because it is not in `steps`.",
            "joke": _step_joke("metadata"),
        }

    # --- Step 3: Structure ---
    if "structure" in steps:
        if skip_completed and ws.structure_path.exists():
            await mark_stage("structure", "done", artifact=str(ws.structure_path))
            step_results["structure"] = "already_exists"
            step_details["structure"] = {
                "status": "already_exists",
                "started_at": None,
                "finished_at": _now_iso(),
                "message": "Structure skipped because structure JSON already exists.",
                "joke": _step_joke("structure"),
                "artifact": str(ws.structure_path),
            }
            emit("structure", "skip", "Structure skipped: structure JSON already exists.")
        else:
            ok = await run_step("structure", _structure(current_dir))
            if not ok:
                return {
                    "steps": step_results,
                    "step_details": step_details,
                    "error": "Structure failed, aborting",
                    "status": "partial_failed",
                    "final_dir": current_dir,
                }
    else:
        await mark_stage("structure", "skipped")
        step_results["structure"] = "skipped"
        step_details["structure"] = {
            "status": "skipped",
            "started_at": None,
            "finished_at": _now_iso(),
            "message": "Structure skipped because it is not in `steps`.",
            "joke": _step_joke("structure"),
        }

    # --- Step 4: Translate ---
    if "translate" in steps:
        if skip_completed and ws.translated_path.exists():
            await mark_stage("translate", "done", artifact=str(ws.translated_path))
            step_results["translate"] = "already_exists"
            step_details["translate"] = {
                "status": "already_exists",
                "started_at": None,
                "finished_at": _now_iso(),
                "message": "Translate skipped because translated markdown already exists.",
                "joke": _step_joke("translate"),
                "artifact": str(ws.translated_path),
            }
            emit("translate", "skip", "Translate skipped: translated markdown already exists.")
        else:
            ok = await run_step("translate", _translate(current_dir, translate_concurrency))
            if not ok:
                return {
                    "steps": step_results,
                    "step_details": step_details,
                    "error": "Translate failed, aborting",
                    "status": "partial_failed",
                    "final_dir": current_dir,
                }
    else:
        await mark_stage("translate", "skipped")
        step_results["translate"] = "skipped"
        step_details["translate"] = {
            "status": "skipped",
            "started_at": None,
            "finished_at": _now_iso(),
            "message": "Translate skipped because it is not in `steps`.",
            "joke": _step_joke("translate"),
        }

    # --- Step 5: Summary ---
    if "summary" in steps:
        if skip_completed and ws.summary_path.exists():
            await mark_stage("summary", "done", artifact=str(ws.summary_path))
            step_results["summary"] = "already_exists"
            step_details["summary"] = {
                "status": "already_exists",
                "started_at": None,
                "finished_at": _now_iso(),
                "message": "Summary skipped because summary_report.md already exists.",
                "joke": _step_joke("summary"),
                "artifact": str(ws.summary_path),
            }
            emit("summary", "skip", "Summary skipped: summary_report.md already exists.")
        else:
            ok = await run_step("summary", _summary(current_dir))
            if not ok:
                return {
                    "steps": step_results,
                    "step_details": step_details,
                    "error": "Summary failed, aborting",
                    "status": "partial_failed",
                    "final_dir": current_dir,
                }
    else:
        await mark_stage("summary", "skipped")
        step_results["summary"] = "skipped"
        step_details["summary"] = {
            "status": "skipped",
            "started_at": None,
            "finished_at": _now_iso(),
            "message": "Summary skipped because it is not in `steps`.",
            "joke": _step_joke("summary"),
        }

    # --- Step 6: Rename ---
    if "rename" in steps:
        rename_started_at = _now_iso()
        await mark_stage("rename", "running", started_at=rename_started_at)
        emit("rename", "start", "Starting `rename` step.")
        try:
            rename_result_raw = await _rename(current_dir, dry_run=dry_run_rename)
            rename_result = json.loads(rename_result_raw)
            rename_status = rename_result.get("status", "unknown")
            step_results["rename"] = rename_status
            rename_artifact = rename_result.get("new_path")
            rename_message = f"`rename` finished with status `{rename_status}`."
            if rename_artifact:
                rename_message += f" Artifact: {rename_artifact}"
            rename_joke = _step_joke("rename")
            step_details["rename"] = {
                "status": rename_status,
                "started_at": rename_started_at,
                "finished_at": _now_iso(),
                "message": rename_message,
                "joke": rename_joke,
                "artifact": rename_artifact,
            }
            if rename_status == "success":
                current_dir = rename_result.get("new_path", current_dir)
                ws = PaperWorkspace(current_dir)
            await mark_stage(
                "rename",
                rename_status,
                started_at=rename_started_at,
                finished_at=step_details["rename"]["finished_at"],
                artifact=str(rename_artifact) if rename_artifact else None,
                error=rename_result.get("error"),
            )
            emit("rename", "end", f"{rename_message} {rename_joke}")
        except Exception as exc:
            step_results["rename"] = f"error: {exc}"
            step_details["rename"] = {
                "status": "error",
                "started_at": rename_started_at,
                "finished_at": _now_iso(),
                "message": f"`rename` crashed with exception: {exc}",
                "joke": "Even good pipelines trip sometimes.",
            }
            await mark_stage(
                "rename",
                "error",
                started_at=rename_started_at,
                finished_at=step_details["rename"]["finished_at"],
                error=str(exc),
            )
            emit("rename", "error", f"`rename` crashed: {exc}")
    else:
        await mark_stage("rename", "skipped")
        step_results["rename"] = "skipped"
        step_details["rename"] = {
            "status": "skipped",
            "started_at": None,
            "finished_at": _now_iso(),
            "message": "Rename skipped because it is not in `steps`.",
            "joke": _step_joke("rename"),
        }

    return {
        "steps": step_results,
        "step_details": step_details,
        "final_dir": current_dir,
        "status": (
            "complete"
            if all(_is_step_success(s) for s in step_results.values())
            else "partial_failed"
        ),
    }


def _new_job(
    *,
    paper_dir: str,
    pdf_path: str,
    steps: List[str],
    skip_completed: bool,
    translate_concurrency: int,
    dry_run_rename: bool,
) -> dict:
    _prune_jobs()
    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "state": "queued",
        "progress": 0.0,
        "current_step": None,
        "last_message": "Job queued.",
        "created_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "events": [],
        "request": {
            "paper_dir": paper_dir,
            "pdf_path": pdf_path,
            "steps": steps,
            "skip_completed": skip_completed,
            "translate_concurrency": translate_concurrency,
            "dry_run_rename": dry_run_rename,
        },
        "result": None,
        "error": None,
        "result_ref": None,
    }
    JOB_STORE[job_id] = job
    return job


async def _job_runner(job_id: str) -> None:
    job = JOB_STORE[job_id]
    req = job["request"]
    sem = _get_job_semaphore()
    async with sem:
        job["state"] = "running"
        job["started_at"] = _now_iso()
        job["last_message"] = "Job started."
        _job_event(job_id, "system", "start", "Background job started.")

        try:
            result = await _run_pipeline_impl(
                paper_dir=req["paper_dir"],
                pdf_path=req["pdf_path"],
                steps=req["steps"],
                skip_completed=req["skip_completed"],
                translate_concurrency=req["translate_concurrency"],
                dry_run_rename=req["dry_run_rename"],
                job_id=job_id,
            )
            job["result"] = result
            job["result_ref"] = _build_result_ref(result)
            if result.get("status") == "complete":
                job["state"] = "done"
                job["progress"] = 1.0
                job["last_message"] = f"Job finished with status `{result.get('status')}`."
            elif result.get("status") == "partial_failed":
                job["state"] = "error"
                job["error"] = result.get("error", "partial_failed")
                job["progress"] = 1.0
                job["last_message"] = f"Job partially failed: {job['error']}"
            else:
                job["state"] = "error"
                job["error"] = result.get("error", "unknown error")
                job["last_message"] = f"Job failed: {job['error']}"
        except asyncio.CancelledError:
            job["state"] = "canceled"
            job["last_message"] = "Job canceled by user."
        except Exception as exc:
            job["state"] = "error"
            job["error"] = str(exc)
            job["last_message"] = f"Job crashed: {exc}"
            _job_event(job_id, "system", "error", job["last_message"])
        finally:
            job["finished_at"] = _now_iso()
            final_dir = None
            if isinstance(job.get("result"), dict):
                final_dir = job["result"].get("final_dir")
            await _sync_queue_status(
                PaperWorkspace(final_dir or req["paper_dir"]),
                pdf_path=req["pdf_path"],
                job_id=job_id,
                finished_at=job["finished_at"],
            )
            JOB_TASKS.pop(job_id, None)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def process_paper(
        paper_dir: str,
        pdf_path: str = "",
        steps: List[str] = ALL_STEPS,
        skip_completed: bool = True,
        translate_concurrency: int = 4,
        dry_run_rename: bool = False,
    ) -> str:
        """
        Run the complete paper processing pipeline in a single call.

        Warning: some MCP clients enforce ~60s tool-call timeout. For long runs,
        prefer async job tools:
        - start_process_paper_job
        - get_process_paper_job
        - cancel_process_paper_job

        Args:
            paper_dir: **Absolute** path to the paper workspace directory
                (e.g. ``C:/users/me/papers/2511.00517``).
                Relative paths are resolved against the MCP server's CWD,
                which is unpredictable — always pass an absolute path.
            pdf_path: **Absolute** path to the source PDF file. Required only
                when ``ocr`` is included in ``steps``.
            steps: List of pipeline steps to run. Default: all steps.
            skip_completed: Skip steps whose output files already exist.
            translate_concurrency: Parallel LLM calls for translation.
            dry_run_rename: Preview rename without writing.
        """
        result = await _run_pipeline_impl(
            paper_dir=paper_dir,
            pdf_path=pdf_path,
            steps=steps,
            skip_completed=skip_completed,
            translate_concurrency=translate_concurrency,
            dry_run_rename=dry_run_rename,
            job_id=None,
        )
        return json.dumps(result)

    @mcp.tool()
    async def start_process_paper_job(
        paper_dir: str,
        pdf_path: str = "",
        steps: List[str] = ALL_STEPS,
        skip_completed: bool = True,
        translate_concurrency: int = 4,
        dry_run_rename: bool = False,
    ) -> str:
        """Start pipeline in background and return a `job_id` immediately.

        Use get_process_paper_job to poll progress, cancel_process_paper_job to abort.

        This is also the recommended fallback when `ocr_paper` times out: call
        this tool with steps=["ocr"] (and the remaining steps) instead of retrying
        ocr_paper directly.

        Returns immediately with:
            {"status": "accepted", "job_id": "...", "state": "queued",
             "poll_tool": "get_process_paper_job"}

        Args:
            paper_dir: **Absolute** path to the paper workspace directory
                (e.g. ``C:/users/me/papers/2511.00517``).
                Relative paths are resolved against the MCP server's CWD,
                which is unpredictable — always pass an absolute path.
            pdf_path: **Absolute** path to the source PDF. Required only when
                ``ocr`` is included in ``steps``.
            steps: Pipeline steps to run. Default: all steps.
            skip_completed: Skip steps whose output already exists.
            translate_concurrency: Parallel LLM calls for translation.
            dry_run_rename: Preview rename without writing.
        """
        loop_error = _ensure_job_loop_consistency()
        if loop_error:
            return json.dumps(loop_error)
        _prune_jobs()
        invalid = _validate_pipeline_input(paper_dir, pdf_path, steps)
        if invalid:
            return json.dumps(invalid)

        job = _new_job(
            paper_dir=paper_dir,
            pdf_path=pdf_path,
            steps=list(steps),
            skip_completed=skip_completed,
            translate_concurrency=translate_concurrency,
            dry_run_rename=dry_run_rename,
        )
        task = asyncio.create_task(_job_runner(job["job_id"]))
        JOB_TASKS[job["job_id"]] = task

        return json.dumps({
            "status": "accepted",
            "job_id": job["job_id"],
            "state": "queued",
            "poll_tool": "get_process_paper_job",
            "cancel_tool": "cancel_process_paper_job",
            "message": "Background job created. Poll with `get_process_paper_job`.",
        })

    @mcp.tool()
    async def get_process_paper_job(
        job_id: str,
        include_result: bool = False,
        max_events: int = 20,
    ) -> str:
        """Get async job state/progress and (optionally) final result."""
        _prune_jobs()
        job = JOB_STORE.get(job_id)
        if not job:
            return json.dumps({
                "status": "error",
                "error": f"Job not found: {job_id}",
            })

        if max_events < 1:
            max_events = 1
        events = job.get("events", [])
        tail = events[-max_events:]

        payload: Dict[str, Any] = {
            "status": "ok",
            "job_id": job_id,
            "state": job["state"],
            "progress": job.get("progress", 0.0),
            "current_step": job.get("current_step"),
            "message": job.get("last_message"),
            "created_at": job.get("created_at"),
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "events": tail,
            "result_ref": job.get("result_ref"),
            "error": job.get("error"),
        }
        if include_result and job.get("result") is not None:
            payload["result"] = job["result"]
        return json.dumps(payload)

    @mcp.tool()
    async def cancel_process_paper_job(job_id: str) -> str:
        """Cancel a running background process_paper job."""
        loop_error = _ensure_job_loop_consistency()
        if loop_error:
            return json.dumps(loop_error)
        _prune_jobs()
        job = JOB_STORE.get(job_id)
        if not job:
            return json.dumps({
                "status": "error",
                "error": f"Job not found: {job_id}",
            })

        task = JOB_TASKS.get(job_id)
        if not task:
            return json.dumps({
                "status": "ok",
                "job_id": job_id,
                "state": job["state"],
                "message": "No running task found for this job.",
            })

        if task.done():
            return json.dumps({
                "status": "ok",
                "job_id": job_id,
                "state": job["state"],
                "message": "Task is already finished.",
            })

        task.cancel()
        job["state"] = "canceling"
        job["last_message"] = "Cancel signal sent."
        _job_event(job_id, "system", "cancel", "Cancel signal sent by user.")
        return json.dumps({
            "status": "ok",
            "job_id": job_id,
            "state": "canceling",
            "message": "Cancel signal sent.",
        })

    @mcp.tool()
    async def batch_process_papers(
        directory: str,
        steps: List[str] = ALL_STEPS,
        skip_completed: bool = True,
        translate_concurrency: int = 4,
        dry_run_rename: bool = False,
    ) -> str:
        """
        Scan a directory for all papers (PDFs and existing workspaces), then
        start batch processing jobs with controlled concurrency.

        This tool:
        1. Scans `directory` for all *.pdf files and existing workspaces
        2. For each PDF, creates/uses workspace directory (PDF stem + "-work")
        3. Initializes processing_queue.json with all discovered papers
        4. Starts background jobs (concurrency controlled by `MAX_CONCURRENT_JOBS`)
        5. Returns immediately with batch summary

        Use get_batch_status() to monitor progress.

        Args:
            directory: **Absolute** path to the papers base directory
                (e.g. ``F:/papers``).
            steps: List of pipeline steps to run. Default: all steps.
            skip_completed: Skip steps whose output files already exist.
            translate_concurrency: Parallel LLM calls for translation.
            dry_run_rename: Preview rename without writing.

        Returns:
            JSON with batch summary: {total, started, skipped, queue_file, job_ids}
        """
        loop_error = _ensure_job_loop_consistency()
        if loop_error:
            return json.dumps(loop_error)

        base_dir = Path(directory).expanduser().resolve()
        if not base_dir.exists():
            return json.dumps({
                "status": "error",
                "error": f"Directory does not exist: {base_dir}",
            })
        if not base_dir.is_dir():
            return json.dumps({
                "status": "error",
                "error": f"Path is not a directory: {base_dir}",
            })

        # Scan for PDFs and existing workspaces.
        pdf_files = sorted(base_dir.glob("*.pdf"))
        workspace_dirs = sorted(
            (
                subdir
                for subdir in base_dir.iterdir()
                if subdir.is_dir() and PaperWorkspace(subdir).is_workspace()
            ),
            key=lambda item: item.name.lower(),
        )
        if not pdf_files and not workspace_dirs:
            return json.dumps({
                "status": "error",
                "error": (
                    "No input papers found. Expected at least one top-level *.pdf "
                    "or one existing workspace directory."
                ),
            })

        # Initialize queue
        queue = ProcessingQueue(base_dir)
        queue_payload = queue.load()
        job_ids: List[str] = []
        skipped_count = 0
        discovered_count = 0

        # Build a merged input set keyed by workspace dir.
        candidates: dict[str, dict[str, Any]] = {}
        for pdf_path in pdf_files:
            workspace_dir = base_dir / f"{pdf_path.stem}-work"
            candidates[str(workspace_dir)] = {
                "workspace_dir": workspace_dir,
                "pdf_source": str(pdf_path.resolve()),
                "source": "pdf",
            }
        for workspace_dir in workspace_dirs:
            key = str(workspace_dir)
            if key not in candidates:
                candidates[key] = {
                    "workspace_dir": workspace_dir,
                    "pdf_source": None,
                    "source": "workspace",
                }

        for item in candidates.values():
            workspace_dir = item["workspace_dir"]
            ws = PaperWorkspace(workspace_dir)
            if not ws.is_workspace():
                ws.mark_as_workspace()

            existing_status = ws.load_paper_status()
            discovered_count += 1

            # Prefer explicit pdf source from discovery, fall back to existing status.
            pdf_source = item["pdf_source"] or existing_status.get("pdf_source")
            if pdf_source:
                ws.save_paper_status({"pdf_source": str(Path(pdf_source).expanduser().resolve())})
            paper_status = ws.load_paper_status()

            # Check if already completed (if skip_completed)
            if skip_completed and paper_status.get("overall_status", "pending") == "done":
                queue.upsert_paper(
                    queue_payload,
                    workspace_dir=workspace_dir,
                    paper_status=paper_status,
                    pdf_path=pdf_source,
                    job_id=None,
                    finished_at=_now_iso(),
                )
                skipped_count += 1
                continue

            # Queue the paper.
            queue.upsert_paper(
                queue_payload,
                workspace_dir=workspace_dir,
                paper_status=paper_status,
                pdf_path=pdf_source,
                job_id=None,
            )

            # Create job.
            job = _new_job(
                paper_dir=str(workspace_dir),
                pdf_path=str(pdf_source or ""),
                steps=list(steps),
                skip_completed=skip_completed,
                translate_concurrency=translate_concurrency,
                dry_run_rename=dry_run_rename,
            )
            job_ids.append(job["job_id"])

        # Save queue with all papers
        queue.save(queue_payload)

        # Start tasks (respecting the global semaphore configured by MAX_CONCURRENT_JOBS)
        started_count = 0
        for job_id in job_ids:
            task = asyncio.create_task(_job_runner(job_id))
            JOB_TASKS[job_id] = task
            started_count += 1

        return json.dumps({
            "status": "ok",
            "total": discovered_count,
            "started": started_count,
            "skipped": skipped_count,
            "queue_file": str(queue.path),
            "job_ids": job_ids,
            "message": (
                f"Batch started: discovered {discovered_count}, started {started_count}, "
                f"skipped {skipped_count}. Monitor with get_batch_status()."
            ),
        })

    @mcp.tool()
    async def get_batch_status(
        directory: str,
    ) -> str:
        """
        Read the processing_queue.json file in the specified directory
        and return a batch processing status summary.

        If the queue file doesn't exist, scans all subdirectories for
        paper_status.json files and builds a summary.

        Args:
            directory: **Absolute** path to the papers base directory.

        Returns:
            JSON with batch status: {total, done, running, pending, error, papers}
        """
        base_dir = Path(directory).expanduser().resolve()
        if not base_dir.exists():
            return json.dumps({
                "status": "error",
                "error": f"Directory does not exist: {base_dir}",
            })

        queue = ProcessingQueue(base_dir)
        if not queue.path.exists():
            # Fallback: scan subdirectories
            workspaces: List[Dict[str, Any]] = []
            for subdir in base_dir.iterdir():
                if subdir.is_dir():
                    ws = PaperWorkspace(subdir)
                    if ws.is_workspace():
                        paper_status = ws.load_paper_status()
                        workspaces.append({
                            "workspace_dir": str(subdir),
                            "status": paper_status.get("overall_status", "pending"),
                            "stages": paper_status.get("stages", {}),
                        })

            summary = {"total": len(workspaces), "done": 0, "running": 0, "pending": 0, "error": 0}
            for w in workspaces:
                status = w.get("status", "pending")
                if status in summary:
                    summary[status] += 1

            return json.dumps({
                "status": "ok",
                "summary": summary,
                "papers": workspaces,
                "source": "scanned",
            })

        payload = queue.load()
        return json.dumps({
            "status": "ok",
            "summary": payload.get("summary", {}),
            "papers": payload.get("papers", []),
            "queue_file": str(queue.path),
            "updated_at": payload.get("updated_at"),
            "source": "queue_file",
        })

    @mcp.tool()
    async def list_jobs(
        state: str = "",
        limit: int = 50,
    ) -> str:
        """
        List all background jobs in memory with optional filtering.

        Args:
            state: Filter by job state. Options: "", "queued", "running",
                "done", "error", "canceled". Empty string returns all.
            limit: Maximum number of jobs to return. Default: 50.

        Returns:
            JSON with list of job summaries.
        """
        _prune_jobs()

        valid_states = {"", "queued", "running", "done", "error", "canceled"}
        if state not in valid_states:
            return json.dumps({
                "status": "error",
                "error": f"Invalid state: {state}. Valid: {valid_states}",
            })

        jobs = []
        for job_id, job in JOB_STORE.items():
            job_state = job.get("state", "")
            if state and job_state != state:
                continue
            jobs.append({
                "job_id": job_id,
                "state": job_state,
                "progress": job.get("progress", 0.0),
                "current_step": job.get("current_step"),
                "message": job.get("last_message"),
                "created_at": job.get("created_at"),
                "started_at": job.get("started_at"),
                "finished_at": job.get("finished_at"),
                "paper_dir": job.get("request", {}).get("paper_dir"),
                "error": job.get("error"),
            })

        # Sort by created_at descending
        jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        jobs = jobs[:limit]

        return json.dumps({
            "status": "ok",
            "count": len(jobs),
            "jobs": jobs,
        })

    @mcp.tool()
    async def retry_job(
        job_id: str,
    ) -> str:
        """
        Retry a failed job (`error`) or a canceled job (`canceled`)
        with the same parameters.

        Automatically skips completed stages by checking file existence
        and paper_status.json.

        Args:
            job_id: The job_id of the job to retry.

        Returns:
            JSON with new job_id and status when retry is accepted.
            Returns error for all other states (e.g. `queued`/`running`/`done`).
        """
        loop_error = _ensure_job_loop_consistency()
        if loop_error:
            return json.dumps(loop_error)

        _prune_jobs()
        old_job = JOB_STORE.get(job_id)
        if not old_job:
            return json.dumps({
                "status": "error",
                "error": f"Job not found: {job_id}",
            })

        # Only retry failed/canceled jobs.
        old_state = old_job.get("state", "")
        if old_state not in {"error", "canceled"}:
            return json.dumps({
                "status": "error",
                "error": f"Cannot retry job in state '{old_state}'. Only failed/canceled jobs can be retried.",
            })

        # Get original request parameters
        req = old_job.get("request", {})

        # Touch paper status for consistency checks (if workspace exists).
        paper_dir = req.get("paper_dir", "")
        if paper_dir:
            ws = PaperWorkspace(paper_dir)
            if ws.is_workspace():
                ws.load_paper_status()
                # For retry, we skip completed stages
                # (skip_completed=True is default in _new_job)

        # Create new job with same parameters
        new_job = _new_job(
            paper_dir=req.get("paper_dir", ""),
            pdf_path=req.get("pdf_path", ""),
            steps=req.get("steps", ALL_STEPS),
            skip_completed=True,  # Always skip completed for retry
            translate_concurrency=req.get("translate_concurrency", 4),
            dry_run_rename=req.get("dry_run_rename", False),
        )

        # Start the new job
        task = asyncio.create_task(_job_runner(new_job["job_id"]))
        JOB_TASKS[new_job["job_id"]] = task

        return json.dumps({
            "status": "ok",
            "original_job_id": job_id,
            "original_state": old_state,
            "new_job_id": new_job["job_id"],
            "state": new_job["state"],
            "message": f"Retry job created. Original job was in state '{old_state}'.",
        })
