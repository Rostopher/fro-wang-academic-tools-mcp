"""OCR tool: ocr_paper — calls MinerU API to OCR a PDF into full.md.

Core MinerU API flow:
  1. POST /file-urls/batch  → get upload URL + batch_id
  2. PUT  <upload_url>      → upload PDF bytes
  3. GET  /extract-results/batch/{batch_id}  (poll) → full_zip_url
  4. GET  <full_zip_url>    → download ZIP
  5. Extract ZIP, keep only full.md + images/
"""

from __future__ import annotations

import hashlib
import json
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

import fitz  # PyMuPDF
import requests
import urllib3
from mcp.server.fastmcp import FastMCP

from ..config import settings

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

def _load_tokens() -> List[str]:
    """Load MinerU API tokens from MINERU_API_KEY_1 … MINERU_API_KEY_5 env vars."""
    tokens = []
    for i in range(1, 6):
        key = getattr(settings, f"MINERU_API_KEY_{i}", None)
        if key:
            tokens.append(key)
    if not tokens:
        raise RuntimeError(
            "No MinerU API keys configured. "
            "Set MINERU_API_KEY_1 … MINERU_API_KEY_5 in .env (at least one required)."
        )
    return tokens


def _get_token() -> str:
    """Return the first available token (simple round-robin not needed for MCP)."""
    return _load_tokens()[0]


# ---------------------------------------------------------------------------
# MinerU API helpers
# ---------------------------------------------------------------------------

def _make_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _make_session() -> requests.Session:
    """Build a requests session for MinerU calls."""
    session = requests.Session()
    session.verify = False
    # Avoid inheriting HTTP(S)_PROXY from system/VPN by default.
    session.trust_env = settings.MINERU_TRUST_ENV
    return session


def _upload_pdf(pdf_path: Path, token: str, api_base: str) -> str:
    """Upload PDF to MinerU and return batch_id."""
    session = _make_session()

    payload = {
        "files": [{"name": pdf_path.name, "data_id": f"file_{int(time.time())}"}],
        "model_version": "vlm",
    }
    resp = session.post(
        f"{api_base}/file-urls/batch",
        headers=_make_headers(token),
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("code") != 0:
        raise RuntimeError(f"Failed to get upload URL: {result.get('msg')}")

    batch_id: str = result["data"]["batch_id"]
    upload_url: str = result["data"]["file_urls"][0]

    with pdf_path.open("rb") as f:
        up = session.put(upload_url, data=f, verify=False, timeout=300)
    if up.status_code != 200:
        raise RuntimeError(f"PDF upload failed: HTTP {up.status_code}")

    return batch_id


def _poll_result(batch_id: str, token: str, api_base: str, timeout: int = 3600) -> str:
    """Poll until processing completes, return the full_zip_url."""
    session = _make_session()
    start = time.time()

    while True:
        if time.time() - start > timeout:
            raise TimeoutError(f"MinerU processing timed out after {timeout}s")

        resp = session.get(
            f"{api_base}/extract-results/batch/{batch_id}",
            headers=_make_headers(token),
            verify=False,
            timeout=60,
        )
        if resp.status_code != 200:
            time.sleep(10)
            continue

        data = resp.json()
        if data.get("code") != 0:
            time.sleep(10)
            continue

        extract = (
            data.get("data", {}).get("extract_result")
            or data.get("data", {}).get("extract_results")
        )
        if not extract:
            time.sleep(10)
            continue

        result = extract[0]
        state = result.get("state")
        if state == "failed":
            raise RuntimeError(f"MinerU failed: {result.get('err_msg', 'unknown error')}")
        if state == "done":
            return result["full_zip_url"]

        time.sleep(10)


def _download_and_extract(zip_url: str, output_dir: Path) -> Path:
    """Download the result ZIP and extract it, keeping only full.md + images/."""
    session = _make_session()

    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "_mineru_result.zip"

    resp = session.get(zip_url, stream=True, verify=False, timeout=300)
    resp.raise_for_status()
    with zip_path.open("wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(output_dir)

    zip_path.unlink(missing_ok=True)

    return output_dir / "full.md"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

async def _run(pdf_path: str, output_dir: Optional[str] = None) -> str:
    """Module-level runner (also called by pipeline.py)."""
    pdf = Path(pdf_path).expanduser().resolve()
    if pdf.exists() and pdf.is_dir():
        return json.dumps({
            "status": "error",
            "error": "`pdf_path` points to a directory. Please pass an actual .pdf file path.",
            "hint": "Example: `pdf_path='F:/.../papers/arxiv-2502.08691.pdf'`",
        })
    if not pdf.exists():
        return json.dumps({"status": "error", "error": f"PDF not found: {pdf}"})
    if pdf.suffix.lower() != ".pdf":
        return json.dumps({
            "status": "error",
            "error": "`pdf_path` must end with `.pdf`.",
            "hint": "Do not pass a folder path to `pdf_path`.",
        })

    if output_dir:
        out = Path(output_dir).expanduser().resolve()
    else:
        out = pdf.parent / pdf.stem
    out.mkdir(parents=True, exist_ok=True)

    # Mark directory as a valid paper workspace immediately so subsequent tools
    # and the destructive cleanup step know it is safe to operate here.
    from ..models.paper import PaperWorkspace
    PaperWorkspace(out).mark_as_workspace()

    full_md = out / "full.md"
    if full_md.exists() and full_md.stat().st_size > 100:
        # Ensure sentinel exists even for directories pre-created before this guard.
        PaperWorkspace(out).mark_as_workspace()
        return json.dumps({
            "status": "already_exists",
            "full_md": str(full_md),
            "output_dir": str(out),
        })

    try:
        doc = fitz.open(str(pdf))
        page_count = doc.page_count
        doc.close()
    except Exception as exc:
        return json.dumps({"status": "error", "error": f"Cannot read PDF: {exc}"})

    try:
        token = _get_token()
        api_base = settings.MINERU_API_BASE

        batch_id = _upload_pdf(pdf, token, api_base)
        zip_url = _poll_result(batch_id, token, api_base)
        result_md = _download_and_extract(zip_url, out)

        return json.dumps({
            "status": "success",
            "full_md": str(result_md),
            "output_dir": str(out),
            "page_count": page_count,
        })
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def ocr_paper(
        pdf_path: str,
        output_dir: Optional[str] = None,
    ) -> str:
        """
        OCR a PDF using MinerU API and save the result as full.md.

        The output directory will contain:
        - full.md   — full Markdown text of the paper
        - images/   — embedded images extracted from the PDF

        Args:
            pdf_path: Absolute path to the PDF file.
            output_dir: Directory to save results. Defaults to the same
                        directory as the PDF (creates a subfolder named
                        after the PDF stem).

        Returns:
            JSON with status and path to full.md.
        """
        return await _run(pdf_path, output_dir)
