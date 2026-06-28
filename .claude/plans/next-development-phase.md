# 下一阶段开发计划

> 创建时间：2026-06-28
> 前置依赖：v2 类型系统重构完成

---

## 总览

```
Phase 0: v2 类型系统重构（5-7天）     ← refactor-v2-migration.md
Phase 1: 工作流 CLI 集成（3天）
Phase 2: REPL DSL 交互模式（2天）
Phase 3: 工作流监控面板（2天）
Phase 4: AI 工作流生成（1天）
Phase 5: 组件系统（2天）
Phase 6: 历史遗留修复（2天）
```

---

## Phase 1：工作流 CLI 集成（3天）

### 目标

用户可以通过命令行完成工作流的完整生命周期：创建 → 验证 → 执行 → 查看历史。

### 1.1 重构 CLI agent 创建逻辑（Day 1）

`cli.py` 中 `run` 和 `monitor_cmd` 重复了大量 agent 创建代码。提取为共享函数：

```
_create_agents_from_workflow(workflow, parse_result) -> Dict[str, Agent]
```

同时：
- `run` 命令改为接受 `.gf` 文件（不再支持 `.af`）
- 删除 `_generate_dsl()` 函数（v1 序列化器）
- 删除 `save` 命令（v1 存储格式）

### 1.2 工作流存储更新（Day 2）

`core/storage.py` 需要：
- `save()` 序列化 v2 `Workflow`（Pydantic BaseModel）
- `load()` 反序列化为 v2 `Workflow`
- 存储格式从 v1 JSON 改为 v2 JSON
- `list()` 返回带元数据的工作流列表（名称、agent 数量、创建时间）

新增 `grassflow delete <name>` 命令。

### 1.3 CLI 命令完善（Day 3）

| 命令 | 变更 |
|------|------|
| `grassflow run <file.gf>` | 使用 v2 parser + 新 Scheduler |
| `grassflow list` | 显示 v2 工作流元数据 |
| `grassflow validate <file.gf>` | 用 v2 parser 验证 + DAG 环检测 |
| `grassflow templates` | 显示 v2 格式模板 |
| `grassflow new <name>` | 从模板创建 v2 `.gf` 文件 |
| `grassflow delete <name>` | 删除已保存的工作流 |
| `grassflow inspect <name>` | 显示工作流详情（组件、连接、端口） |
| `grassflow history` | 保持不变（从 DB 读取） |

### 验收

```bash
grassflow templates                    # 列出 5 个模板
grassflow new ticket_processing        # 创建 .gf 文件
grassflow validate ticket_processing.gf  # 验证通过
grassflow run ticket_processing.gf     # 端到端执行
grassflow history                      # 查看执行记录
```

---

## Phase 2：REPL 工作流智能编排（3天）

### 目标

REPL 中的 AI 能**主动识别多步骤任务**，自动生成 DSL 编排工作流并执行。用户也可以通过命令手动触发。

### 核心场景

```
场景 1：AI 主动编排
❯ 帮我分析这三个项目的代码质量，然后生成对比报告
  🤖 检测到多步骤任务，正在编排工作流...
  ┌─ Workflow: code_quality_analysis ────────────────┐
  │ [analyze_proj_A] ──┐                              │
  │ [analyze_proj_B] ──┼──→ [compare] ──→ [report]   │
  │ [analyze_proj_C] ──┘                              │
  └──────────────────────────────────────────────────┘
  确认执行？[Y/n] Y
  ⏳ 执行中... (并行: analyze_proj_A, B, C)

场景 2：用户主动触发
❯ /run ticket_processing.gf
  ⏳ 执行中...

场景 3：用户手动编排
❯ /run research(A,B,C) -> analyze -> report
  ✓ 解析成功
  确认执行？[Y/n] Y
```

### 2.1 工作流执行工具（Day 1）

给 AI 添加一个工具 `workflow_execute`，AI 可以调用它来执行工作流：

```python
class WorkflowExecuteTool(BaseTool):
    """AI 调用此工具来执行工作流"""
    name = "workflow_execute"
    description = "创建并执行多 Agent 工作流。当任务需要多个步骤或并行处理时使用。"

    async def execute(self, context: ToolContext) -> ToolResult:
        dsl = context.get_param("dsl")  # AI 生成的 DSL 字符串
        # 1. 解析 DSL
        # 2. 验证 DAG
        # 3. 创建 Agent 实例
        # 4. 执行 Scheduler
        # 5. 返回执行结果
```

AI 在系统提示词中被教导：
- 何时使用工作流（多步骤、可并行、需要条件分支）
- DSL 语法规范
- 如何生成有效的 Component + Workflow

### 2.2 AI 编排决策（Day 1）

在系统提示词中添加：

```
## 工作流编排能力

当用户的请求满足以下条件时，你应该使用工作流编排：
1. 任务可以分解为多个独立步骤
2. 某些步骤可以并行执行
3. 需要条件分支（根据不同结果走不同路径）
4. 涉及多个数据源或多个处理阶段

使用方式：调用 workflow_execute 工具，传入 DSL 字符串。
DSL 格式：component + workflow 声明，使用 -> 连接。
```

### 2.3 `/run` 命令增强（Day 2）

```
/run <file.gf>          # 执行工作流文件
/run <dsl_expression>   # 执行内联 DSL
/run                    # 显示当前运行的工作流
```

### 2.4 工作流状态面板（Day 2）

在 REPL 底部状态栏显示运行中的工作流：

```
❯ 用户输入中...
──────────────────────────────────────────
🔄 code_quality_analysis: 2/4 agents done | elapsed: 12.3s
```

完成后显示结果摘要。

### 2.5 工作流取消（Day 3）

```
❯ /run stop <workflow_id>   # 取消指定工作流
❯ /run stop                  # 取消所有工作流
```

### 验收

```
❯ 帮我分析这三个文件的代码质量
  🤖 我将编排一个并行分析工作流...
  ┌─ Workflow: code_analysis ──────────────────┐
  │ [analyze_1] ──┐                             │
  │ [analyze_2] ──┼──→ [summarize] ──→ [report]│
  │ [analyze_3] ──┘                             │
  └─────────────────────────────────────────────┘
  确认执行？[Y/n] Y
  ⏳ analyze_1 ✅ 2.1s | analyze_2 ✅ 1.8s | analyze_3 ✅ 2.3s
  ⏳ summarize ✅ 0.5s | report ✅ 1.2s
  ✅ 完成！总耗时: 4.5s
```

---

## Phase 3：工作流监控面板（2天）

### 目标

执行工作流时显示 htop 风格的实时监控面板。

### 3.1 集成 monitor_panel（Day 1）

`monitor_panel.py` 已经实现了 `execute_with_monitor()`，但它是通过 monkey-patch scheduler 的私有方法实现的。重构为：

- Scheduler 添加 `on_agent_start` / `on_agent_complete` / `on_agent_fail` 回调
- MonitorPanel 注册这些回调来更新状态
- 不再 monkey-patch

### 3.2 增强监控面板（Day 2）

在现有基础上增加：
- Port 级数据预览（点击 agent 查看 port 输出）
- 连接动画（数据流动画）
- 失败重试指示器
- Token 用量统计（如果可用）

### 验收

```bash
grassflow run ticket_processing.gf --watch
# 显示实时监控面板
```

---

## Phase 4：AI 工作流生成（1天）

### 目标

用户用自然语言描述需求，AI 生成 `.gf` 文件。

### 4.1 `/generate` 命令

在 REPL 中添加 `/generate` 命令：

```
❯ /generate 帮我创建一个代码审查工作流：先读代码，再审查，最后生成报告
  → AI 生成 DSL → 显示预览 → 用户确认 → 保存
```

### 4.2 接入 workflow_generator

`core/workflow_generator.py` 已有 AI 生成 DSL 的能力，需要：
- 更新生成器输出 v2 格式（Component + Workflow）
- 添加语法验证（调用 v2 parser 验证生成结果）
- 支持迭代修改（"把 report agent 的 model 改成 deepseek"）

### 验收

```
❯ /generate 创建一个数据分析工作流：数据清洗 → 特征工程 → 模型训练 → 报告
  ✓ 生成了 4 个 component，3 个 connection
  保存为 data_analysis.gf？[Y/n] Y
```

---

## Phase 5：组件系统（2天）

### 目标

实现 Component 的发现、复用和继承。

### 5.1 组件发现（Day 1）

扫描两个目录：
- `.grass/components/` — 项目级组件
- `~/.Grass/components/` — 全局组件

每个 `.gf` 文件可以包含一个或多个 `component` 声明。

### 5.2 组件继承（Day 2）

v2 parser 已支持 `extends` 语法（需要验证）。实现：
- `component advanced-reviewer extends code-reviewer { ... }`
- 子组件继承父组件的所有字段
- 子组件可以覆盖任何字段
- 端口合并（子组件端口覆盖同名父组件端口）

### 5.3 组件注册命令

```
grassflow components list          # 列出所有可用组件
grassflow components show <name>   # 显示组件详情
grassflow components install <path># 安装组件到全局目录
```

### 验收

```
❯ agent reviewer use code-reviewer {
    model default: "deepseek-v4"
  }
  ✓ 使用组件 code-reviewer，覆盖 model
```

---

## Phase 6：历史遗留修复（2天）

### 目标

修复 4 个历史遗留问题。

| 问题 | 方案 | 工作量 |
|------|------|--------|
| MCP 服务器启动 | 修复 MCPManager.start_servers() 调用链 | 0.5天 |
| ASK 审批回调 | 用 `run_in_terminal` 替代 `input()` | 0.5天 |
| Token 计数 | 贯通 USAGE 事件链：agent_loop → repl → status_bar | 0.5天 |
| 中文编码 | 全面测试 + 修复编码问题 | 0.5天 |

---

## 时间线

```
Week 1: Phase 0 — v2 类型系统重构
  Day 1: 阶段 1（类型迁移）
  Day 2: 阶段 2（Agent 重构）
  Day 3-4: 阶段 3（DAG + Scheduler）
  Day 5: 阶段 4（CLI + 模板）
  Day 6-7: 阶段 5（测试 + 清理）

Week 2: Phase 1-2 — CLI 集成 + REPL 工作流编排
  Day 1-3: Phase 1（CLI 命令）
  Day 4-6: Phase 2（REPL 智能编排）

Week 3: Phase 3-5 — 监控 + AI 生成 + 组件
  Day 1-2: Phase 3（监控面板）
  Day 3: Phase 4（AI 生成）
  Day 4-5: Phase 5（组件系统）

Week 4: Phase 6 + 收尾
  Day 1-2: Phase 6（遗留修复）
  Day 3-5: 文档更新 + 多环境测试 + 发布准备
```

---

## 优先级排序

| 优先级 | Phase | 理由 |
|--------|-------|------|
| P0 | Phase 0 | 所有后续工作的基础 |
| P0 | Phase 1 | 用户能跑通工作流才有意义 |
| P0 | Phase 2 | GrassFlow 的核心差异化 — AI 主动编排 |
| P1 | Phase 3 | 可观测性，调试必备 |
| P2 | Phase 4 | 降低使用门槛 |
| P2 | Phase 5 | 组件复用，但不阻塞核心功能 |
| P2 | Phase 6 | 稳定性提升 |
