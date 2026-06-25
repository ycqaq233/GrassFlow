# GrassFlow CLI 差距分析

> 分析日期：2026-06-25
> 对标：opencode TUI (参考 `docs/hermes-opencode-analysis.md`)

---

## 1. 当前状态总览

### 文件清单 (tui/ 目录，12 个文件)

| 文件 | 大小 | 状态 | 核心职责 |
|------|------|------|---------|
| `cli.py` | 25KB | 可用 | Click CLI 入口，12 个命令 |
| `repl.py` | 35KB | 部分可用 | REPL 主循环、消息渲染、命令处理 |
| `display.py` | 7KB | 可用 | Rich 格式化输出 |
| `dsl_parser.py` | 14KB | 可用 | DSL v1 解析器 |
| `dsl_parser_v2.py` | 14KB | 可用 | DSL v2 解析器（组件系统） |
| `session.py` | 36KB | 已实现未集成 | 会话管理 + SQLite 持久化 + 断点恢复 |
| `editor.py` | 22KB | 可用 | Textual 交互式编辑器 |
| `monitor_panel.py` | 11KB | 可用 | htop 风格实时监控面板 |
| `stream_handler.py` | 7KB | 已实现未集成 | LLM 流式响应渲染 |
| `context_compressor.py` | 27KB | 已实现未集成 | Token 检测 + 摘要压缩 |
| `templates.py` | 15KB | 可用 | 5 个工作流模板 |
| `__init__.py` | 1KB | 可用 | 模块导出 |

---

## 2. 逐文件详细分析

### 2.1 cli.py — CLI 命令入口

**当前功能：**
- 12 个 Click 命令：`run`, `save`, `list`, `validate`, `history`, `inspect`, `delete`, `templates`, `create`, `monitor`, `edit`, `repl`
- 配置管理子命令组：`config get/set/list/reset/api-key/show-key/path`

**正常工作的：**
- 基本命令路由和参数解析
- 工作流执行流程（parse -> create agents -> schedule -> save record）
- 配置管理命令
- Rich 表格输出（history, templates, config list）

**问题和缺失：**
1. `run` 命令的 `--model` 参数硬编码为 `gpt-4`，应从配置读取默认值
2. `generate_dsl()` 函数的 DSL 生成逻辑过于简化，不能正确生成并行和条件分支
3. `edit` 命令依赖 `textual`，但没有在 `requirements.txt` 中声明
4. 没有 `grassflow init` 命令来初始化项目目录结构
5. 没有 `grassflow doctor` 命令来检查环境和依赖
6. 没有 shell 补全支持（bash/zsh/fish）
7. 命令输出不一致：有些用 `display`，有些用 `click.echo`，有些用 Rich 直接输出

### 2.2 repl.py — REPL 主循环

**当前功能：**
- 消息类型系统（user/assistant/system/error）
- 命令处理器（11 个 slash 命令）
- 消息渲染器（Markdown、代码块、表格、面板）
- 输入处理器（历史记录、中断信号）
- 流式输出集成（通过 StreamHandler）
- 信号处理（Ctrl+C 双击退出）

**正常工作的：**
- 基本输入-输出循环
- Slash 命令解析和执行
- Rich 格式化渲染
- Ctrl+C 中断处理

**核心缺陷（与 opencode 对比）：**

| 维度 | opencode | GrassFlow REPL | 差距 |
|------|----------|----------------|------|
| **架构** | Agent Loop（感知->思考->行动->观察） | 简单输入-输出循环 | 根本性缺失 |
| **工具调用** | 内置工具 + MCP 工具动态调用 | 无工具调用能力 | 根本性缺失 |
| **会话管理** | 自动持久化、多会话切换 | SessionManager 存在但未集成 | 未连接 |
| **上下文压缩** | 自动检测 + 压缩 | ContextCompressor 存在但未集成 | 未连接 |
| **流式渲染** | token-by-token 实时渲染 + Markdown 渐进渲染 | 基本流式输出 | 功能粗糙 |
| **多行输入** | 支持 Shift+Enter 或粘贴多行 | 不支持 | 缺失 |
| **命令补全** | Tab 补全 | 无 | 缺失 |
| **子 Agent** | 可 spawn 子 Agent 并行执行 | 无 | 缺失 |
| **中断恢复** | 优雅中断 + 恢复执行 | 基本中断 | 功能粗糙 |
| **主题系统** | 可配置主题 | 硬编码样式 | 缺失 |

**关键问题：**
1. `_handle_message()` 中，当没有 `on_message` 回调时，直接进入回显模式或流式模式，但流式模式的消息构建逻辑有 bug：它创建的是 `tui.repl.Message` 对象而不是 `core.llm_protocol.Message` 对象
2. `_handle_streaming_message()` 中用 `asyncio.run()` 嵌套调用，如果外层已有 event loop 会报错
3. 命令处理器的 `_cmd_run` 只返回 data dict，实际执行逻辑在 `_handle_command` 中，但 `/run` 命令的结果渲染不走 `_execute_workflow` 的完整路径
4. `run_async()` 方法使用 `run_in_executor` 读取输入，但没有处理 executor 中的异常

### 2.3 display.py — 终端展示

**当前功能：**
- 工作流信息展示（树形结构）
- 执行状态展示（颜色编码）
- 执行结果表格
- 错误/成功/信息消息
- 进度条（ProgressDisplay）

**问题：**
1. 全局单例 `display` 和 `progress_display` 不支持多 Console 实例
2. `print_execution_result` 假设 `record` 一定是 `ExecutionRecord`，但 REPL 中传入的可能是 dict
3. 没有 spinner/loading 动画的统一管理
4. 进度条 `execute_with_progress` 的 callback 接口设计不直观

### 2.4 dsl_parser.py — DSL v1 解析器

**正常工作的：**
- 基本 workflow/agent 声明解析
- 顺序流（A -> B -> C）
- 并行流（(A, B, C) -> D）
- 立即执行（A | B）
- 条件分支（[urgent] A, [normal] B）
- 嵌套大括号匹配

**问题：**
1. `_parse_flow` 中移除 agent 声明的逻辑是逐个匹配移除，如果 agent 名称出现在流声明中会导致误删
2. 不支持多行字符串（prompt 中包含换行）
3. 不支持转义字符（如 prompt 中的引号）
4. 错误信息不够详细（没有行号、列号）
5. 不支持 DSL v2 语法

### 2.5 dsl_parser_v2.py — DSL v2 解析器

**正常工作的：**
- component 定义解析
- workflow 定义解析
- port 声明
- model/mcp/permission 配置
- agent use component 语法
- 连接解析（A.x -> B.y）

**问题：**
1. 不支持条件分支语法（[urgent]）
2. 不支持立即执行语法（|）
3. 三引号多行字符串的正则匹配在嵌套三引号时会失败
4. `_parse_connection_line` 要求严格 `->` 分割，不支持链式连接（A -> B -> C）

### 2.6 session.py — 会话管理

**当前功能：**
- SQLite 持久化（sessions, session_messages, session_checkpoints 表）
- 会话 CRUD（create/get/update/delete/list）
- 消息 CRUD（add/get/delete）
- 断点管理（save/get/list checkpoint）
- 会话恢复（resume_session, restore_context）
- 会话导出/导入

**设计质量：** 这是 tui/ 中设计最好的模块，数据模型清晰，接口完整。

**问题：**
1. **未被 REPL 集成** — 这是最大的问题。REPL 不使用 SessionManager，每次启动都是全新会话
2. `SessionDatabase` 和 `core/db.py` 的 `ExecutionDatabase` 共用同一个 SQLite 文件但没有事务协调
3. `resume_session` 中重置 BUSY 状态为 IDLE，但没有实际恢复执行的逻辑
4. `find_resumable_session` 的查找逻辑可以优化（当前是线性扫描）

### 2.7 editor.py — 交互式编辑器

**当前功能：**
- Textual App 实现
- Agent 编辑对话框
- Edge 编辑对话框
- 左侧 Agent/Edge 列表，右侧信息面板
- 快捷键操作（A/E/D/C/X/S/L/V/P/N/Q）
- DSL 预览和生成

**问题：**
1. DSL 生成逻辑（`generate_dsl`）与 `cli.py` 中的重复，且都有 bug
2. `action_load` 中引用了 `tui.storage`，应该是 `core.storage`
3. 没有文件选择对话框，load 只能加载第一个保存的工作流
4. 没有 undo/redo 功能
5. 没有拖拽连线（这是 Textual 的限制，需要后续 GUI 实现）
6. 依赖 `textual` 但不在 requirements.txt 中

### 2.8 monitor_panel.py — 实时监控面板

**当前功能：**
- Rich Layout 布局（header + agents table + progress + logs）
- Agent 状态跟踪（pending/running/completed/failed）
- 实时日志面板
- 进度统计

**问题：**
1. 通过 monkey-patch `scheduler._execute_agent` 来捕获事件，这是脆弱的做法
2. `execute_with_monitor` 中 `asyncio.run()` 嵌套可能导致 event loop 冲突
3. 没有持久化监控数据
4. 日志面板没有滚动支持

### 2.9 stream_handler.py — 流式处理器

**当前功能：**
- StreamHandler 类，支持 token-by-token 输出
- LLMClientFactory 从配置创建客户端
- 中断支持

**问题：**
1. **未被 REPL 正确集成** — REPL 中的消息对象类型不匹配
2. `LLMClientFactory.create_from_config()` 的实现依赖 `core.config.config_manager.load_config()` 返回的对象结构，如果配置格式变化会 break
3. 没有错误重试逻辑
4. 没有输出缓冲区（频繁的 `console.print(token, end="")` 可能导致性能问题）

### 2.10 context_compressor.py — 上下文压缩器

**当前功能：**
- Token 估算（字符数 / 3）
- 消息选择策略（保留最近 N 轮）
- LLM 摘要生成
- 自动压缩包装器（AutoCompactingContext）

**设计质量：** 设计精良，参考了 opencode 的 compaction.ts。

**问题：**
1. **未被 REPL 集成** — 对话再长也不会触发压缩
2. Token 估算使用固定比率（3 字符/token），对中文不准确
3. `SUMMARY_TEMPLATE` 是中文的，但项目其他部分是英文，不一致
4. `build_compaction_prompt` 中的 `previous_summary` 嵌入方式可能导致 prompt injection

### 2.11 templates.py — 工作流模板

**当前功能：**
- 5 个预定义模板：ticket_processing, competitor_analysis, code_review, data_pipeline, chatbot
- 模板查询和创建工作流

**问题：**
1. 模板硬编码在 Python 文件中，不支持从文件加载
2. 没有用户自定义模板的机制
3. 模板中的 model 硬编码为 "gpt-4"

---

## 3. 与 opencode TUI 的关键差距

### 3.1 架构级差距

```
opencode 架构:
┌─────────────────────────────────────────────────┐
│  App (app.tsx)                                   │
│  ├── Session Manager (自动持久化)                │
│  ├── Agent Loop (感知→思考→行动→观察)            │
│  │   ├── Tool Registry (内置 + MCP)              │
│  │   ├── LLM Client (多 Provider)                │
│  │   └── Context Manager (自动压缩)              │
│  ├── UI Layer                                    │
│  │   ├── Input (多行、补全、快捷键)              │
│  │   ├── Output (Markdown、代码高亮、diff)       │
│  │   └── Status Bar (token、成本、模型)          │
│  └── Event System (状态变更通知)                 │
└─────────────────────────────────────────────────┘

GrassFlow 当前架构:
┌─────────────────────────────────────────────────┐
│  CLI (click)                                     │
│  ├── REPL (简单输入-输出循环)                    │
│  │   ├── Command Handler (slash 命令)            │
│  │   ├── Message Renderer (Rich)                 │
│  │   └── Input Handler (历史记录)                │
│  ├── Session Manager (未集成)                    │
│  ├── Context Compressor (未集成)                 │
│  ├── Stream Handler (未正确集成)                 │
│  └── Tools (存在但未连接)                        │
└─────────────────────────────────────────────────┘
```

**核心差距：缺少 Agent Loop。** opencode 的核心是一个持续的 Agent 循环（感知环境 -> 思考决策 -> 调用工具 -> 观察结果），而 GrassFlow REPL 只是一个简单的"用户输入 -> LLM 响应"管道。

### 3.2 功能级差距

| 功能 | opencode | GrassFlow | 优先级 |
|------|----------|-----------|--------|
| Agent Loop（工具调用循环） | 完整实现 | 完全缺失 | **P0** |
| 会话持久化 + 恢复 | 自动 | 有代码未集成 | **P0** |
| 工具执行（shell/read/write/glob/grep） | 内置 + MCP | tools/ 有代码未连接 | **P0** |
| 上下文自动压缩 | 自动触发 | 有代码未集成 | **P1** |
| 流式 Markdown 渐进渲染 | 完整 | 基本 | **P1** |
| 多行输入 | 支持 | 不支持 | **P1** |
| 命令 Tab 补全 | 支持 | 不支持 | **P2** |
| 状态栏（token/成本/模型） | 完整 | 缺失 | **P2** |
| 子 Agent 管理 | 支持 | 缺失 | **P2** |
| 主题系统 | 可配置 | 硬编码 | **P3** |
| Shell 补全脚本 | bash/zsh/fish | 缺失 | **P3** |
| 工作流可视化（DAG 图） | N/A | 缺失（GUI 阶段） | **P3** |

### 3.3 代码质量差距

| 维度 | 问题 |
|------|------|
| **模块耦合** | REPL 没有使用 SessionManager、ContextCompressor、ToolRegistry 等已实现的模块 |
| **重复代码** | `cli.py` 和 `editor.py` 中的 DSL 生成逻辑重复 |
| **错误处理** | 多处 bare `except Exception`，错误信息不够结构化 |
| **类型安全** | 没有使用 type hints 的一致性（有些函数有，有些没有） |
| **测试覆盖** | cli.py、display.py、editor.py、monitor_panel.py、stream_handler.py 没有测试 |
| **依赖管理** | `textual` 不在 requirements.txt 中 |

---

## 4. 改进优先级

### P0 — 核心功能（必须完成，否则 CLI 不可用）

1. **实现 Agent Loop**
   - 在 REPL 中实现 感知->思考->行动->观察 循环
   - 集成 ToolRegistry，让 LLM 可以调用工具
   - 支持多轮工具调用（一个用户请求可能触发多次工具调用）
   - 位置：`tui/repl.py` 或新建 `tui/agent_loop.py`

2. **集成 SessionManager**
   - REPL 启动时自动创建/恢复会话
   - 每条消息自动持久化
   - 支持 `/session` 命令（list/switch/new/delete）
   - 位置：修改 `tui/repl.py`

3. **连接工具系统**
   - 将 `tools/` 目录下的工具注册到 REPL 的 Agent Loop 中
   - 支持 MCP 工具动态发现
   - 工具执行前的权限检查
   - 位置：修改 `tui/repl.py`，使用 `core/tool_registry.py`

4. **修复 StreamHandler 集成**
   - REPL 中的消息对象类型需要统一
   - 修复 `asyncio.run()` 嵌套问题
   - 位置：修改 `tui/repl.py` 和 `tui/stream_handler.py`

### P1 — 体验提升（显著改善可用性）

5. **集成 ContextCompressor**
   - 在 REPL 对话循环中自动检测 token 使用
   - 超限时自动触发压缩
   - 显示压缩状态通知
   - 位置：修改 `tui/repl.py`

6. **改进流式渲染**
   - 支持 Markdown 渐进渲染（边输出边解析 Markdown）
   - 代码块语法高亮
   - 位置：修改 `tui/stream_handler.py`

7. **多行输入支持**
   - 支持 Shift+Enter 换行
   - 支持粘贴多行文本
   - 位置：修改 `tui/repl.py` 的 `InputHandler`

8. **统一错误处理**
   - 使用 `core/error_classifier.py` 的结构化错误
   - 统一错误输出格式
   - 位置：修改所有 tui/ 文件

### P2 — 功能完善

9. **状态栏**
   - 显示当前模型、token 使用量、会话时长
   - 参考 opencode 的 status bar
   - 位置：修改 `tui/repl.py`

10. **命令补全**
    - Tab 补全 slash 命令
    - 文件路径补全
    - 位置：修改 `tui/repl.py` 的 `InputHandler`

11. **`grassflow init` 命令**
    - 初始化 `.grass/` 目录结构
    - 创建默认配置文件
    - 位置：修改 `tui/cli.py`

12. **`grassflow doctor` 命令**
    - 检查 Python 版本、依赖、配置、API Key
    - 位置：修改 `tui/cli.py`

13. **修复 DSL 生成**
    - 统一 `cli.py` 和 `editor.py` 中的 DSL 生成逻辑
    - 正确生成并行和条件分支语法
    - 位置：新建 `tui/dsl_generator.py`

### P3 — 锦上添花

14. **主题系统**
15. **Shell 补全脚本**
16. **子 Agent 管理**
17. **工作流可视化（ASCII DAG 图）**
18. **插件系统**

---

## 5. 建议的重构路径

### 阶段一：打通核心循环（1-2 天）

```
目标：REPL 能真正"做事"，而不只是聊天

1. 新建 tui/agent_loop.py
   - 实现基本的 Agent Loop（LLM -> 工具调用 -> 结果反馈 -> 继续）
   - 集成 ToolRegistry
   - 集成 LLMClient

2. 修改 tui/repl.py
   - REPL 使用 AgentLoop 处理用户消息
   - 集成 SessionManager（自动保存会话）
   - 修复 StreamHandler 集成

3. 修改 tui/cli.py
   - 添加 init 和 doctor 命令
   - 统一错误处理
```

### 阶段二：体验打磨（1-2 天）

```
目标：用起来顺畅

4. 集成 ContextCompressor
5. 改进流式渲染
6. 多行输入支持
7. 统一 DSL 生成逻辑
8. 添加缺失的测试
```

### 阶段三：功能完善（2-3 天）

```
目标：功能完整

9. 状态栏
10. 命令补全
11. 子 Agent 管理
12. 工作流 ASCII 可视化
```

---

## 6. 总结

GrassFlow TUI 的**基础设施已经相当完善**（SessionManager、ContextCompressor、ToolRegistry、StreamHandler 都已实现），但**最大的问题是这些模块没有被连接起来**。REPL 仍然是一个简单的输入-输出管道，缺少 opencode 那样的 Agent Loop 核心。

**一句话总结：零件都有，但发动机没装上。**

优先级最高的工作是实现 Agent Loop 并将现有模块集成到 REPL 中，这将使 GrassFlow 从"一个能聊天的 REPL"变成"一个能执行任务的 AI Agent"。
