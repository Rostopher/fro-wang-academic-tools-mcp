# Runbook

> **职责**：说明"怎么运行、产物在哪、出错如何排查"。是执行类信息的唯一入口。
> **最后更新**：2026-03-09（本轮更新）

---

## 1) 环境准备

- **Python 版本**：≥ 3.11
- **依赖安装**：
  ```bash
  F:/global_venv/.venv/Scripts/python.exe -m pip install -e \
    "f:/codeF/llm_projects/academic_tools_for_agents/mcps/fro-wang-academic-tools-mcp"
  ```
- **关键环境变量**（`.env`）：
  - `LLM_API_KEY` — LLM API Key
  - `LLM_BASE_URL` — OpenAI-compatible endpoint（默认 `https://api.deepseek.com`）
  - `LLM_MODEL` — 模型名（默认 `deepseek-chat`）
  - `ZOTERO_LIBRARY_ID` — Zotero 用户/群组 ID
  - `ZOTERO_API_KEY` — Zotero Web API Key
  - `ZOTERO_LOCAL` — 本地模式（`true/false`）
  - `MINERU_TOKENS_FILE` — MinerU token 文件路径
  - `ARXIV_STORAGE_PATH` — arXiv 下载目录（默认 `papers`）
  - `MAX_CONCURRENT_JOBS` — 后台并行 job 上限（默认 `3`）

## 2) 运行命令

```bash
# 方式 1：命令行脚本（安装后可用）
fro-wang-academic-tools-mcp

# 方式 2：模块调用
python -m academic_tools
```

服务以 **stdio 传输**启动，监听 stdin/stdout MCP JSON-RPC 消息。

## 3) 输出位置

```
papers/                       # 根目录（ARXIV_STORAGE_PATH）
├── processing_queue.json        # 全局队列状态（所有论文的鸟瞰图）
├── 2502.08691.pdf               # 下载的 PDF
└── paper_dir/                    # 论文工作目录
    ├── full.md                   # OCR 输出
    ├── images/                   # 提取的图片
    ├── metadata.json             # 元数据
    ├── <stem>_structure.json    # 结构化章节
    ├── <stem>_translated.md     # 翻译版本
    ├── summary_report.md         # 摘要报告
    ├── paper_status.json         # 论文级处理状态（每 stage 实时写盘）
    └── .academic_workspace       # 安全哨兵标记
```

## 4) 常见问题

### 问题 1：`MINERU_TOKENS_FILE not set`
- **现象**：OCR 步骤报错
- **排查**：检查 `.env` 是否配置 `MINERU_TOKENS_FILE`
- **修复**：设 `MINERU_TOKENS_FILE` 指向实际文件

### 问题 2：OCR 超时
- **现象**：MinerU 免费额度轮询慢，长时间无返回
- **排查**：检查 `_poll_result()` 轮询逻辑
- **修复**：增加重试间隔，或使用付费 token

### 问题 3：LLM 返回非 JSON
- **现象**：metadata 提取失败
- **排查**：检查 prompt 和模型输出
- **修复**：`shared/prompt_utils.py#extract_json_from_response` 有 5 层兜底

### 问题 4：Zotero `Missing credentials`
- **现象**：Zotero 工具无法使用
- **排查**：检查 `ZOTERO_LIBRARY_ID + ZOTERO_API_KEY`
- **修复**：
  - 远程模式：配置正确的 Library ID 和 API Key
  - 本地模式：设 `ZOTERO_LOCAL=true`，确保 Zotero 桌面端正在运行

### 问题 5：元数据标题提取错误
- **现象**：`metadata.json` 的 `title` 是会议名而非论文标题
- **排查**：检查 `_title_similarity()` 交叉验证逻辑
- **修复**：手动编辑 `metadata.json`，重跑 `rename_paper_folder`

### 问题 6：目录重命名失败
- **现象**：`rename_paper_folder` 返回 `unchanged`
- **排查**：检查 `metadata.json` 是否有 `title`, `authors`, `publication_year`
- **修复**：确保元数据字段完整

### 问题 7：翻译步骤报错
- **现象**：`*_translated.md` 中有 `[翻译失败: ...]` 标记
- **排查**：检查 LLM API Key 有效性和账户余额
- **修复**：降低 `translate_concurrency`（默认 4）

### 问题 8：查看当前批处理进度
- **需求**：想知道哪些论文还在处理中
- **方式 1**：直接读集根目录下的 `processing_queue.json`，查看 `summary` 和 `papers` 数组
- **方式 2**：对具体论文读取 `paper_dir/paper_status.json`，查看每个 stage 的详细状态、时间戳和错误信息

---

## 5) 故障排查入口

详细故障排查手册见主 README 文档 `docs/README.md` 第 9 节。
