# 编码规范（CONVENTIONS.md）

> **职责**：约束 Agent 和人写代码时的风格、命名、错误处理、输入输出等，保证项目一致性和可维护性。
> **最后更新**：2026-03-09

---

## 1. 命名规范

- **Python 变量、函数、文件名**：一律用 `snake_case`
- **类名**：用 `CamelCase`
- **配置项、常量**：用全大写加下划线（如 `MAX_ITER`）
- **MCP 工具函数**：用 `snake_case`（如 `ocr_paper`）

## 2. 文件组织

- 每个模块单独一个文件夹，文件夹下只放相关代码和文档
- 测试代码放在 `tests/` 或模块下的 `test_*.py`
- Prompt 模板放在 `prompts/` 目录

## 3. 模块结构约定

- 每个工具模块必须暴露两个函数：
  - `_run()` — 模块级入口，供 pipeline 复用
  - `register(mcp)` — 注册函数，供 server.py 调用
- 禁止在 `register()` 外访问 `mcp` 实例

## 4. 错误处理

- **必须**：返回统一 JSON 格式 `{"status": "success"/"error"/"already_exists"/"dry_run", ...}`
- 数据缺失、格式错误等情况一律返回明确错误状态，不允许 silent skip
- 重要异常需写明上下文

## 5. 输入输出约定

- **必须**：使用 `PaperWorkspace` 管理路径，禁止自己拼接 `paper_dir + "/full.md"`
- **必须**：通过 `config.settings` 读取配置，禁止直接 `os.getenv()`
- **必须**：使用 `get_llm_client()` 单例，禁止自己实例化 `AsyncOpenAI`

## 6. 依赖管理

- 新增依赖需在 `pyproject.toml` 的 `dependencies` 中登记
- Python 版本统一为 **≥ 3.11**

## 7. 幂等性约定

- 所有处理步骤必须支持幂等：已完成的步骤不重复执行
- 检查逻辑：输出文件存在即跳过
- 统一返回 `{"status": "already_exists"}`

## 8. 返回格式约定

- 所有 MCP 工具必须返回 JSON 字符串
- 所有 pipeline 步骤必须返回统一状态包
- 错误信息包含在 `error` 字段中

---

## 最关键的 5 条硬规则

> 这 5 条建议同步写进 CLAUDE.md，保证 Agent 每次都能读到：

1. **使用 `PaperWorkspace` 管理路径** — 禁止自己拼接路径
2. **使用 `get_llm_client()` 单例** — 禁止自己实例化 LLM 客户端
3. **使用 `config.settings`** — 禁止直接 `os.getenv()`
4. **统一返回 JSON 格式** — 禁止返回非结构化数据
5. **幂等性优先** — 任何处理步骤都要考虑重跑场景
