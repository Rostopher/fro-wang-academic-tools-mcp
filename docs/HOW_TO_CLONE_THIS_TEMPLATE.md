# 如何复制这套模板到其他项目

> **职责**：用最少步骤把本模板迁移到新项目，保证 Agent 和人都能快速上手。

## 步骤

1. 复制目录：`docs_template_example/` → `<你的项目>/docs/`
2. 在 `<你的项目>/CLAUDE.md` 加入 Agent 必读文档入口：
   ```markdown
   ## Agent 必读文档（按优先级）
   1. **docs/OVERVIEW.md** — 项目总览与架构
   2. **docs/STATUS.md** — 项目当前进展
   3. **docs/GLOSSARY.md** — 术语与变量定义
   4. **docs/RUNBOOK.md** — 如何运行、产物位置
   5. **docs/CONVENTIONS.md** — 编码规范与约束
   6. **docs/DECISIONS.md** — 历史设计决策
   ```
3. 把旧的日期文档迁入 `docs/archive/`
4. （可选）复制自动更新触发器：
   - Slash Command：`.claude/commands/update-docs.md`
   - Skill：`.claude/skills/update-living-docs/SKILL.md`
   - 用法：对话结束后输入 `/update-docs` 或说"更新动态文档"

> 如果你的项目不使用 Claude Code / Copilot 的 Agent 模式，可以跳过第 4 步。

## 最小维护纪律

- 项目重大变动：改 `OVERVIEW.md`
- 里程碑完成：改 `STATUS.md`
- 决策产生：追加 `DECISIONS.md`
- 新变量引入：改 `GLOSSARY.md`
- 跑法变化：改 `RUNBOOK.md`
- 规范新增或变更：改 `CONVENTIONS.md`
