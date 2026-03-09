# Glossary

> **职责**：统一术语和变量定义，防止"同名不同义"或"口头定义漂移"。
> **最后更新**：2026-03-09（本轮更新）

---

## 核心术语

### `paper_dir`
- **定义**：论文工作目录，如 `~/papers/Smith-NeurIPS-2024-LLM-Voting/`
- **备注**：由 `PaperWorkspace` 统一管理，包含所有处理产物

### `full.md`
- **定义**：MinerU OCR 输出的完整 Markdown 文本
- **备注**：论文处理流程的第一个产物，后续所有步骤基于此文件

### `stem`
- **定义**：论文目录的名称，如 `Smith-NeurIPS-2024-LLM-Voting`
- **备注**：用于生成结构化输出的文件名，如 `*_structure.json`, `*_translated.md`

### `metadata.json`
- **定义**：统一元数据文件，包含 LLM 提取和 API 富化的完整信息
- **备注**：Pydantic `PaperMetadata` 模型序列化

### `PaperWorkspace`
- **定义**：管理论文目录文件布局的数据模型
- **备注**：提供 `.ocr_markdown`, `.metadata_path`, `.structure_path` 等属性；新增 `update_stage()`、`load_paper_status()`、`save_paper_status()` 方法用于维护 `paper_status.json`

### `paper_status.json`
- **定义**：论文级状态文件，存放在每个 `paper_dir/` 下
- **内容**：6 个 stage（ocr/metadata/structure/translate/summary/rename）各自的 `status`、`started_at`、`finished_at`、`artifact`、`error`；以及 `overall_status`、`pdf_source`
- **更新时机**：stage 开始写 `running`，函数返回后立即写实际状态（非推断）
- **rename 安全**：文件随目录走，rename 后自动存在于新目录

### `processing_queue.json`
- **定义**：全局队列状态文件，存放在 papers 根目录下
- **内容**：所有论文的 `pdf_path`、`workspace_dir`、`status`、`current_stage`、`progress`、`job_id`；及 `summary` 统计（total/done/running/pending/error）
- **路径存储**：pdf_path 和 workspace_dir 存相对于 `base_dir` 的相对路径
- **并发防护**：`asyncio.Lock` + 原子替换写入

### `ProcessingQueue`
- **定义**：管理 `processing_queue.json` 的 Python 类，位于 `models/queue.py`
- **主要方法**：`load()`、`save()`（原子写）、`upsert_paper()`、`update_locked()`（带锁的快捷更新）、`refresh_summary()`

### `overall_status`
- **定义**：论文全部 stage 的汇总状态
- **取値规则**：任意 stage == `error` → `error`；任意 stage == `running` → `running`；所有 stage 在 `{done, skipped}` → `done`；其他 → `pending`
- **自动推导**：`PaperWorkspace.overall_status_from_stages()` 计算，无需手动维护

### `PaperMetadata`
- **定义**：论文元数据的 Pydantic 数据模型
- **备注**：分两阶段：Phase 1 (LLM 提取) + Phase 2 (API 富化)

### `_run()`
- **定义**：每个工具模块的模块级入口函数
- **备注**：供 pipeline 直接 import，复用逻辑

### `register(mcp)`
- **定义**：每个工具模块暴露给 server.py 的注册函数
- **备注**：使用 `@mcp.tool()` 装饰器定义 MCP 工具

### `OCR`
- **定义**：Optical Character Recognition，这里指 MinerU API 对 PDF 进行高质量 Markdown 转换
- **备注**：不是传统 OCR，而是 PDF 版面分析与结构化输出

### `Phase 1 / Phase 2`
- **定义**：metadata 提取的两个阶段
- **Phase 1**：LLM 从 full.md 提取 title/authors/abstract/doi/year/github
- **Phase 2**：Crossref/OpenAlex API 富化 journal/citation_count/references

### `DOI content negotiation`
- **定义**：向 `https://doi.org/<doi>` 发特定 Accept 头获取 APA/BibTeX 引用
- **备注**：标准学术 API 规范

### `MCP`
- **定义**：Model Context Protocol，Claude/Cursor 调用外部工具的协议
- **备注**：参见 https://modelcontextprotocol.io

### `FastMCP`
- **定义**：MCP 的 Python 高层封装库
- **备注**：本项目使用的 MCP 框架

### `Better BibTeX`
- **定义**：Zotero 插件，提供 citekey 管理和批注导出
- **备注**：用于 `zotero_get_annotations`

## 变量定义

### `paper_status`
- **含义**：论文各 stage 处理状态（字典类型）
- **取値**：`pending` / `running` / `done` / `skipped` / `error`（每个 stage 独立）
- **来源**：`PaperWorkspace.load_paper_status()["stages"]`，持久化在 `paper_status.json`
- **注意**：字符串 `success` / `already_exists` / `unchanged` / `dry_run` 均被规范化为 `done`

### `enrichment_status`
- **含义**：元数据富化状态
- **取值**：`success`, `degraded`, `no_data`, `failed`
- **注意事项**：反映 Crossref/OpenAlex API 调用是否成功

### `skip_completed`
- **含义**：是否跳过已完成的步骤
- **取值**：`True`（默认）- 跳过；`False` - 强制重跑
- **注意事项**：用于 `process_paper` 断点续跑

### `translate_concurrency`
- **含义**：翻译步骤的并发 LLM 调用数
- **取值**：默认 4
- **注意事项**：过高可能触发 API rate limit

### `METADATA_TEXT_LIMIT`
- **含义**：发送给 LLM 提取元数据的字符数上限
- **取值**：默认 6000
- **注意事项**：控制 LLM 上下文长度
### `MAX_CONCURRENT_JOBS`
- **含义**：同时允许运行的最大后台 job 数
- **取値**：默认 3，可通过 `.env` 设置 `MAX_CONCURRENT_JOBS=N`
- **实现**：`asyncio.Semaphore`，超出上限的 job 保持 `queued` 状态排队等待