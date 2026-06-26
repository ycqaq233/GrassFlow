# GrassFlow CLI 重构计划

> 制定日期：2026-06-26
> 参考来源：hermes-agent (Python, MIT), opencode (TypeScript), 官方文档
> 目标：重构 CLI 架构，使其具备生产级质量，支持 MCP、Skills、Slash Commands、会话管理

---

## 一、现状问题总结

### P0 — 阻塞性问题

| # | 问题 | 影响 |
|---|------|------|
| 1 | `repl.py` 2,183行，承担7个职责 | 任何修改都有连锁风险 |
| 2 | 两套 LLM 系统并存 (`llm.py` vs `llm_protocol.py`) | 新开发者无法判断使用哪个 |
| 3 | `AgentConfig` 在 `models.py` 和 `agent.py` 重复定义，字段不一致 | 数据不一致 |

### P1 — 高优先级

| # | 问题 | 影响 |
|---|------|------|
| 4 | CLI 和 REPL 的 8+ 个命令功能重叠但实现独立 | 维护成本翻倍 |
| 5 | 11+ 个全局单例 | 耦合度高，测试困难 |
| 6 | 5 个已实现模块未集成 (circuit_breaker, doom_loop, context_compressor, stream_handler, session) | 功能浪费 |
| 7 | `core/component_registry.py` 反向依赖 `tui/dsl_parser_v2` | 违反分层原则 |

### P2 — 中优先级

| # | 问题 | 影响 |
|---|------|------|
| 8 | 6 个文件超过 800 行 | 可维护性差 |
| 9 | MCP 三种 Transport 初始化逻辑重复 | 代码冗余 |
| 10 | Skills 系统未与 REPL 集成 | 功能不可用 |

---

## 二、参考架构提炼

### 2.1 从 hermes 借鉴（Python，最直接）

| 设计 | hermes 实现 | GrassFlow 应用 |
|------|------------|---------------|
| **命令注册** | `CommandDef` dataclass + `COMMAND_REGISTRY` 列表 | 统一 `CommandRegistry` 类 |
| **Mixin 拆分** | `CLICommandsMixin` + `CLIAgentSetupMixin` | 将 repl.py 拆为多个 Mixin |
| **自注册工具** | `registry.register()` 模块级调用 | 统一 ToolRegistry |
| **MCP 集成** | 后台 asyncio 事件循环 + 线程安全 | 复用现有 mcp_client.py，修复重复代码 |
| **会话管理** | SQLite + resume/branch/compress/undo | 集成现有 session.py |
| **配置格式** | YAML + .env，多层合并 | JSONC + 环境变量 |

### 2.2 从 opencode 借鉴（TypeScript，设计层面）

| 设计 | opencode 实现 | GrassFlow 应用 |
|------|--------------|---------------|
| **Slash Command 声明式** | `slashName`, `slashAliases`, `category` | CommandDef 扩展字段 |
| **MCP 配置** | `local`/`remote` 类型，`{env:VAR}` 语法 | 统一配置格式 |
| **Skill 系统** | Markdown + frontmatter，`skill` 工具加载 | 复用现有 skills.py，集成到 REPL |
| **配置层级** | 6 层合并（远程→全局→自定义→项目→目录→内联） | 4 层合并 |
| **Provider 系统** | 40+ 内置，自定义通过 baseURL + apiKey | 扩展现有 ProviderConfig |
| **会话恢复** | `--continue` / `--session` / `--fork` | CLI 参数 + `/resume` 命令 |
| **自定义命令** | `$ARGUMENTS`、`!command`、`@filename` 语法 | v2 迭代 |

---

## 三、重构方案

### 阶段 1：拆分 repl.py（核心，预计 3 天）

**目标**：将 2,183 行的 repl.py 拆分为 6 个职责清晰的模块。

**参考**：hermes 的 Mixin 模式 + opencode 的声明式命令注册

```
tui/
├── repl.py              (~300行) REPL 主循环、状态机、prompt_toolkit Application
├── layout.py            (~400行) prompt_toolkit 布局/渲染/快捷键
├── slash_commands.py    (~500行) 命令注册表 + 命令处理器
├── agent_integration.py (~300行) Agent Loop 集成、流式输出
├── compat.py            (~200行) 向后兼容层（旧 API 包装）
└── fallback.py          (~100行) 降级模式（Git Bash/mintty 回退）
```

**命令注册系统设计**（参考 hermes `CommandDef` + opencode 声明式）：

```python
# tui/slash_commands.py
@dataclass(frozen=True)
class CommandDef:
    name: str                    # "model"
    description: str             # "切换模型提供商"
    category: str                # "Configuration"
    aliases: tuple[str, ...]     # ("mo",)
    args_hint: str               # "[provider:model]"
    handler: str                 # "_cmd_model"  → 方法名
    visible: bool = True         # 是否在 /help 中显示

COMMAND_REGISTRY: list[CommandDef] = [
    CommandDef("help", "显示帮助信息", "General", ("h",), "", "_cmd_help"),
    CommandDef("model", "切换模型", "Configuration", ("mo",), "[provider:model]", "_cmd_model"),
    CommandDef("models", "列出可用模型", "Configuration", (), "", "_cmd_models"),
    CommandDef("new", "新建会话", "Session", ("n", "reset"), "", "_cmd_new"),
    CommandDef("resume", "恢复历史会话", "Session", ("continue",), "[session_id]", "_cmd_resume"),
    CommandDef("sessions", "会话列表", "Session", (), "", "_cmd_sessions"),
    CommandDef("compact", "压缩上下文", "Session", (), "", "_cmd_compact"),
    CommandDef("undo", "撤销上一步", "Edit", (), "", "_cmd_undo"),
    CommandDef("redo", "重做", "Edit", (), "", "_cmd_redo"),
    CommandDef("theme", "切换主题", "Display", (), "[theme_name]", "_cmd_theme"),
    CommandDef("provider", "切换 Provider", "Configuration", (), "[name]", "_cmd_provider"),
    CommandDef("skills", "查看可用 Skills", "Skills", (), "", "_cmd_skills"),
    CommandDef("mcp", "MCP 服务器管理", "MCP", (), "[list|status]", "_cmd_mcp"),
    CommandDef("config", "配置管理", "Configuration", (), "[key] [value]", "_cmd_config"),
    CommandDef("init", "初始化项目", "Project", (), "", "_cmd_init"),
    CommandDef("doctor", "健康检查", "System", (), "", "_cmd_doctor"),
    CommandDef("clear", "清屏", "General", ("cls",), "", "_cmd_clear"),
    CommandDef("exit", "退出", "General", ("quit", "q"), "", "_cmd_exit"),
    # ... 工作流相关
    CommandDef("run", "执行工作流", "Workflow", (), "[workflow]", "_cmd_run"),
    CommandDef("list", "列出工作流", "Workflow", ("ls",), "", "_cmd_list"),
    CommandDef("history", "执行历史", "Workflow", (), "", "_cmd_history"),
    CommandDef("templates", "工作流模板", "Workflow", (), "", "_cmd_templates"),
]
```

**拆分步骤**：

1. 创建 `tui/slash_commands.py` — 提取所有命令定义和处理函数
2. 创建 `tui/layout.py` — 提取 prompt_toolkit 布局、KeyBindings、渲染逻辑
3. 创建 `tui/agent_integration.py` — 提取 Agent Loop 初始化、流式输出处理
4. 创建 `tui/compat.py` — 移动 Message、MessageRole、CommandResult 等旧类
5. 创建 `tui/fallback.py` — 提取 `_run_fallback()` 降级模式
6. 精简 `repl.py` — 只保留主循环和状态机

---

### 阶段 2：统一 LLM 层（预计 2 天）

**目标**：消除 `llm.py` 和 `llm_protocol.py` 的重复，统一为单一 LLM 接口。

```
core/llm/
├── __init__.py          # 统一导出 (LLMClient, LLMResponse, Usage)
├── client.py            # LLMClient 统一接口（合并 llm.py + llm_protocol.py）
├── providers/           # 各 Provider 实现
│   ├── __init__.py
│   ├── openai_provider.py
│   ├── anthropic_provider.py
│   ├── deepseek_provider.py
│   └── ollama_provider.py
├── types.py             # 统一类型定义 (LLMResponse, Usage, Message)
└── protocol.py          # 协议层（从 llm_protocol.py 拆分的传输/认证逻辑）
```

**关键决策**：
- 保留 `llm_protocol.py` 的 `stream_events()` 作为核心（更完整）
- 将 `llm.py` 的 litellm 封装合并为一个 Provider 实现
- 统一 `LLMResponse` 和 `Usage` 类型定义
- `AgentConfig` 只在 `core/models.py` 保留一份

---

### 阶段 3：命令系统统一（预计 1.5 天）

**目标**：CLI 和 REPL 共享同一套命令逻辑。

```python
# core/commands.py — 共享命令层
class CommandRegistry:
    """统一命令注册表，CLI 和 REPL 共享"""

    def __init__(self):
        self._commands: dict[str, CommandDef] = {}
        self._aliases: dict[str, str] = {}

    def register(self, cmd: CommandDef):
        self._commands[cmd.name] = cmd
        for alias in cmd.aliases:
            self._aliases[alias] = cmd.name

    def get(self, name: str) -> CommandDef | None:
        resolved = self._aliases.get(name, name)
        return self._commands.get(resolved)

    def execute(self, name: str, args: str, context: CommandContext) -> CommandResult:
        cmd = self.get(name)
        if not cmd:
            return CommandResult(success=False, output=f"Unknown command: {name}")
        return cmd.handler(args, context)

# 全局注册表实例
command_registry = CommandRegistry()
```

**CLI 集成**：
```python
# tui/cli.py — 使用共享注册表
@cli.command()
@click.argument("args", nargs=-1)
def run(args):
    result = command_registry.execute("run", " ".join(args), ctx)
    ...
```

**REPL 集成**：
```python
# tui/repl.py — 使用共享注册表
def _handle_slash_command(self, text: str):
    name, args = parse_slash_command(text)
    result = command_registry.execute(name, args, self._command_context)
    ...
```

---

### 阶段 4：集成未使用模块（预计 1 天）

**目标**：将 5 个已实现但未集成的模块接入系统。

| 模块 | 集成方式 |
|------|---------|
| `session.py` | REPL `/resume` 命令 + CLI `--continue`/`--session` 参数 |
| `context_compressor.py` | Agent Loop 中 token 超限时自动触发 |
| `stream_handler.py` | REPL 流式输出渲染替换当前实现 |
| `circuit_breaker.py` | Agent Loop 工具调用失败时的熔断保护 |
| `doom_loop.py` | Agent Loop 重复检测，防止无限循环 |

**集成点**：
```python
# tui/agent_integration.py
from core.session import SessionManager
from core.context_compressor import ContextCompressor
from core.circuit_breaker import CircuitBreakerManager
from core.doom_loop import DoomLoopDetector

class AgentIntegration:
    def __init__(self):
        self.session = SessionManager()
        self.compressor = ContextCompressor()
        self.breaker = CircuitBreakerManager()
        self.doom_detector = DoomLoopDetector()

    async def run_agent(self, user_input: str):
        # 1. 检查 doom loop
        if self.doom_detector.is_looping():
            yield LoopEvent(type="error", data="检测到循环，已中断")
            return

        # 2. 检查上下文大小
        if self.compressor.should_compress(self.messages):
            self.messages = await self.compressor.compress(self.messages)

        # 3. 执行 Agent Loop（带熔断保护）
        async for event in self.agent_loop.process_streaming(self.messages):
            # 4. 流式输出（使用 stream_handler）
            yield event
```

---

### 阶段 5：MCP + Skills 集成到 REPL（预计 1.5 天）

**目标**：在 REPL 中可用 `/mcp` 和 `/skills` 命令。

**MCP 集成**（参考 opencode 配置格式）：
```jsonc
// .grass/config.json
{
  "mcp": {
    "filesystem": {
      "type": "local",
      "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "environment": {},
      "timeout": 5000
    },
    "remote-server": {
      "type": "remote",
      "url": "https://mcp.example.com/sse",
      "headers": {
        "Authorization": "{env:MCP_API_KEY}"
      },
      "timeout": 10000
    }
  }
}
```

**Skills 集成**（复用现有 `core/skills.py`）：
```
搜索路径：
~/.grass/skills/          — 全局 skills
<project>/.grass/skills/  — 项目 skills
.claude/skills/           — Claude 兼容

REPL 命令：
/skills                   — 列出所有可用 skills
/skills <name>            — 查看 skill 详情
```

---

### 阶段 6：配置系统升级（预计 1 天）

**目标**：统一配置格式，支持 JSONC + 变量替换 + 多层合并。

**配置层级**（参考 opencode 6 层，简化为 4 层）：

| 优先级 | 位置 | 说明 |
|--------|------|------|
| 1 | 环境变量 `GRASSFLOW_*` | 运行时覆盖 |
| 2 | 项目配置 `.grass/config.jsonc` | 项目特定 |
| 3 | 全局配置 `~/.Grass/config.jsonc` | 用户偏好 |
| 4 | 内置默认值 | 代码中的默认配置 |

**变量替换语法**（参考 opencode）：
```jsonc
{
  "mcp": {
    "my-server": {
      "headers": {
        "Authorization": "Bearer {env:MY_API_KEY}"
      }
    }
  }
}
```

---

### 阶段 7：会话管理完善（预计 1 天）

**目标**：完整的会话生命周期管理。

**CLI 参数**（参考 opencode）：
```bash
grassflow repl                    # 新会话
grassflow repl --continue         # 继续最近会话
grassflow repl --session <id>     # 恢复指定会话
```

**REPL 命令**：
```
/new              — 新建会话
/resume [id]      — 恢复会话（无参数列出列表）
/sessions         — 会话列表
/compact          — 压缩上下文
/undo             — 撤销上一步
/redo             — 重做
```

---

## 四、重构后的目标文件结构

```
grassflow/
├── core/                          # 共享核心
│   ├── llm/                       # 统一 LLM 层（阶段2）
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── providers/
│   │   ├── types.py
│   │   └── protocol.py
│   ├── commands.py                # 统一命令注册表（阶段3）
│   ├── agent.py                   # Agent 基类
│   ├── dag.py                     # DAG 引擎
│   ├── scheduler.py               # 调度器
│   ├── context.py                 # 数据传递
│   ├── monitor.py                 # 监控 Agent
│   ├── models.py                  # 数据模型（唯一 AgentConfig 定义）
│   ├── config.py                  # 配置管理（升级）
│   ├── mcp_client.py              # MCP 客户端（修复重复）
│   ├── tool_registry.py           # 工具注册表
│   ├── skills.py                  # Skills 系统
│   ├── session.py                 # 会话管理
│   ├── context_compressor.py      # 上下文压缩
│   ├── circuit_breaker.py         # 熔断器
│   ├── doom_loop.py               # 循环检测
│   ├── storage.py                 # 工作流存储
│   ├── db.py                      # 数据库
│   └── ...
│
├── tui/                           # CLI 层
│   ├── repl.py                    # (~300行) REPL 主循环
│   ├── layout.py                  # (~400行) prompt_toolkit 布局
│   ├── slash_commands.py          # (~500行) 斜杠命令定义+处理
│   ├── agent_integration.py       # (~300行) Agent Loop 集成
│   ├── stream_handler.py          # 流式输出渲染
│   ├── compat.py                  # 向后兼容层
│   ├── fallback.py                # 降级模式
│   ├── cli.py                     # Click CLI 入口
│   ├── display.py                 # Rich 格式化输出
│   ├── spinner.py                 # 加载动画
│   ├── themes.py                  # 主题系统
│   ├── status_bar.py              # 状态栏
│   ├── approval.py                # 审批系统
│   ├── editor.py                  # 工作流编辑器
│   ├── diff_renderer.py           # 差异渲染
│   ├── dangerous_commands.py      # 危险命令检测
│   ├── dsl_parser.py              # DSL v1
│   ├── dsl_parser_v2.py           # DSL v2
│   ├── templates.py               # 工作流模板
│   ├── monitor_panel.py           # 监控面板
│   └── commands/                  # CLI 子命令
│       ├── __init__.py
│       ├── init_cmd.py
│       ├── doctor_cmd.py
│       ├── model_cmd.py
│       └── plugin_cmd.py
│
├── server/                        # FastAPI 后端（后续）
├── gui/                           # Electron 前端（后续）
├── examples/                      # 示例工作流
└── tests/                         # 测试
```

---

## 五、重构后 REPL 功能清单

### 斜杠命令（参考 hermes + opencode）

| 命令 | 别名 | 功能 | 分类 |
|------|------|------|------|
| `/help` | `/h` | 显示帮助 | General |
| `/model` | `/mo` | 切换模型 | Configuration |
| `/models` | | 列出可用模型 | Configuration |
| `/provider` | | 切换 Provider | Configuration |
| `/config` | | 配置管理 | Configuration |
| `/new` | `/n`, `/reset` | 新建会话 | Session |
| `/resume` | `/continue` | 恢复会话 | Session |
| `/sessions` | | 会话列表 | Session |
| `/compact` | | 压缩上下文 | Session |
| `/undo` | | 撤销 | Edit |
| `/redo` | | 重做 | Edit |
| `/skills` | | 查看 Skills | Skills |
| `/mcp` | | MCP 管理 | MCP |
| `/theme` | | 切换主题 | Display |
| `/init` | | 初始化项目 | Project |
| `/doctor` | | 健康检查 | System |
| `/run` | | 执行工作流 | Workflow |
| `/list` | `/ls` | 工作流列表 | Workflow |
| `/history` | | 执行历史 | Workflow |
| `/templates` | | 模板管理 | Workflow |
| `/clear` | `/cls` | 清屏 | General |
| `/exit` | `/quit`, `/q` | 退出 | General |

---

## 六、执行顺序与依赖关系

```
阶段1 (拆分 repl.py)
  ↓
阶段2 (统一 LLM 层)  ←→  阶段3 (命令系统统一)  [可并行]
  ↓                         ↓
阶段4 (集成未使用模块)  ←────┘
  ↓
阶段5 (MCP + Skills)  ←→  阶段6 (配置升级)  [可并行]
  ↓
阶段7 (会话管理完善)
  ↓
测试 + 文档
```

**总预估时间**：11-12 天（含测试）

---

## 七、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 拆分 repl.py 引入回归 bug | 用户体验 | 每步拆分后运行完整测试 |
| LLM 层统一影响现有 provider | 功能退化 | 保留旧 API 兼容层 |
| 命令系统统一影响 CLI 行为 | 用户习惯 | 渐进式迁移，保留旧入口 |
| 集成模块相互冲突 | 稳定性 | 逐个集成，每次验证 |

---

## 八、验收标准

- [ ] `repl.py` 不超过 400 行
- [ ] 只有一套 LLM 调用系统
- [ ] 只有一个 `AgentConfig` 定义
- [ ] CLI 和 REPL 共享命令注册表
- [ ] `/mcp` 命令可查看 MCP 服务器状态
- [ ] `/skills` 命令可列出可用 Skills
- [ ] `/resume` 可恢复历史会话
- [ ] 5 个未集成模块全部接入
- [ ] 全部现有测试通过
- [ ] 新增模块有对应测试
