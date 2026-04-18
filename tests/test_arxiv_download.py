from __future__ import annotations

import json
from pathlib import Path

import pytest

from academic_tools.tools import arxiv as arxiv_tools


class _CapturingMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


def _registered_download_tool():
    mcp = _CapturingMCP()
    arxiv_tools.register(mcp)
    return mcp.tools["download_paper"]


class _FakeArxivClient:
    def __init__(self, paper: object) -> None:
        self.paper = paper

    def results(self, search: object):
        return iter([self.paper])


class _PaperThatFailsBeforeWriting:
    title = "Synthetic arXiv paper"
    pdf_url = "https://arxiv.org/pdf/2401.00001"


class _PaperThatLeavesPartialFinalFile:
    title = "Synthetic arXiv paper"
    pdf_url = "https://arxiv.org/pdf/2401.00003"


@pytest.mark.asyncio
async def test_download_paper_returns_structured_error_when_arxiv_client_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        arxiv_tools.arxiv,
        "Client",
        lambda: _FakeArxivClient(_PaperThatFailsBeforeWriting()),
    )
    monkeypatch.setattr(
        arxiv_tools,
        "_download_pdf_with_retries",
        lambda pdf_url, pdf_path: (_ for _ in ()).throw(RuntimeError("connection reset by peer")),
    )

    download_paper = _registered_download_tool()
    raw = await download_paper("2401.00001", str(tmp_path))
    payload = json.loads(raw)

    assert payload["status"] == "error"
    assert payload["paper_id"] == "2401.00001"
    assert "connection reset by peer" in payload["error"]
    assert not (tmp_path / "2401.00001.pdf").exists()


@pytest.mark.asyncio
async def test_download_paper_does_not_accept_empty_existing_pdf_as_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper_id = "2401.00002"
    (tmp_path / f"{paper_id}.pdf").write_bytes(b"")
    monkeypatch.setattr(
        arxiv_tools.arxiv,
        "Client",
        lambda: _FakeArxivClient(_PaperThatFailsBeforeWriting()),
    )
    monkeypatch.setattr(
        arxiv_tools,
        "_download_pdf_with_retries",
        lambda pdf_url, pdf_path: Path(pdf_path).write_bytes(b"%PDF-1.4\ncomplete"),
    )

    download_paper = _registered_download_tool()
    raw = await download_paper(paper_id, str(tmp_path))
    payload = json.loads(raw)

    assert payload["status"] == "success"
    assert (tmp_path / f"{paper_id}.pdf").read_bytes() == b"%PDF-1.4\ncomplete"


@pytest.mark.asyncio
async def test_download_paper_removes_or_avoids_final_pdf_after_interrupted_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper_id = "2401.00003"
    monkeypatch.setattr(
        arxiv_tools.arxiv,
        "Client",
        lambda: _FakeArxivClient(_PaperThatLeavesPartialFinalFile()),
    )
    def fail_with_partial_final(pdf_url: str, pdf_path: Path) -> None:
        pdf_path.write_bytes(b"%PDF-1.4\npartial")
        raise RuntimeError("connection reset by peer")

    monkeypatch.setattr(arxiv_tools, "_download_pdf_with_retries", fail_with_partial_final)

    download_paper = _registered_download_tool()
    raw = await download_paper(paper_id, str(tmp_path))
    payload = json.loads(raw)

    assert payload["status"] == "error"
    assert not (tmp_path / f"{paper_id}.pdf").exists()
