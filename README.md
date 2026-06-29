# GrassFlow

> 可视化多 Agent 积木编排平台 · a0.3

GrassFlow 是一个**声明式多 Agent 编排平台**，用户可以通过"拼积木"的方式创建、连接和调度多个 AI Agent，实现复杂任务的自动化分解与并行执行。

> 取名 GrassFlow（野草 + 流程）：像野草一样自由蔓延，Agent 编排自然生长。

## 核心特性

- **声明式 DSL 语法**：用简洁的文本描述 Agent 依赖关系，系统自动处理执行顺序和并行调度
- **丰富的交互方式**：顺序执行、并行执行、条件分支、立即执行、Stream 流式触发
- **工具调用能力**：Agent 可调用内置工具（文件读写、搜索、Shell 命令等），支持 MCP 协议扩展
- **MCP 集成**：通过 Model Context Protocol 连接外部工具服务（GDB 调试器、浏览器自动化、搜索等）
- **权限过滤机制**：每个 Agent 组件可独立配置允许/禁止的工具，实现最小权限原则
- **实时监控面板**：DAG 可视化、Agent 状态追踪、执行时间统计
- **智能意图检测**：自然语言自动转换为 DSL 工作流
- **REPL 交互模式**：类似 Claude Code 的交互式终端，支持斜杠命令
- **AI 自主编排**：AI 可自动编写 DSL 工作流并通过 `run_workflow` 工具执行

## 快速开始

### 方式一：直接安装

```bash
# 克隆项目
git clone https://github.com/ycqaq233/GrassFlow.git
cd GrassFlow

# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 安装 grassflow 包
pip install -e .
```

### 方式二：Docker

```bash
# 构建镜像
docker build -t grassflow .

# 运行 REPL（需要传入 API Key）
docker run -it -e OPENAI_API_KEY=sk-xxx grassflow

# 运行工作流
docker run -it -e OPENAI_API_KEY=sk-xxx grassflow run examples/code_review_pipeline.gf

# 使用 docker-compose
docker-compose up          # 启动服务
docker-compose run test    # 运行测试
```

### 配置 API Key

```bash
# 通过 CLI 配置
python -m tui.cli config api-key openai sk-xxx
python -m tui.cli config api-key anthropic sk-xxx

# 或通过环境变量
export GRASSFLOW_API_KEYS_OPENAI=sk-xxx
export GRASSFLOW_API_KEYS_ANTHROPIC=sk-xxx
```

## 使用方式

### REPL 交互模式（推荐）

```bash
# 进入 REPL 交互终端
python -m tui.cli repl

# 在 REPL 中可以：
# - 直接对话 AI Agent
# - 使用斜杠命令（/help, /run, /generate 等）
# - 用自然语言描述任务，自动生成工作流
```

### CLI 命令

```bash
# 执行工作流
python -m tui.cli run examples/code_review_pipeline.gf

# 执行工作流并传入任务描述
python -m tui.cli run examples/code_review_pipeline.gf --task "审查代码质量"

# 启动监控面板
python -m tui.cli monitor examples/code_review_pipeline.gf

# 查看已保存的工作流
python -m tui.cli list

# 验证工作流语法
python -m tui.cli validate examples/code_review_pipeline.gf
```

### 配置管理

```bash
# 查看配置
python -m tui.cli config list                    # 列出所有配置
python -m tui.cli config list --scope global     # 只看全局配置
python -m tui.cli config list --json             # JSON 格式输出
python -m tui.cli config get llm.default_model   # 获取配置值
python -m tui.cli config path                    # 显示配置文件路径

# 修改配置
python -m tui.cli config set llm.default_model gpt-4 --scope global
python -m tui.cli config api-key openai sk-xxx   # 设置 API Key
python -m tui.cli config show-key openai         # 显示 API Key（脱敏）

# 重置配置
python -m tui.cli config reset --scope global    # 重置全局配置
python -m tui.cli config reset --scope project   # 重置项目配置
python -m tui.cli config reset --scope all       # 重置所有配置
```

**配置文件位置**：
- 全局配置：`~/.Grass/config.json`
- 项目配置：`.grass/config.json`

**环境变量覆盖**：
```bash
export GRASSFLOW_LLM_DEFAULT_MODEL=claude-3
export GRASSFLOW_API_KEYS_OPENAI=sk-xxx
```

### MCP 服务器配置

在 `~/.Grass/config.json` 的 `mcp_servers` 中配置外部工具服务：

```json
{
  "mcp_servers": {
    "gdb-debugger": {
      "command": "wsl",
      "args": ["-d", "kali-linux", "--", "python", "/root/mcp/gdb-mcp-server/server.py"],
      "transport": "stdio",
      "enabled": true
    },
    "playwright": {
      "command": "npx",
      "args": ["@anthropic-ai/mcp-playwright"],
      "transport": "stdio",
      "enabled": true
    },
    "tavily-search": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp.tavily.com/mcp/?tavilyApiKey=xxx"],
      "transport": "stdio",
      "enabled": true
    }
  }
}
```

在 REPL 中使用 `/mcp` 命令查看 MCP 服务器状态和已注册工具。

## DSL 语法

GrassFlow 使用声明式 DSL 描述 Agent 之间的依赖关系：

```grassflow
# 工作流定义
workflow code_review {
  # Agent 声明（使用组件系统）
  agent analyzer use code-reviewer {
    model temperature: 0.3
    permission allow: [read, glob, grep]
    permission deny: [write, shell]
  }

  agent reporter {
    model: "gpt-4"
    prompt: "根据分析结果生成报告: {input}"
  }

  # 顺序执行：analyzer -> reporter
  analyzer -> reporter
}
```

### 支持的语法

| 语法 | 说明 | 示例 |
|------|------|------|
| `A -> B` | 顺序执行 | `analyzer -> reporter` |
| `(A, B) -> C` | 并行执行 | `(analyzer, checker) -> reporter` |
| `A \| B` | 立即执行（先启动，遇依赖等待） | `analyzer \| checker` |
| `-> [x] A` | 条件分支 | `-> [urgent] human, [normal] bot` |
| `A -> (B, C)` | 广播分发 | `analyzer -> (reporter, notifier)` |
| `mode: "stream"` | Stream 流式触发 | 上游输出 list 时逐项触发 |

### 组件系统

组件是可复用的 Agent 模板，定义了模型、提示词、工具权限和接口：

```grassflow
component code-reviewer {
  description: "代码审查专家"

  system_prompt: """
    你是一个专业的代码审查专家...
  """

  # 连线接口
  port input code: string "待审查的代码"
  port output review_result: object "审查结果"

  # MCP 工具配置
  mcp filesystem {
    tools: [read, glob, grep]
  }

  # 模型配置
  model default: "gpt-4"
  model temperature: 0.3

  # 工具权限
  permission allow: [read, glob, grep]
  permission deny: [write, shell]
}
```

## 项目结构

```
GrassFlow/
├── core/                         # 共享核心模块
│   ├── agent.py                  # Agent 基类 + Schema 系统
│   ├── agent_component.py        # AgentComponent v2 数据模型
│   ├── component_registry.py     # 组件注册表 + 组件解析
│   ├── dag.py                    # DAG 引擎 + 拓扑排序
│   ├── scheduler.py              # asyncio 并行调度器 + Stream 模式
│   ├── context.py                # 只读数据传递 Context
│   ├── condition.py              # 条件分支 Agent
│   ├── config.py                 # 配置管理
│   ├── llm.py                    # LLM API 封装（支持工具调用）
│   ├── llm_agent.py              # LLM Agent（带工具调用循环）
│   ├── tool_registry.py          # 工具注册表 + 权限过滤 + ANSI 剥离
│   ├── models.py                 # 数据模型
│   └── execution.py              # 执行记录
│
├── tui/                          # TUI 入口
│   ├── cli.py                    # CLI 命令入口
│   ├── repl.py                   # REPL 交互主循环
│   ├── dsl_parser.py             # DSL 解析器入口
│   ├── dsl_parser_v2.py          # DSL v2 语法解析器
│   ├── mcp_integration.py        # MCP 客户端集成（mcp SDK）
│   ├── agent_loop.py             # Agent 感知-思考-行动循环
│   ├── agent_integration.py      # Agent 与 REPL 集成
│   ├── workflow_runner.py        # REPL 工作流执行引擎
│   ├── slash_commands.py         # 斜杠命令注册表
│   ├── monitor_panel.py          # 监控面板（Rich 渲染）
│   ├── session.py                # 会话管理（SQLite）
│   └── display.py                # 终端进度展示
│
├── tools/                        # 内置工具
│   ├── shell.py                  # Shell 命令执行
│   ├── read.py                   # 文件读取
│   ├── write.py                  # 文件写入
│   ├── glob.py                   # 文件搜索
│   ├── grep.py                   # 内容搜索
│   ├── webfetch.py               # 网页抓取
│   └── run_workflow.py           # 工作流执行工具（AI 自主编排）
│
├── examples/                     # 示例工作流 (.gf 文件)
├── tests/                        # 测试
├── docs/                         # 开发文档
├── Dockerfile                    # Docker 构建文件
├── docker-compose.yml            # Docker Compose 配置
├── setup.py                      # Python 包配置
└── requirements.txt              # 依赖列表
```

## 开发

### 运行测试

```bash
# 运行全部测试
pytest tests/ -v

# 运行特定测试
pytest tests/test_scheduler.py -v

# 运行测试并显示覆盖率
pytest tests/ --cov=core --cov=tui --cov-report=term-missing
```

### 代码质量

```bash
# 代码格式化
black core/ tui/ tests/

# 代码检查
ruff check core/ tui/ tests/
```

### 测试覆盖

项目包含 **1372 个测试**，覆盖以下模块：

| 模块 | 测试内容 |
|------|---------|
| **核心模块** | Agent、Context、Workflow、Models、AgentComponent |
| **DAG 引擎** | 拓扑排序、依赖解析、环检测、并行分组 |
| **调度器** | 顺序/并行执行、失败策略、条件分支、Stream 模式、事件回调 |
| **DSL 解析器** | v1/v2 语法解析、组件系统、连接路由规则 |
| **工具系统** | 工具注册表、权限过滤、内置工具、LLM 工具调用 |
| **LLM 集成** | LLMClient、LLMAgent、流式输出、工具调用循环 |
| **存储** | 工作流保存/加载、SQLite 执行记录 |
| **监控** | Schema 检查、质量检查、性能检查 |
| **配置管理** | 多级配置、环境变量覆盖、CLI 配置命令 |
| **REPL** | 斜杠命令、意图检测、工作流执行、会话管理 |
| **上下文管理** | Token 估算、消息压缩、上下文窗口管理 |

## 技术栈

| 层级 | 技术选型 |
|------|---------|
| **TUI 前端** | Python Rich + prompt_toolkit |
| **后端** | Python + FastAPI + asyncio |
| **数据持久化** | SQLite + JSON |
| **AI 层** | LiteLLM（支持 OpenAI / Anthropic / DeepSeek 等） |
| **通信** | WebSocket（实时状态推送） |
| **容器化** | Docker + Docker Compose |
| **CI/CD** | GitHub Actions |

## 版本历史

### a0.3 (2025-06-29)

**MCP 集成 + 工作流增强**

- MCP (Model Context Protocol) 集成，支持 stdio/HTTP/SSE 三种传输方式
- 内置 MCP 服务器支持：GDB 调试器、Playwright 浏览器自动化、Tavily 搜索、视觉识别
- AI 可通过 `run_workflow` 工具自主编写并执行 DSL 工作流
- DSL 解析器支持 `prompt:` 字段和 YAML 多行块语法 (`|-`)
- 工具调用结果 ANSI 转义码自动剥离
- 连续同名工具调用折叠显示
- 工具结果截断（防止 LLM 上下文溢出）
- 迭代耗尽时强制生成最终回复
- MCP 异步桥接（`call_tool_async`），工作流执行不再阻塞 REPL
- 熔断器机制（连续失败 3 次自动冷却 60 秒）

### a0.2

- DSL v2 语法解析器 + 组件系统
- DAG 引擎 + asyncio 并行调度器
- REPL 交互模式 + 斜杠命令
- LLM 工具调用循环
- 会话管理（SQLite）
- 监控面板

### a0.1

- 项目初始化
- Agent 基类 + Schema 系统
- 基础工作流执行

## 许可证

MIT License
