# Decisions Log

> **职责**：沉淀"为什么这么做"的关键决策，避免重复讨论。所有方法、口径、架构决策都在这里留痕。

---

## 记录规则

- 只追加，不删除
- 若新决策推翻旧决策，写：`supersedes DEC-xxx`
- 每条必须包含：背景 / 结论 / 理由 / 影响范围

## 模板

```markdown
### DEC-xxx: 决策标题 (YYYY-MM-DD)
**背景**：
**结论**：
**理由**：
**影响范围**：
```

---

## 决策记录

### DEC-001: 使用 FastMCP 构建 MCP Server (2025-01)
**背景**：需要将学术工具封装为 MCP 协议供 Claude/Cursor 调用
**结论**：采用 `fastmcp` 库，基于 stdio 协议暴露工具
**理由**：
- FastMCP 是轻量级 MCP 框架，与原生 MCP 协议兼容
- stdio 传输适合本地进程调用
- 项目已有成功实践
**影响范围**：所有工具通过 `register(mcp)` 函数注册

### DEC-002: 幂等性设计 (2025-01)
**背景**：需要支持断点续跑，避免重复执行已完成步骤
**结论**：通过检查输出文件存在性判断步骤是否完成
**理由**：
- 简单可靠，无需额外状态存储
- 符合文件系统即状态的原则
**影响范围**：`tools/pipeline.py`, 各工具 `_run()` 函数

### DEC-003: 统一文件布局管理 (2025-01)
**背景**：各工具需要统一读写论文目录，路径逻辑散落各处
**结论**：引入 `PaperWorkspace` 数据模型，集中管理文件路径
**理由**：
- 单一职责，路径逻辑集中
- 便于维护和扩展
- `paper_dir` 下所有产物有明确命名规范
**影响范围**：`models/paper.py`

### DEC-004: 统一返回格式 (2025-01)
**背景**：各工具返回格式不统一，上层难以判断处理状态
**结论**：所有步骤返回统一 JSON 包 `{"status": "success"/"error"/"already_exists"/"dry_run", ...}`
**理由**：
- 上层（pipeline/Agent）可依此判断是否继续
- 统一错误处理逻辑
**影响范围**：所有 tools 模块

### DEC-005: 元数据降级策略 (2025-01)
**背景**：Crossref/OpenAlex 等外部 API 可能失败，不应阻断主流程
**结论**：Enrichment API 失败时降级为 LLM-only 结果，不抛出异常
**理由**：
- API 不可用是常态，需要容错
- 保留已提取数据，不因部分失败丢失全部进度
- 返回 `enrichment_facts` 告知富化状态
**影响范围**：`tools/metadata.py`

### DEC-006: 本地 Status 文档写入（草案） (2026-03-08)
**背景**：当前 pipeline 运行状态不透明，难以追踪和排障
**结论**：在 `paper_dir` 下创建 `status.json`，记录每个处理阶段的结果
**理由**：便于 Agent 感知已完成步骤
**影响范围**：`tools/pipeline.py`, `models/paper.py`
> ⚠️ **已被 DEC-007 / DEC-008 / DEC-009 细化和取代**

---

### DEC-007: 双层持久化状态设计 (2026-03-09)
**背景**：DEC-006 仅提出在 `paper_dir` 写状态，但未明确格式、分层、并发安全等细节；用户希望系统是 Agent 优先的，通过文件感知全局状态
**结论**：采用两层分离设计：
- **论文级**：`paper_dir/paper_status.json` — 记录 6 个 stage 各自的状态/时间/产物/错误
- **全局级**：`papers/processing_queue.json` — 记录所有论文的鸟瞰进度，含 summary 统计
**理由**：
- 论文级状态随 workspace 目录走，rename 后自动跟随，不丢失
- 全局队列提供单文件全貌，Agent 无需逐个查子目录
- 两层职责分离：论文级详细、全局级摘要
**影响范围**：`models/paper.py`（新增 `paper_status.json` 读写）、`models/queue.py`（新文件）
**supersedes**：DEC-006

### DEC-008: asyncio.Lock + 原子替换写入 (2026-03-09)
**背景**：多个后台 job 并发更新同一个 `processing_queue.json` 时存在写竞争风险
**结论**：`ProcessingQueue` 用类级 `_locks` dict，以文件路径为 key 按需创建 `asyncio.Lock`；写入时先写 `.tmp` 临时文件再 `rename` 替换，保证原子性
**理由**：
- MCP 是单进程 stdio 模式，同一个 event loop 内 `asyncio.Lock` 足以保护
- 先写临时文件再 rename 是 POSIX 原子写的标准做法，防止半写损坏
- 无需引入外部锁库或数据库
**影响范围**：`models/queue.py` `ProcessingQueue.update_locked()` / `ProcessingQueue.save()`

### DEC-009: asyncio.Semaphore 控制后台 job 并发上限 (2026-03-09)
**背景**：不加限制地批量提交 job 会同时打满 LLM API 和 MinerU OCR 的并发，导致限速或内存耗尽
**结论**：全局单例 `_JOB_SEMAPHORE = asyncio.Semaphore(settings.MAX_CONCURRENT_JOBS)`，在 `_job_runner` 入口的 `async with sem:` 包住整个执行体；job 在 `queued` 时等待 semaphore
**理由**：
- Semaphore 是 asyncio 原生并发控制原语，无副作用
- 在 `queued` 等待而非拒绝，保留了批量提交后自动排队执行的能力
- `MAX_CONCURRENT_JOBS` 通过 `config.py` 配置，默认 3，可按环境调整
**影响范围**：`tools/pipeline.py` `_job_runner()`、`config.py` 新增 `MAX_CONCURRENT_JOBS: int = 3`

### DEC-010: 使用 GitHub Release + PyPI Trusted Publishing 发布包 (2026-04-18)
**背景**：项目已在 PyPI 发布，后续需要从手动 `twine` 上传切换到可审计的 GitHub 自动发布流程。
**结论**：新增 `.github/workflows/publish.yml`，由 GitHub Release published 事件触发构建，并通过 PyPI OIDC Trusted Publisher 发布到 `fro-wang-academic-tools-mcp` 项目。
**理由**：
- Trusted Publishing 使用短时 OIDC 凭证，不需要在 GitHub secrets 保存长期 PyPI token
- Release 事件能把 PyPI 发布绑定到明确的 tag/release 审批动作
- 构建和发布拆成两个 job，发布 job 只下载构建产物并持有 `id-token: write`
**影响范围**：`.github/workflows/publish.yml`、GitHub environment `pypi`、PyPI 项目 Publishing 设置
