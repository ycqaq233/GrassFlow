# GrassFlow CLI 现状分析报告

> 分析日期：2026-06-26
> 范围：`tui/` 目录（20个文件，~5,800行）+ `core/` 目录（25个文件，~11,000行）

---

## 一、项目总体概况

### 文件规模

| 目录 | 文件数 | 代码行数 | 最大文件 |
|------|--------|---------|---------|
| `tui/` | 20 | ~5,800 | `repl.py` (2,183行) |
| `core/` | 25 | ~11,000 | `llm_protocol.py` (1,628行) |
| **合计** | **45** | **~16,800** | — |

### tui/ 文件职责矩阵

| 文件 | 行数 | 职责 | 状态 |
|------|------|------|------|
| `repl.py` | 2,183 | REPL 主循环、斜杠命令、消息渲染、Agent Loop 集成 | **过度膨胀** |
| `session.py` | 1,160 | 会话 SQLite 持久化、断点恢复 | 已实现，部分未集成 |
| `cli.py` | 1,141 | Click CLI 入口，20+ 命令 | 可用 |
| `agent_loop.py` | 1,043 | Agent 对话循环引擎（流式/非流式） | 可用 |
| `context_compressor.py` | 899 | Token 检测 + 摘要压缩 | 已实现未集成 |
| `display.py` | 923 | Rich 格式化输出（工具调用、通知、进度条） | 可用 |
| `stream_handler.py` | 771 | LLM 流式响应渲染、Markdown 渐进渲染 | 已实现未集成 |
| `editor.py` | 691 | Textual 交互式工作流编辑器 | 可用 |
| `spinner.py` | 560 | 加载动画（15种风格） | 可用 |
| `themes.py` | 572 | 主题/皮肤系统（6个内置主题） | 可用 |
| `diff_renderer.py` | 514 | 文件差异渲染器 | 可用 |
| `dsl_parser_v2.py` | 480 | DSL v2 解析器 | 可用 |
| `dsl_parser.py` | 457 | DSL v1 解析器 | 可用 |
| `status_bar.py` | 376 | 终端底部状态栏 | 可用 |
| `templates.py` | 360 | 5 个工作流模板 | 可用 |
| `approval.py` | 289 | 审批系统（NORMAL/YOLO/STRICT） | 可用 |
| `monitor_panel.py` | 291 | htop 风格实时监控面板 | 可用 |
| `dangerous_commands.py` | 157 | 危险命令检测（35条规则） | 可用 |
| `commands/` | 5个文件 | init/doctor/model/plugin 子命令 | 可用 |
| `__init__.py` | 96 | 模块导出 | 可用 |

---

## 二、repl.py 深度分析

### 2.1 职责过载

`repl.py` 是整个 TUI 层最大的文件（2,183行），承担了**至少 7 个不同职责**：

| 职责 | 估计行数 | 应独立为 |
|------|---------|---------|
| prompt_toolkit 布局/渲染 | ~400 | `tui/layout.py` |
| 斜杠命令系统（30+命令） | ~500 | `tui/slash_commands.py` |
| Agent Loop 集成（流式/非流式） | ~300 | `tui/agent_integration.py` |
| REPL 主循环（输入/输出/状态机） | ~300 | 保留在 `repl.py` |
| 主题/样式管理 | ~200 | 已有 `themes.py`，应迁移 |
| 向后兼容层（旧 API 包装） | ~200 | `tui/compat.py` |
| 降级模式（input() 回退） | ~100 | `tui/fallback.py` |

### 2.2 斜杠命令系统

当前实现了 **30+ 个斜杠命令**，全部硬编码在 `GrassFlowREPL` 类中：

```
/help, /h          — 帮助
/model, /models    — 模型管理
/new, /clear, /cls — 会话管理
/compact           — 上下文压缩
/sessions          — 会话列表
/init              — 项目初始化
/undo, /redo       — 撤销/重做
/exit, /quit, /q   — 退出
/theme             — 主题切换
/provider          — Provider 切换
/run               — 执行工作流
/list, /ls         — 工作流列表
/history           — 执行历史
/validate          — 验证工作流
/templates         — 模板管理
/config            — 配置管理
/stats, /status    — 统计信息
```

**问题**：
- 命令处理函数全部是 `GrassFlowREPL` 的方法，无法独立测试或扩展
- 没有命令注册机制，添加新命令需要修改 `handlers` 字典 + 添加方法
- 命令帮助文本硬编码在 `_cmd_help()` 中，与命令定义分离

### 2.3 向后兼容层

文件末尾有约 200 行的向后兼容代码，包括：
- `MessageRole`, `Message`, `CommandResult` 等旧数据类
- `CommandHandler`, `InputHandler`, `MessageRenderer` 等旧接口
- `REPL` 类（旧版包装器）

这些应该移到独立的 `tui/compat.py` 中。

---

## 三、命令系统分析

### 3.1 CLI 命令（cli.py）

基于 Click 框架，包含以下命令组：

| 命令 | 功能 | 状态 |
|------|------|------|
| `grassflow run` | 执行工作流 | 可用 |
| `grassflow save` | 保存工作流 | 可用 |
| `grassflow list` | 列出工作流 | 可用 |
| `grassflow validate` | 验证工作流 | 可用 |
| `grassflow history` | 执行历史 | 可用 |
| `grassflow inspect` | 执行详情 | 可用 |
| `grassflow delete` | 删除记录 | 可用 |
| `grassflow templates` | 模板列表 | 可用 |
| `grassflow create` | 从模板创建 | 可用 |
| `grassflow edit` | 交互式编辑器 | 可用 |
| `grassflow monitor` | 实时监控 | 可用 |
| `grassflow init` | 项目初始化 | 可用 |
| `grassflow doctor` | 健康检查 | 可用 |
| `grassflow models` | 模型列表 | 可用 |
| `grassflow plugin` | 插件管理 | 可用 |
| `grassflow config` | 配置管理（10个子命令） | 可用 |
| `grassflow repl` | 启动 REPL | 可用 |

### 3.2 REPL 斜杠命令

与 CLI 命令存在**大量功能重叠**：
- `/run` vs `grassflow run`
- `/list` vs `grassflow list`
- `/history` vs `grassflow history`
- `/validate` vs `grassflow validate`
- `/templates` vs `grassflow templates`
- `/config` vs `grassflow config`
- `/models` vs `grassflow models`
- `/init` vs `grassflow init`

**问题**：两套命令系统的实现完全独立，没有共享逻辑。

---

## 四、MCP 支持分析

### 4.1 当前实现

MCP（Model Context Protocol）支持分布在两个文件中：

| 文件 | 类 | 职责 |
|------|-----|------|
| `core/mcp_client.py` (1,019行) | `MCPClient`, `MCPManager`, `StdioTransport`, `HTTPTransport`, `SSETransport` | 底层 MCP 通信 |
| `core/tool_registry.py` (971行) | `MCPToolAdapter` | MCP 工具注册到 ToolRegistry |

### 4.2 实现程度

- **传输层**：支持 Stdio、HTTP、SSE 三种传输方式
- **工具发现**：支持从 MCP Server 获取工具列表
- **工具调用**：支持通过 MCP 协议调用远程工具
- **资源/提示词**：定义了 `MCPResource` 和 `MCPPrompt` 数据类，但未见实际使用

### 4.3 问题

1. **三种 Transport 的 `_initialize()` 方法几乎完全重复**，应抽取到基类
2. **`StdioTransport.send_request()` 使用已弃用的 `asyncio.get_event_loop()`**
3. **`register_mcp_tools()` 中使用 `asyncio.get_event_loop().run_until_complete()`**，在异步环境中嵌套同步调用可能导致死锁
4. **`SSETransport._connect_sse()` 没有超时机制**
5. **`mcp_client.py` 和 `tool_registry.py` 之间缺少清晰的分层文档**

---

## 五、Skills 系统分析

### 5.1 当前实现

`core/skills.py`（974行）实现了一个完整的 Skills 系统：

| 组件 | 功能 |
|------|------|
| `SkillInfo` | Skill 元信息（name, description, version, tags 等） |
| `SkillManager` | Skill 生命周期管理（发现、加载、查询、格式化） |
| `discover_skill_files()` | 从多个目录扫描 `.md` 文件 |
| `load_skill_file()` | 解析 frontmatter + 内容 |
| `_parse_yaml_simple()` | 自实现的简化 YAML 解析器 |

### 5.2 Skill 文件格式

```markdown
---
name: skill-name
description: 一句话描述
metadata:
  type: user | feedback | project | reference
---

Skill 内容...
```

### 5.3 搜索路径

```
~/.claude/skills/          — 全局 skills
<project>/.claude/skills/  — 项目 skills
```

### 5.4 问题

1. **自实现 YAML 解析器**：只支持基本键值对，不支持列表、嵌套映射等常见结构
2. **`DEFAULT_SEARCH_DIRS` 使用 `Path.cwd()`**：模块加载时就确定了搜索路径，工作目录改变后不会更新
3. **方法过多**：`SkillInfo` 和 `SkillManager` 各有 6 个格式化方法，代码量膨胀
4. **未与 REPL 集成**：REPL 中没有 `/skills` 命令，也没有在 Agent Loop 中加载 skills

---

## 六、Agent Loop 分析

### 6.1 架构

`agent_loop.py`（1,043行）实现了完整的 Agent 对话循环：

```
用户输入 → AgentLoop.process_streaming()
  → LLM API 调用（流式）
  → 解析响应（文本/工具调用/思考）
  → 工具调用 → ToolExecutor → 返回结果
  → 继续循环（直到无工具调用或达到最大迭代）
  → 输出事件流（LoopEvent）
```

### 6.2 事件类型

| 事件 | 用途 |
|------|------|
| `loop_start` / `loop_end` | 循环生命周期 |
| `text_delta` / `text_end` | 流式文本输出 |
| `thinking_delta` / `thinking_end` | 思考过程 |
| `tool_call_start` / `tool_call_end` | 工具调用 |
| `tool_result` | 工具执行结果 |
| `error` | 错误 |
| `interrupted` | 用户中断 |
| `usage` | Token 使用统计 |

### 6.3 问题

1. **`ToolExecutor` 与 `core/tool_registry.py` 的 `ToolRegistry` 职责重叠**
2. **最大迭代次数硬编码为 10**，应可配置
3. **没有集成 `core/doom_loop.py`**（循环检测）和 `core/circuit_breaker.py`（熔断器）
4. **没有集成 `core/context_compressor.py`**（上下文压缩）
5. **没有集成 `core/skills.py`**（Skill 加载）

---

## 七、配置管理分析

### 7.1 Provider 配置结构

`core/config.py`（423行）定义了多层配置：

```python
GrassFlowConfig
├── providers: Dict[str, ProviderConfig]
│   ├── name: str
│   ├── type: str  (openai/anthropic/deepseek/ollama/gemini/custom)
│   ├── options: ProviderOptions
│   │   ├── apiKey: str
│   │   ├── baseUrl: str
│   │   ├── apiVersion: str
│   │   └── defaultModel: str
│   └── models: List[ProviderModelConfig]
├── llm: LLMConfig
│   ├── defaultProvider: str
│   ├── defaultModel: str
│   ├── temperature: float
│   ├── maxTokens: int
│   ├── timeout: int
│   └── retryCount: int
├── workflow: WorkflowConfig
├── display: DisplayConfig
└── server: ServerConfig
```

### 7.2 问题

1. **`APIKeys` 类已废弃**：字段被 `ProviderConfig.options.apiKey` 替代，但仍保留在代码中
2. **环境变量只支持两级嵌套**：如 `GRASSFLOW_LLM_DEFAULT_MODEL`，不支持更深路径
3. **全局单例 `config_manager` 在模块加载时创建**：此时可能还没有确定 `project_dir`
4. **`set()` 方法不健壮**：中间层已存在非 dict 值时会报错

---

## 八、core/ 目录代码质量问题汇总

### 8.1 重复代码（严重）

| 问题 | 涉及文件 | 严重程度 |
|------|---------|---------|
| `AgentConfig` 类重复定义 | `models.py` vs `agent.py` | 高 |
| `Workflow` 类名冲突 | `models.py` vs `dsl_v2_ast.py` | 高 |
| `ComponentRegistry` 类名冲突 | `agent_component.py` vs `component_registry.py` | 高 |
| `LLMResponse` 类重复定义 | `llm.py` vs `llm_protocol.py` | 高 |
| 重试逻辑重复 | `agent.py` vs `scheduler.py` | 中 |
| 从 `_deps` 查找字段值的逻辑重复 | `condition.py` 中两个类 | 低 |
| MCP 初始化逻辑重复 | `mcp_client.py` 中三种 Transport | 中 |
| DAG 节点集合获取重复 | `dag.py` 中 5+ 处 | 低 |

### 8.2 职责不清（严重）

| 问题 | 涉及文件 |
|------|---------|
| 两套 LLM 调用系统并存 | `llm.py`（litellm封装） vs `llm_protocol.py`（自研协议层） |
| 两套 MCP 注册机制 | `mcp_client.py`（底层通信） vs `tool_registry.py`（注册表适配） |
| 两种 ComponentRegistry | `agent_component.py`（运行时注册） vs `component_registry.py`（文件系统发现） |
| Agent 执行链路不清 | `Agent.execute()` vs `Scheduler._execute_agent()` |

### 8.3 未集成模块

| 模块 | 行数 | 状态 |
|------|------|------|
| `circuit_breaker.py` | 433 | 已实现，无任何模块引用 |
| `doom_loop.py` | 492 | 已实现，无任何模块引用 |
| `context_compressor.py` | 899 | 已实现，REPL 中未集成 |
| `stream_handler.py` | 771 | 已实现，REPL 中未集成 |
| `session.py` | 1,160 | 已实现，REPL 中部分集成 |

### 8.4 全局单例过多（11+ 个）

```
core/llm.py:           llm_manager
core/llm_protocol.py:  protocol_manager
core/config.py:        config_manager
core/storage.py:       workflow_storage
core/db.py:            execution_db
core/monitor.py:       monitor (get_monitor())
core/llm_agent.py:     llm_agent_factory
core/tool_registry.py: _DECORATOR_REGISTRY
core/permission.py:    (module-level DEFAULT_RULESET)
core/circuit_breaker.py: (CircuitBreakerManager 全局实例)
core/doom_loop.py:     (DoomLoopManager 全局实例)
core/component_registry.py: (ComponentRegistry 全局实例)
```

### 8.5 文件过大

| 文件 | 行数 | 建议拆分 |
|------|------|---------|
| `llm_protocol.py` | 1,628 | → `protocol/` 子包（auth, transport, framing, model, provider） |
| `tool_registry.py` | 971 | → `tools/` 子包（registry, adapters, decorators, errors） |
| `skills.py` | 974 | → `skills/` 子包（manager, loader, formatter） |
| `component_registry.py` | 960 | → `components/` 子包（discovery, registry, dsl_generator） |
| `agent_component.py` | 875 | → `components/` 子包（agent, ports, workflow） |
| `error_classifier.py` | 723 | → `errors/` 子包（classifier, exceptions, retry） |

### 8.6 架构违规

- **`component_registry.py` 依赖 `tui.dsl_parser_v2`**：core 模块不应依赖上层 tui 模块
- **`scheduler.py` 直接访问 `context._data`**：破坏封装性
- **`scheduler.py` 调用 `agent.run()` 而非 `agent.execute()`**：跳过 Agent 自身的校验和重试逻辑

---

## 九、问题优先级排序

### P0 — 阻塞性问题（必须立即修复）

1. **`repl.py` 过度膨胀**：2,183行、7个职责，任何修改都有连锁风险
2. **两套 LLM 系统并存**：`llm.py` 和 `llm_protocol.py` 职责完全重叠，新开发者无法判断使用哪个
3. **`AgentConfig` 重复定义**：`models.py` 和 `agent.py` 各有一份，字段不一致

### P1 — 高优先级（影响开发效率）

4. **CLI 和 REPL 命令系统无共享逻辑**：8+ 个命令功能重叠但实现独立
5. **11+ 个全局单例**：增加耦合度，测试困难
6. **5 个已实现模块未集成**：circuit_breaker、doom_loop、context_compressor、stream_handler、session
7. **core 依赖 tui**：`component_registry.py` 反向依赖违反分层原则

### P2 — 中优先级（代码质量）

8. **6 个文件超过 800 行**：需要拆分
9. **MCP 传输层代码重复**：三种 Transport 的初始化逻辑几乎相同
10. **DAG 节点集合获取重复 5+ 次**：应缓存
11. **`scheduler.py` 跳过 Agent 的 `execute()` 方法**：Agent 基类的校验和重试形同虚设

### P3 — 低优先级（改进项）

12. **自实现 YAML 解析器**：功能有限，应使用 PyYAML
13. **`asyncio.get_event_loop()` 已弃用**：多处使用，应改为 `get_running_loop()`
14. **Monitor 的 schema 检查过于简单**：未对照 output_schema 验证
15. **DSL 验证使用正则而非解析器**：不可靠

---

## 十、重构建议概览

### 10.1 repl.py 拆分方案

```
tui/
├── repl.py              (~300行) REPL 主循环、状态机
├── layout.py            (~400行) prompt_toolkit 布局/渲染
├── slash_commands.py    (~500行) 斜杠命令注册/执行/帮助
├── agent_integration.py (~300行) Agent Loop 集成
├── compat.py            (~200行) 向后兼容层
└── fallback.py          (~100行) 降级模式
```

### 10.2 LLM 层统一方案

```
core/
├── llm/
│   ├── __init__.py      统一导出
│   ├── client.py        LLMClient（统一接口）
│   ├── providers/       各 Provider 实现
│   │   ├── openai.py
│   │   ├── anthropic.py
│   │   └── ...
│   ├── protocol.py      协议层（从 llm_protocol.py 拆分）
│   └── types.py         统一类型定义
```

### 10.3 命令系统统一方案

```python
# 统一命令注册
class CommandRegistry:
    commands: Dict[str, Command]

    def register(self, name, handler, help_text, args_schema):
        ...

    def execute(self, name, args):
        ...

# CLI 和 REPL 共享同一个 CommandRegistry
# CLI: registry.execute("run", args)
# REPL: registry.execute("run", args)
```

---

## 附录：文件行数统计

### tui/ 目录

| 文件 | 行数 |
|------|------|
| repl.py | 2,183 |
| session.py | 1,160 |
| cli.py | 1,141 |
| agent_loop.py | 1,043 |
| display.py | 923 |
| context_compressor.py | 899 |
| stream_handler.py | 771 |
| editor.py | 691 |
| themes.py | 572 |
| spinner.py | 560 |
| diff_renderer.py | 514 |
| dsl_parser_v2.py | 480 |
| dsl_parser.py | 457 |
| status_bar.py | 376 |
| templates.py | 360 |
| approval.py | 289 |
| monitor_panel.py | 291 |
| dangerous_commands.py | 157 |
| __init__.py | 96 |
| commands/ (5个文件) | ~1,158 |
| **合计** | **~13,000+** |

### core/ 目录

| 文件 | 行数 |
|------|------|
| llm_protocol.py | 1,628 |
| tool_registry.py | 971 |
| skills.py | 974 |
| component_registry.py | 960 |
| agent_component.py | 875 |
| error_classifier.py | 723 |
| workflow_generator.py | 563 |
| permission.py | 543 |
| doom_loop.py | 492 |
| circuit_breaker.py | 433 |
| config.py | 423 |
| dag.py | 318 |
| scheduler.py | 257 |
| mcp_client.py | 1,019 |
| monitor.py | 231 |
| llm_agent.py | 233 |
| llm.py | 203 |
| db.py | 253 |
| models.py | 145 |
| condition.py | 149 |
| storage.py | 143 |
| agent.py | 124 |
| dsl_v2_ast.py | 97 |
| context.py | 72 |
| __init__.py | 295 |
| **合计** | **~11,000+** |
