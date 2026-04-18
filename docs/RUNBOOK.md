# Runbook

> **职责**：说明"怎么运行、产物在哪、出错如何排查"。是执行类信息的唯一入口。
> **最后更新**：2026-04-18（PyPI 发布节奏与流程）

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
  - `ZOTERO_LOCAL` — 本地只读 Zotero 模式（设为 `true`）
  - `MINERU_TOKENS_FILE` — MinerU token 文件路径
  - `ARXIV_STORAGE_PATH` — arXiv 下载目录（默认 `papers`，建议填绝对路径）
  - `MAX_CONCURRENT_JOBS` — 后台并行 job 上限（默认 `3`）

## 2) 运行命令

```bash
# 方式 1：命令行脚本（安装后可用）
fro-wang-academic-tools-mcp

# 方式 2：模块调用
python -m academic_tools
```

服务以 **stdio 传输**启动，监听 stdin/stdout MCP JSON-RPC 消息。

## 2.1) 测试与复现入口

```bash
uv run pytest
```

当前 arXiv/Zotero 问题先用不联网 pytest 固化复现：

- `tests/test_arxiv_download.py`：覆盖 arXiv 下载异常、空 PDF 被误判完成、下载中断留下残缺最终文件等场景
- `tests/test_zotero_client.py`：覆盖 Zotero 远程凭据缺失、本地模式默认库 ID，以及工具层连接错误/返回格式问题
- `tests/test_zotero_local_diagnostics.py`：覆盖本地 Zotero 使用前置条件诊断，包括 Zotero 桌面端未打开、Better BibTeX/本地 HTTP 服务未启用、`127.0.0.1:23119` 被其他进程占用
- `tests/test_zotero_tools_exposed.py`：覆盖 9 个暴露给 agent 的只读 Zotero MCP 工具是否完整注册，并在 fake Zotero 正常返回时逐个调用成功
- `tests/integration/test_zotero_live_tools.py`：真实 Zotero live 测试；默认跳过，只有显式设置环境变量才访问本地 Zotero

此前的 arXiv 下载容错和 Zotero 工具层问题已转为正式通过测试；当前默认测试集中不保留 `xfail`。

运行真实 Zotero 只读 live 测试：

```bash
ZOTERO_LIVE_TEST=1 uv run pytest tests/integration/test_zotero_live_tools.py -m integration -q
```

运行指定 item 的 live 读取测试：

```bash
ZOTERO_LIVE_TEST=1 \
ZOTERO_LIVE_ITEM_KEY=<真实 Zotero item key> \
uv run pytest tests/integration/test_zotero_live_tools.py::test_live_zotero_item_read_tools -q
```

当前本地 Zotero live 结论：

- 只读工具链已验证通过：recent、collections、tags、search、item metadata、fulltext、annotations、notes、collection items
- 本项目不暴露 Zotero 写入工具；Zotero Desktop 本地 HTTP API 在当前项目中按只读能力使用
- Better BibTeX 相关能力需额外确认；若诊断返回 `better_bibtex_unavailable`，表示 Zotero local API 在运行，但 Better BibTeX endpoint 不存在或未启用

## 2.2) PyPI 发布节奏

日常代码、测试和文档改动可以先合并到 `main`，不必每次都发布 PyPI。优先攒成一个可说明的 release 批次，避免无意义版本噪音。

适合发布 PyPI 的情况：

- 新增或改变用户可见 MCP 工具行为
- 修复影响安装、运行、打包或外部服务调用的问题
- 更新依赖、Python 兼容性、配置项或命令入口
- 累计多个小修复后，已经能写出清晰 release notes

不必立即发布的情况：

- 纯文档、注释、内部整理或测试补充
- 不影响已安装用户的局部重构
- 刚合并但还需要继续观察的一小步实验性改动

发布前先确认这次变更值得占用一个新的 PyPI 版本号。PyPI 文件名不可复用；一旦某个版本发布，即使删除文件也不能用相同版本重新上传。

## 2.3) PyPI 发布流程

发布由 GitHub Release 触发：

1. 汇总自上次 release 以来的变更，确认需要发布。
2. 将 `pyproject.toml` 版本号改成尚未发布到 PyPI 的新版本。
3. 本地运行基础验证，例如 `python -m build`，必要时再跑相关 pytest。
4. 将发布改动合并到 `main` 并推送远端。
5. 在 GitHub 仓库创建并发布匹配版本的 tag/release，例如 `v0.1.5`。
6. GitHub Actions 会运行 `.github/workflows/publish.yml`，先构建 sdist/wheel，再通过 PyPI Trusted Publishing 上传。
7. 发布后检查 GitHub Actions run、PyPI 项目页和 `Download files` 中的 wheel/sdist。

PyPI 项目的 Trusted Publisher 配置需与 workflow 精确匹配：

- Owner: `Rostopher`
- Repository name: `fro-wang-academic-tools-mcp`
- Workflow name: `publish.yml`
- Environment name: `pypi`

发布 job 依赖 GitHub environment `pypi` 和 OIDC 权限 `id-token: write`；不要在仓库 secrets 中配置长期 `PYPI_TOKEN`。

若发布 workflow 报 `File already exists`，说明该版本的某个 distribution 已经上传到 PyPI。不要重跑同一个版本；改用下一个版本号重新发布。

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

## 3.1) `download_paper` 路径规范

- `download_dir` **优先传绝对路径**（跨客户端/跨工作目录最稳定）
- `download_dir="cwd"` 或 `"auto"` 会固定到 `<cwd>/papers`
- 不传 `download_dir` 时使用 `ARXIV_STORAGE_PATH`
- 若传相对路径，会按 MCP 服务进程的当前工作目录解析
- 下载会先写入 `.part` 临时文件，校验为 PDF 后再替换最终文件；空文件/残缺文件不会被当作 `already_exists`

示例：

```json
{"paper_id":"1706.03762","download_dir":"F:/codeF/llm_projects/academic_tools_for_agents/mcps/fro-wang-academic-tools-mcp/papers"}
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

### 问题 4：Zotero 本地只读工具无法使用
- **现象**：Zotero 工具无法读取本地文库
- **排查**：检查 `ZOTERO_LOCAL=true`，Zotero 桌面端是否正在运行，本地 HTTP/API 服务是否启用
- **修复**：打开 Zotero Desktop，并确认本地 HTTP/API 访问已开启

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
