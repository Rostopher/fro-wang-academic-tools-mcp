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

from ..models.paper import PaperWorkspace
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

    def emit(step: str, phase: str, message: str) -> None:
        if job_id:
            _job_event(job_id, step, phase, message)
        else:
            _emit_progress(step, phase, message)

    async def run_step(name: str, coro) -> bool:
        if name not in steps:
            step_results[name] = "skipped"
            step_details[name] = {
                "status": "skipped",
                "started_at": None,
                "finished_at": _now_iso(),
                "message": f"Step `{name}` skipped (not in requested steps).",
                "joke": _step_joke(name),
            }
            emit(name, "skip", f"Step `{name}` skipped.")
            return True

        started_at = _now_iso()
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
            emit(name, "end", f"{message} {joke}")
            return status in ("success", "already_exists", "unchanged", "dry_run")
        except asyncio.CancelledError:
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
            emit(name, "error", f"`{name}` crashed: {exc}")
            return False

    # --- Step 1: OCR ---
    if "ocr" in steps:
        if skip_completed and (ws.dir / "full.md").exists():
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
            emit("rename", "end", f"{rename_message} {rename_joke}")
            if rename_status == "success":
                current_dir = rename_result.get("new_path", current_dir)
        except Exception as exc:
            step_results["rename"] = f"error: {exc}"
            step_details["rename"] = {
                "status": "error",
                "started_at": rename_started_at,
                "finished_at": _now_iso(),
                "message": f"`rename` crashed with exception: {exc}",
                "joke": "Even good pipelines trip sometimes.",
            }
            emit("rename", "error", f"`rename` crashed: {exc}")
    else:
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
        if result.get("status") in ("complete", "partial_failed"):
            job["state"] = "done"
            job["progress"] = 1.0
            job["last_message"] = f"Job finished with status `{result.get('status')}`."
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
