# GrassFlow — 可视化多Agent积木编排平台

## 项目概述

GrassFlow 是一个**声明式多Agent编排平台**，用户可以通过"拼积木"的方式创建、连接和调度多个AI Agent，实现复杂任务的自动化分解与并行执行。

> 取名 GrassFlow（野草 + 流程）：像野草一样自由蔓延，Agent 编排自然生长。

### 核心理念

> 用户只需声明"谁依赖谁"，系统自动搞定一切。

与传统Agent工具（如Claude Code单窗口单Agent）不同，GrassFlow 允许用户：
- 以模块化方式创建多个任务级Agent
- 声明Agent之间的依赖关系
- 自动解析执行顺序和并行度
- 实时监控每个Agent的执行状态

---

## 创新点

### 1. GUI + TUI 双模式

| 模式 | 目标用户 | 场景 |
|------|---------|------|
| **GUI模式** | 非技术用户 | 可视化拖拽、积木式连线、所见即所得 |
| **TUI模式** | 开发者/AI | 声明式语法、可脚本化、可让AI自动生成编排 |

**TUI语法示例**：
```
research(A,B,C) -> analyze(A,B,C) -> report
```

### 2. 丰富的Agent交互方式

突破传统"线性传递"的限制，支持多种交互模式：

| 交互类型 | 描述 | 示例 |
|---------|------|------|
| **顺序传递** | A输出 → B输入 | `A -> B` |
| **条件分支** | A根据结果决定发给哪个Agent | `A -> [success] B, [fail] C` |
| **立即执行** | 先开始，遇到依赖再等待 | `A \| B` (B立即开始，遇到A的输入时等待) |
| **广播分发** | A的输出同时发给多个Agent | `A -> (B, C, D)` |
| **聚合等待** | 等待多个Agent全部完成 | `(A, B, C) -> D` |

### 3. 监控Agent机制

用Agent监控Agent，解决多Agent系统的核心痛点：
- 检查输出是否符合预期Schema
- 检测执行时间是否异常
- 检测结果质量（如：输出过短可能意味着敷衍）
- 发现偏差时发出警告

---

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                        用户界面层                            │
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │   GUI 模式       │    │   TUI 模式                       │ │
│  │  (React Flow)    │    │  (DSL Parser + Rich)            │ │
│  │  - 积木拖拽      │    │  - 声明式 DSL 语法               │ │
│  │  - 多种连线类型  │    │  - AI 可自动生成                  │ │
│  │  - 实时状态动画  │    │  - 终端进度展示                   │ │
│  └────────┬────────┘    └───────────────┬─────────────────┘ │
│           │                             │                   │
│  ┌────────┴─────────────────────────────┴─────────────────┐ │
│  │              共享 DAG 表示层（JSON）                     │ │
│  │   nodes[] / edges[] / conditions[] / interactionTypes[] │ │
│  └──────────────────────────┬──────────────────────────────┘ │
├─────────────────────────────┼───────────────────────────────┤
│                        后端引擎层                            │
│  ┌──────────────────────────┴──────────────────────────────┐ │
│  │                   DAG 调度引擎                           │ │
│  │  - 拓扑排序 + 依赖解析                                   │ │
│  │  - 交互类型处理（条件/广播/聚合/立即执行）                │ │
│  │  - asyncio 并行调度                                      │ │
│  └──┬───────────────────────────────────────────┬──────────┘ │
│     │                                           │            │
│  ┌──┴──────────────┐    ┌──────────────────────┴──────────┐ │
│  │  Agent Runtime   │    │      Monitor Agent              │ │
│  │  - LLM 调用      │    │  - Schema 校验                  │ │
│  │  - 工具执行      │    │  - 超时检测                      │ │
│  │  - 结果格式化    │    │  - 质量检查                      │ │
│  └─────────────────┘    └─────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 技术栈

| 层级 | 技术选型 |
|------|---------|
| **GUI前端** | React + React Flow + TypeScript + Zustand + TailwindCSS |
| **TUI前端** | Python Rich |
| **后端** | Python + FastAPI + asyncio |
| **数据持久化** | SQLite + JSON |
| **AI层** | OpenAI API / Anthropic API + LiteLLM |
| **通信** | WebSocket (实时状态推送) |
| **桌面应用** | Electron（后续迭代） |

---

## 核心设计

### Agent 定义

```python
class Agent:
    """所有 Agent 的基类"""
    name: str
    input_schema: dict        # JSON Schema
    output_schema: dict       # JSON Schema
    model: str = "gpt-4"
    prompt: str = ""
    on_fail: str = "stop"     # stop / skip / retry
    retry_count: int = 3

    async def run(self, input_data: dict) -> dict:
        raise NotImplementedError
```

### DSL 语法规范

> **设计原则**: 所有 Agent 组件系统必须先为 DSL 服务
> - 所有组件以及组件之间的关系都应该可以使用 DSL 语法表示
> - 如果组件相关的设计不能通过 DSL 语法表示，则应该先设计 DSL 语法

#### DSL v1 (当前)

```grassflow
# 基础顺序
A -> B -> C

# 并行执行
(A, B, C) -> D

# 立即执行（先启动，遇依赖等待）
A | B

# 条件分支（ConditionAgent 输出 route 字段）
route -> [urgent] human, [normal] bot

# 组合使用
(A | B) -> route -> [urgent] human, [normal] bot

# 完整工作流定义
workflow ticket_processing {
  agent classify {
    model: "gpt-4"
    prompt: "分类工单: {input}"
    input_schema: { "ticket": "string" }
    output_schema: { "category": "string" }
  }
  agent route {
    type: "condition"
    rules: ["urgent", "normal", "info"]
  }
  agent human { type: "manual" }
  agent bot {
    model: "gpt-4"
    prompt: "自动回复: {input}"
  }

  classify | priority
  -> route
  -> [urgent] human, [normal] bot
}
```

#### DSL v2 (计划中 - 支持组件系统)

```grassflow
# 组件定义 (可复用的 Agent 模板)
component code-reviewer {
  description: "代码审查专家"
  version: "1.0.0"

  # 预装载提示词
  system_prompt: """
    你是一个专业的代码审查专家...
    审查重点：
    - 代码质量
    - 安全漏洞
    - 性能问题
  """

  # 连线接口定义
  port input code: string "待审查的代码"
  port input context: object "上下文信息"
  port output review_result: object "审查结果"
  port output issues: array "发现的问题列表"

  # MCP 配置
  mcp github {
    tools: [create_issue, add_comment]
  }
  mcp sonarqube {
    tools: [analyze_code, get_metrics]
  }

  # 模型配置
  model default: "gpt-4"
  model fallback: "gpt-3.5-turbo"
  model temperature: 0.3

  # 工具权限
  permission allow: [read_file, write_file, search_code]
  permission deny: [delete_file, execute_command]
  permission ask: [commit_changes, push_code]
}

# 组件实例化 (在工作流中使用组件)
workflow my-review {
  # 实例化组件
  agent reviewer use code-reviewer {
    # 覆盖默认配置
    model temperature: 0.5
  }

  # 自定义 Agent (也可以使用组件的接口)
  agent analyzer {
    model: "gpt-4"
    prompt: "分析代码: {code}"
    # 声明接口
    port input code: string
    port output analysis: object
  }

  # 连接 (使用接口名称)
  analyzer.code -> reviewer.code
  analyzer.analysis -> reviewer.context

  # 或使用简写
  (analyzer -> reviewer).code
  (analyzer -> reviewer).analysis -> context

  # 条件分支
  reviewer.issues -> [has_issues] fixer, [no_issues] approver
}

# 组件继承
component advanced-reviewer extends code-reviewer {
  # 添加新的接口
  port input requirements: array "需求文档"

  # 覆盖提示词
  system_prompt: """
    你是一个高级代码审查专家...
    除了基础审查，还需要检查：
    - 是否符合需求
    - 架构合理性
  """

  # 添加新的 MCP
  mcp jira {
    tools: [create_ticket, update_ticket]
  }
}
```

### 数据传递机制

```python
class WorkflowContext:
    """只读数据传递"""
    def set(self, agent_id: str, data: dict):
        """Agent 只能写自己的 key"""
        self._data[agent_id] = data

    def get(self, agent_id: str) -> dict:
        """可以读任何 Agent 的输出"""
        return self._data.get(agent_id, {})
```

### 失败策略

```python
on_fail: "stop"      # 默认：任何失败，整个工作流停止
on_fail: "skip"      # 跳过该 Agent，用空结果继续
on_fail: "retry"     # 重试，配合 retry_count
```

### 配置管理

支持多级配置（参考 Claude Code）：
- **全局配置**：`~/.Grass/config.json`
- **项目配置**：`.grass/config.json`
- **环境变量**：`GRASSFLOW_*`

**配置优先级**：环境变量 > 项目配置 > 全局配置 > 默认值

```json
// ~/.Grass/config.json
{
  "version": "1.0.0",
  "api_keys": {
    "openai": "sk-xxx",
    "anthropic": "sk-xxx",
    "deepseek": null,
    "ollama": null
  },
  "llm": {
    "default_model": "gpt-4",
    "default_provider": "openai",
    "temperature": 0.7,
    "max_tokens": 4096,
    "timeout": 60,
    "retry_count": 3,
    "retry_delay": 1.0
  },
  "workflow": {
    "auto_save": true,
    "auto_validate": true,
    "max_parallel": 10,
    "default_on_fail": "stop",
    "execution_timeout": 300
  },
  "display": {
    "theme": "dark",
    "show_timestamps": true,
    "show_agent_names": true,
    "log_level": "INFO",
    "compact_mode": false
  },
  "server": {
    "host": "localhost",
    "port": 8000,
    "cors_origins": ["*"],
    "debug": false
  },
  "workflows_dir": "~/.Grass/workflows",
  "db_path": "~/.Grass/grassflow.db",
  "plugins_dir": "~/.Grass/plugins"
}
```

**CLI 配置命令**：
```bash
# 查看配置
grassflow config list                    # 列出所有配置
grassflow config list --scope global     # 只看全局配置
grassflow config list --json             # JSON 格式输出
grassflow config get llm.default_model   # 获取配置值
grassflow config path                    # 显示配置文件路径

# 修改配置
grassflow config set llm.default_model gpt-4 --scope global
grassflow config api-key openai sk-xxx   # 设置 API Key
grassflow config show-key openai         # 显示 API Key（脱敏）

# 重置配置
grassflow config reset --scope global    # 重置全局配置
grassflow config reset --scope project   # 重置项目配置
grassflow config reset --scope all       # 重置所有配置
```

**环境变量覆盖**：
```bash
# 设置环境变量
export GRASSFLOW_LLM_DEFAULT_MODEL=claude-3
export GRASSFLOW_API_KEYS_OPENAI=sk-xxx

# 运行时会自动应用
grassflow run workflow.af
```

### 预设积木类型（GUI 后续迭代）

| 类别 | 积木 | 说明 |
|------|------|------|
| AI 类（蓝色） | 🤖 LLM Agent | 调用大模型 |
| | 🔍 Search Agent | 搜索网络/知识库 |
| | 📝 Writer Agent | 专门写作 |
| | 📊 Analyzer Agent | 数据分析 |
| 控制类（橙色） | 🔀 Condition | 条件分支 |
| | ⏳ Immediate | 立即执行 |
| | ⏸️ Human | 人工审批暂停点 |
| IO 类（绿色） | 📥 Input | 工作流输入 |
| | 📤 Output | 工作流输出 |

### 连线类型（GUI 后续迭代）

| 线型 | 含义 | 样式 |
|------|------|------|
| 实线 | 顺序依赖 | ━━━━━ |
| 虚线 | 立即执行 | ╌╌╌╌╌ |
| 粗线 | 条件分支 | ═════ |

---

## 项目目标

### 短期目标（两周MVP — TUI 优先）

1. ✅ Agent 基类 + Schema 系统
2. ✅ DAG 拓扑排序 + asyncio 并行调度
3. ✅ DSL 解析器（顺序/并行/条件/立即执行）
4. ✅ ConditionAgent（条件分支）
5. ✅ LLM API 调用集成
6. ✅ 只读数据传递（Context）
7. ✅ 可配置失败策略（stop/skip/retry）
8. ✅ 工作流保存/加载（JSON）
9. ✅ 终端进度展示（Rich）
10. ✅ CLI 入口（`grassflow run/list/save`）
11. ✅ 监控报告（事后检查）
12. ✅ 执行记录（SQLite）

### 中期目标（GUI + 扩展）

1. Electron 桌面应用
2. React Flow 画布 + 左侧积木面板
3. 多种连线类型（实线/虚线/粗线）
4. 广播分发、聚合等待、超时降级
5. AI 自动生成 TUI 编排
6. 工作流模板市场
7. 本地模型支持（Ollama）

### 长期目标（产品化）

1. 用户认证 + 多租户
2. 生产级性能优化
3. A2A/MCP 协议集成
4. 嵌入式运行时（可视化设计导出为可执行代码）

---

## 与竞品的差异化

| 维度 | Langflow | n8n | CrewAI | **GrassFlow (本项目)** |
|------|----------|-----|--------|----------------------|
| **定位** | 全栈AI平台 | 业务自动化 | 代码框架 | 轻量纯编排 |
| **交互方式** | GUI | GUI | 代码 | GUI + TUI |
| **依赖声明** | 手动连线 | 手动连线 | 代码 | 声明式 DSL 语法 |
| **交互类型** | 线性 | 线性+条件 | 线性 | 线性+条件+广播+聚合+立即执行 |
| **AI生成编排** | ❌ | ❌ | ❌ | ✅ (TUI模式) |
| **监控Agent** | ❌ | ❌ | ❌ | ✅ |
| **分发方式** | pip/Docker | npm/Docker | pip | pip (TUI) + exe (GUI) |

---

## 文件结构

```
grassflow/                        # 单仓库 monorepo
├── core/                         # 共享核心（独立 Python 包）
│   ├── agent.py                  # Agent 基类 + Schema 系统
│   ├── dag.py                    # DAG 引擎 + 拓扑排序
│   ├── scheduler.py              # asyncio 并行调度器
│   ├── context.py                # 只读数据传递 Context
│   ├── monitor.py                # 监控 Agent（事后检查）
│   └── models.py                 # 数据模型
│
├── tui/                          # TUI 入口（pip install grassflow）
│   ├── cli.py                    # CLI 命令入口
│   ├── dsl_parser.py             # DSL 语法解析器
│   ├── runner.py                 # 工作流执行器
│   └── display.py                # 终端进度展示（Rich）
│
├── server/                       # FastAPI 后端
│   ├── app.py                    # FastAPI 应用
│   ├── api/
│   │   ├── workflows.py          # 工作流 CRUD API
│   │   └── executions.py         # 执行记录 API
│   └── ws.py                     # WebSocket 实时推送
│
├── gui/                          # Electron 前端（后续迭代）
│   ├── electron/                 # Electron 壳
│   ├── src/                      # React + React Flow
│   └── package.json
│
├── examples/                     # 示例工作流 (.gf 文件)
├── tests/                        # 测试
├── setup.py                      # Python 包配置
├── CLAUDE.md                     # 项目说明
└── 项目制作计划.md
```

---

## 数据持久化

```
~/.Grass/                           # 全局配置目录
├── config.json                     # 全局配置（API Key、默认模型等）
├── workflows/                      # 工作流定义（JSON）
│   ├── ticket_processing.json
│   └── competitor_analysis.json
├── plugins/                        # 插件目录
└── grassflow.db                    # 执行记录（SQLite）

.grass/                             # 项目配置目录（可选）
└── config.json                     # 项目级配置（覆盖全局配置）
```

---

## 开发规范

- Python 环境：使用项目目录下的虚拟环境 `.venv`
- 后端：Python + FastAPI + asyncio
- 前端：TypeScript 严格模式（GUI 后续迭代）
- 代码风格：遵循各语言主流规范
- 版本控制：Git

### 主代理职责

**主代理不参与开发细节。** 主代理只负责：
1. 分析需求，规划工作流，编排子代理
2. 定义子代理之间的接口契约
3. 接收子代理报告，汇总进度，向用户汇报

**以下工作必须由子代理执行，主代理不得参与：**
- 阅读/搜索/分析代码
- 编写/修改代码
- 运行测试
- 调试、排错、修复 bug
- 运行命令（pip install、git 操作除外）
- 任何与"读、写、执行、调试"相关的开发活动

**主代理允许的操作：**
- git status / git add / git commit
- pip install（安装依赖）
- 编辑 CLAUDE.md 和计划文件
- 使用 Agent 工具派发子代理
- 读取子代理输出报告（docs/*.md）

### Git 提交规范

**修改前**：检查是否已提交仓库，如果未提交则先提交当前状态
```bash
git status
git add .
git commit -m "描述当前状态"
```

**修改后**：立即提交更改
```bash
git add .
git commit -m "描述本次修改"
```

**重要**：每次修改代码前必须确保仓库是干净状态，修改完成后必须立即提交。

---

## 推荐技能使用指南

在开发过程中，遇到以下场景时**主动调用对应技能**：

### 开发阶段

| 场景 | 技能 | 说明 |
|------|------|------|
| 每个阶段完成后审查 | `/grill-me` | 压测当前实现的设计决策 |
| 核心模块开发（dag.py, scheduler.py, agent.py） | `/tdd` | 测试驱动开发，先写测试再写实现 |
| 验证 DSL 语法或 DAG 调度方案 | `/prototype` | 构建一次性原型验证可行性 |
| 遇到 async 调度或复杂 bug | `/diagnose` | 系统化诊断：复现→最小化→假设→修复 |

### 架构与质量

| 场景 | 技能 | 说明 |
|------|------|------|
| MVP 完成后重构 | `/improve-codebase-architecture` | 找重构机会，降低耦合 |
| 迷失在细节时 | `/zoom-out` | 拉远视角，理解全局 |
| Git 操作保护 | `/git-guardrails` | 阻止危险 git 命令 |

### 持续改进

| 场景 | 技能 | 说明 |
|------|------|------|
| 命令失败或用户纠正时 | `/self-improving-agent` | 自动捕获错误和改进点 |
| 需要创建新技能时 | `/write-a-skill` | 创建项目专用技能 |

### 后续迭代（GUI 阶段）

| 场景 | 技能 | 说明 |
|------|------|------|
| Electron GUI 视觉设计 | `/frontend-design` | UI 设计指导，避免模板化 |
| 项目计划拆解为 issue | `/to-issues` | 把制作计划拆成可独立领取的任务 |

---

## 参考项目与开发哲学

### ⚠️ 核心原则：不要重复造轮子！

opencode 和 hermes 是**商业级、完整的 AI Agent 框架**，均采用 MIT 协议。它们已经解决了大量工程问题，GrassFlow 应该：

1. **参考甚至照搬** 它们的项目结构和源码文件（MIT 协议允许）
2. **先读分析报告** — `docs/` 文件夹下有大量分析报告，重新调查前必须先阅读
3. **站在巨人肩膀上** — 不要从零实现已有成熟方案的功能

### 参考项目路径

| 项目 | 路径 | 协议 | 特点 |
|------|------|------|------|
| **opencode** | `E:\opencode-desktop\opencode-dev\opencode-dev` | MIT | TypeScript, TUI 精美, MCP 完整, 命令面板 |
| **hermes** | `E:\opencode-desktop\hermes-agent-main\hermes-agent-main` | MIT | Python, 功能极丰富, 80+ CLI 命令, Skills 系统 |

### 已有分析报告（`docs/` 目录）

| 报告 | 内容 |
|------|------|
| `hermes-opencode-analysis.md` | 两者对比分析 |
| `opencode-cli-features.md` | opencode CLI 功能清单 |
| `opencode-tui-analysis.md` | opencode TUI 架构分析 |
| `hermes-tui-analysis.md` | hermes TUI/CLI 源码分析 |
| `grassflow-cli-gap-analysis.md` | GrassFlow 与竞品差距分析 |
| `grassflow-cli-current.md` | GrassFlow 当前 CLI 状态 |
| `grassflow-current-analysis.md` | GrassFlow 整体分析 |
| `official-docs-analysis.md` | 官方文档分析 |
| `refactoring-plan.md` | 重构计划 |
| `dsl-v2-specification.md` | DSL v2 规范 |

### 功能实现优先级参考

**从 hermes 搬运（Python 项目，直接可用）：**
- Thinking 模式：`agent/anthropic_adapter.py` (adaptive + manual budget)
- 思考块清理：`agent/think_scrubber.py` (StreamingThinkScrubber)
- 推理力度解析：`hermes_constants.py:parse_reasoning_effort()`
- MCP 客户端：`tools/mcp_tool.py` (~2500 行，完整实现)
- MCP 配置：`hermes_cli/mcp_config.py`
- Skills 系统：`tools/skills_tool.py` + `agent/prompt_builder.py`
- AGENTS.md 加载：`agent/prompt_builder.py:build_context_files_prompt()`
- 系统提示词三层架构：`agent/system_prompt.py`
- 命令注册：`hermes_cli/commands.py:COMMAND_REGISTRY`

**从 opencode 参考（TypeScript，参考设计）：**
- 命令面板：`packages/tui/src/component/command-palette.tsx`
- 命令注册模式：`slashName` + `slashAliases` + `category`
- MCP 配置格式：`opencode.json` 的 `mcp` 字段
- 模型变体（思考力度）：`/variants` 命令

### 当前 GrassFlow TUI 模块文件清单

```
tui/
├── __init__.py
├── repl.py                 # REPL 主循环
├── layout.py               # prompt_toolkit 布局/样式/快捷键
├── slash_commands.py       # 命令注册表 + 补全器 + 21 个命令
├── agent_loop.py           # Agent 感知-思考-行动-观察循环
├── agent_integration.py    # Agent 与 REPL 集成
├── stream_handler.py       # 流式输出处理
├── session.py              # 会话管理 (SQLite)
├── context_compressor.py   # 上下文压缩器 (未集成)
├── config_integration.py   # 配置集成
├── thinking_renderer.py    # 思考过程渲染
├── permission_handler.py   # 权限处理器
├── tool_executor.py        # 工具执行器
├── display.py              # Rich 终端显示
├── cli.py                  # CLI 入口
├── error_handler.py        # 错误处理
├── dsl_parser.py           # DSL 解析器
├── runner.py               # 工作流执行器
├── templates.py            # 工作流模板
├── models.py               # 数据模型
├── mcp_client.py           # MCP 客户端 (未集成)
├── compat.py               # 兼容层
└── fallback.py             # 降级模式
```
