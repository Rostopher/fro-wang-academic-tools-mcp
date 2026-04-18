# Project Status

> **职责**：记录"项目当前进展到哪了"，包括已完成模块、进行中事项和待办优先级。是状态类信息的唯一入口。
> **最后更新**：2026-04-18（PyPI Trusted Publishing 发布流程）

---

## 1) 项目范围（Scope）

- **目标**：提供统一的学术论文处理 MCP Server，支持 OCR、元数据提取、结构分析、翻译、摘要、重命名，以及 arXiv 搜索和 Zotero 集成
- **当前版本**：v0.1.4
- **主线仓库/目录**：`src/academic_tools/`

## 2) 已完成（Done）

- [x] **MCP Server 框架**：基于 FastMCP 的 stdio 协议服务
- [x] **论文处理工具（8 个）**：
  - `ocr_paper` — MinerU API OCR
  - `extract_metadata` — LLM + Crossref + OpenAlex 元数据提取
  - `extract_sections` — 章节结构提取
  - `translate_paper` — 并发翻译
  - `generate_summary` — 摘要报告生成
  - `rename_paper_folder` — 目录标准化重命名
  - `process_paper` — 全流程编排
  - 异步任务工具（start_process_paper_job, get_process_paper_job, cancel_process_paper_job）
- [x] **arXiv 工具（2 个）**：搜索与下载
- [x] **Zotero 只读工具（9 个）**：搜索、元数据、全文、collections、tags、recent、批注、笔记等；不暴露写入工具
- [x] **幂等性机制**：已完成步骤不重复执行
- [x] **异步 OCR**：支持长时间 OCR 任务的异步处理
- [x] **论文级状态持久化（`paper_status.json`）**：每个 stage 开始/完成/失败/跳过时直接写盘，`PaperWorkspace.update_stage()` 实现，无需推断
- [x] **全局队列状态（`processing_queue.json`）**：`ProcessingQueue` 模型管理，记录所有论文的鸟瞰进度，支持 summary 统计
- [x] **并发写保护**：`asyncio.Lock`（per 队列文件）+ 原子替换写入（`.tmp → .json`），同进程多 job 并发安全
- [x] **后台 job 并发上限（`MAX_CONCURRENT_JOBS`）**：`asyncio.Semaphore` 控制最大并行 job 数，默认 3，可通过 `.env` 配置
- [x] **arXiv/Zotero 问题复现测试**：新增 `tests/test_arxiv_download.py`、`tests/test_zotero_client.py`、`tests/test_zotero_local_diagnostics.py`、`tests/test_zotero_tools_exposed.py`；相关复现测试均已转为正式通过
- [x] **arXiv 下载容错**：`download_paper` 改为流式下载到 `.part` 临时文件，校验 PDF 后再替换最终文件；空/残缺 PDF 不再被当作完成
- [x] **Zotero 工具统一 JSON 返回**：9 个 agent-facing Zotero 只读工具成功/失败均返回 JSON 字符串，连接失败进入 `{"status":"error"}` 包
- [x] **本地 Zotero 诊断**：Better BibTeX 客户端新增本地连接诊断，区分未连接、端口异常响应，并在错误信息中提示打开 Zotero、安装 Better BibTeX、启用本地 HTTP/API 服务
- [x] **Zotero live 测试入口**：新增默认跳过的 `tests/integration/test_zotero_live_tools.py`；`ZOTERO_LIVE_TEST=1` 可跑真实只读测试
- [x] **Zotero live 只读验证**：本机真实 Zotero 下 recent/collections/tags/search/item metadata/fulltext/annotations/notes/collection items 只读路径通过
- [x] **PyPI Trusted Publishing 发布流程**：新增 GitHub Release 触发的 `.github/workflows/publish.yml`，构建 sdist/wheel 后通过 PyPI OIDC Trusted Publisher 发布，不再依赖长期 `PYPI_TOKEN`

## 3) 进行中（In Progress）

_（当前无进行中事项）_

## 4) 待办 Backlog（按优先级）

1. **P0**：新增 Phase 2 编排工具：`batch_process_papers`（目录级批量入口）、`get_batch_status`（全局队列鸟瞰）、`list_jobs`（内存 job 列表）、`retry_job`（失败重试）
2. **P2**：为真实 arXiv 外部服务补充可选集成测试或诊断脚本
3. **P3**：优化 LLM 调用（添加重试/退避机制）

## 5) 关键口径提醒

- **幂等性**：已完成的步骤不重复执行（通过检查文件存在性）
- **文件布局**：`PaperWorkspace` 统一管理，所有工具通过它读写
- **返回格式**：所有步骤返回统一 JSON 包 `{"status": "success"/"error"/"already_exists"/"dry_run", ...}`
