# fro-wang-academic-tools-mcp

`fro-wang-academic-tools-mcp` is an MCP server for academic paper workflows, built on FastMCP.
It combines OCR, metadata extraction/enrichment, section parsing, translation, summary generation, arXiv tools, and Zotero integration.

Detailed system design is documented in `docs/README_SYSTEM.md`.

## Motivation

This project is dedicated to managing academic papers locally to empower AI Agents. While AI Agents excel at local tasks, they struggle with the dominant format of academic literature: PDFs. When you are conducting literature reviews, reading, or searching for papers, most of your local library consists of PDF files.

Local coding agents prefer plain text. They rely on tools like `grep` or semantic search to navigate local files. These tools cannot natively search inside PDFs, making it difficult for agents to assist with literature management effectively.

Having frequently encountered this bottleneck, I built `fro-wang-academic-tools-mcp` to bridge the gap. These tools extract the core workflow from my website, [frowang.com](https://frowang.com), converting PDFs into agent-friendly formats (like Markdown) and enriching them with metadata.

## Features

- End-to-end paper pipeline via `process_paper`
- OCR with MinerU (`ocr_paper`)
- Metadata extraction + enrichment (`extract_metadata`)
- Section structure extraction (`extract_sections`)
- Markdown translation (`translate_paper`)
- Summary report generation (`generate_summary`)
- Folder rename by metadata convention (`rename_paper_folder`)
- arXiv search/download tools
- Zotero library tools (search, notes, collections, attachments, annotations)

## Tool Groups

This server currently registers 22 MCP tools:

- Paper processing: `ocr_paper`, `extract_metadata`, `extract_sections`, `translate_paper`, `generate_summary`, `rename_paper_folder`
- Pipeline: `process_paper`, `start_process_paper_job`, `get_process_paper_job`, `cancel_process_paper_job`
- arXiv: `search_papers`, `download_paper`
- Zotero: `zotero_search_items`, `zotero_get_item_metadata`, `zotero_get_item_fulltext`, `zotero_get_collections`, `zotero_get_collection_items`, `zotero_get_tags`, `zotero_get_recent`, `zotero_get_annotations`, `zotero_get_notes`, `zotero_create_note`

## Requirements

- Python `>=3.11` (project pin: `3.13.7`, see `.python-version`)
- MinerU token (for OCR)
- OpenAI-compatible LLM API key (default endpoint is DeepSeek)
- Zotero credentials (for remote mode) or local Zotero desktop mode

> **Configuration Guides:**
> - [How to configure DeepSeek API](docs/deepseek_config_guide.md)
> - [How to configure Zotero (Local & Remote)](docs/zotero_config_guide.md)
> - [How to configure MinerU OCR](docs/mineru_config_guide.md)
> - [How to configure MCP in AI Agents (Cursor, Claude, Copilot, Cline)](docs/mcp_client_config_guide.md)

## Quick Start (uv)

```powershell
cd mcps/fro-wang-academic-tools-mcp
uv python pin 3.13.7
uv venv --python 3.13.7
uv sync --extra dev
```

Create `.env` from template:

```powershell
Copy-Item .env.example .env
```

Then edit `.env` at least for:

- `LLM_API_KEY`
- `MINERU_TOKENS_FILE`
- `ZOTERO_LIBRARY_ID` and `ZOTERO_API_KEY` (if using Zotero remote mode)

## Run

```powershell
uv run fro-wang-academic-tools-mcp
```

or

```powershell
uv run python -m academic_tools
```

## Long-Running Jobs (Recommended for MCP Clients)

Many MCP clients apply a ~60s timeout per tool call. For full pipeline runs, prefer async jobs:

1. Start job with `start_process_paper_job` (returns immediately with `job_id`)
2. Poll with `get_process_paper_job(job_id)`
3. Optional cancel via `cancel_process_paper_job(job_id)`

This avoids client timeout while OCR/LLM stages continue in the background.

## Development

Run tests and lint:

```powershell
uv run pytest
uv run ruff check src
```

Check Python version used by the project env:

```powershell
uv run python -V
uv run python -c "import sys; print(sys.executable)"
```

## Common Issues

- `uv init` says project already initialized:
  - Expected behavior. This repo already has `pyproject.toml`.
- `uv sync --extra dev` warns about `VIRTUAL_ENV` mismatch:
  - You likely activated another project's venv. Deactivate it and run again in this folder.
- `Readme file does not exist: README.md` during build:
  - This file is required by `[project].readme` in `pyproject.toml`. Keep `README.md` in project root.

## Project Entry Points

- CLI script: `fro-wang-academic-tools-mcp` (defined in `pyproject.toml`)
- Module entry: `python -m academic_tools`
- Server wiring: `src/academic_tools/server.py`
