# Hermes Agent TUI/CLI 源码分析报告

## 1. 项目概览

Hermes Agent 是一个功能完整的 AI Agent 框架，包含 CLI、TUI、Gateway 等多种前端。项目规模庞大（2551 个 Python 文件），核心功能包括：

- 交互式 REPL 界面
- 多模型支持（OpenAI、Anthropic、Gemini 等）
- 工具系统（文件操作、终端、浏览器、MCP 等）
- 会话管理和持久化
- 权限控制和安全审计
- 主题/皮肤系统

---

## 2. CLI 入口和命令系统

### 2.1 入口文件结构

```
hermes_cli/main.py          # 主入口，argparse 命令分发
hermes_cli/_parser.py       # 顶层 parser 构建
hermes_cli/subcommands/     # 子命令模块化
cli.py                      # REPL 核心实现（HermesCLI 类）
```

### 2.2 命令分发机制

```python
# main.py 中的命令分发
def main():
    parser, subparsers, chat_parser = build_top_level_parser()
    chat_parser.set_defaults(func=cmd_chat)

    # 注册子命令
    build_model_parser(subparsers, cmd_model=cmd_model)
    build_gateway_parser(subparsers, cmd_gateway=cmd_gateway)
    build_setup_parser(subparsers, cmd_setup=cmd_setup)
    # ... 更多子命令

    args = parser.parse_args()
    args.func(args)
```

### 2.3 GrassFlow 可借鉴点

**直接可用**：
- 子命令模块化模式（`subcommands/` 目录结构）
- argparse 的分层构建模式
- Profile 覆盖机制（`--profile` 参数预解析）

---

## 3. REPL 实现

### 3.1 核心架构

Hermes 使用 `prompt_toolkit` 实现 REPL，核心类为 `HermesCLI`（cli.py:3358）：

```python
class HermesCLI(CLIAgentSetupMixin, CLICommandsMixin):
    """Interactive CLI for the Hermes Agent."""

    def __init__(self, model=None, toolsets=None, provider=None, ...):
        self.console = Console()  # Rich console
        self.config = CLI_CONFIG
        # ... 配置初始化

    def run(self):
        """Run the interactive CLI loop with persistent input at bottom."""
        # 1. 显示 banner
        self.show_banner()

        # 2. 创建 key bindings
        kb = KeyBindings()

        @kb.add('enter')
        def handle_enter(event):
            # 路由到正确的队列
            if self._sudo_state:
                # 处理 sudo 密码
            elif self._approval_state:
                # 处理审批选择
            elif self._agent_running:
                # 中断队列
            else:
                # 正常输入队列

        # 3. 创建 prompt_toolkit 应用
        app = Application(
            layout=layout,
            key_bindings=kb,
            style=style,
        )
        app.run()
```

### 3.2 输入处理机制

```python
# 异步状态管理
self._agent_running = False
self._pending_input = queue.Queue()     # 正常输入
self._interrupt_queue = queue.Queue()   # 中断消息
self._should_exit = False

# 模式切换
self.busy_input_mode = "interrupt"  # interrupt / queue / steer
```

### 3.3 命令系统

```python
# 斜杠命令处理
def process_command(self, text: str) -> bool:
    if text.startswith("/"):
        cmd = text.split()[0].lower()
        if cmd == "/help":
            self._show_help()
        elif cmd == "/model":
            self._handle_model_switch()
        elif cmd == "/resume":
            self._handle_resume()
        # ... 更多命令
```

### 3.4 GrassFlow 可借鉴点

**直接可用**：
- `prompt_toolkit` 的使用模式（KeyBindings、Application）
- 异步输入队列机制（`_pending_input`、`_interrupt_queue`）
- 忙碌模式切换（interrupt / queue / steer）
- 斜杠命令处理框架

**需要适配**：
- GrassFlow 已有 `tui/repl.py`，可参考 Hermes 的队列机制增强中断处理
- 可引入 `prompt_toolkit` 替代当前的 `input()` 循环

---

## 4. Agent Loop 实现

### 4.1 核心循环

`agent/conversation_loop.py` 实现了核心对话循环：

```python
def run_conversation(
    agent,
    user_message: str,
    system_message: str = None,
    conversation_history: List[Dict] = None,
    task_id: str = None,
    stream_callback: Optional[callable] = None,
) -> Dict[str, Any]:
    """Run a complete conversation with tool calling until completion."""

    # 初始化上下文
    _ctx = build_turn_context(agent, user_message, ...)

    # 主循环
    while (api_call_count < agent.max_iterations
           and agent.iteration_budget.remaining > 0):

        # 检查中断
        if agent._interrupt_requested:
            interrupted = True
            break

        # API 调用
        api_call_count += 1
        response = agent._call_api(messages)

        # 处理工具调用
        if response.tool_calls:
            results = agent._execute_tool_calls(response.tool_calls)
            messages.extend(results)
        else:
            # 最终响应
            final_response = response.content
            break

    return {
        "response": final_response,
        "messages": messages,
        "api_calls": api_call_count,
    }
```

### 4.2 工具执行

`agent/tool_executor.py` 实现了工具执行：

```python
def _execute_tool_calls_concurrent(agent, tool_calls, ...):
    """并发执行工具调用"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_TOOL_WORKERS) as executor:
        futures = {}
        for tc in tool_calls:
            future = executor.submit(
                _execute_single_tool,
                agent, tc.function.name, tc.function.arguments, ...
            )
            futures[future] = tc

        results = []
        for future in concurrent.futures.as_completed(futures):
            tc = futures[future]
            try:
                result = future.result(timeout=timeout)
                results.append(make_tool_result_message(tc, result))
            except Exception as e:
                results.append(make_tool_result_message(tc, str(e), is_error=True))

    return results
```

### 4.3 GrassFlow 可借鉴点

**直接可用**：
- 工具调用循环结构
- 并发工具执行模式（ThreadPoolExecutor）
- 中断检查机制
- 迭代预算控制（IterationBudget）

**需要适配**：
- GrassFlow 的 DAG 调度与 Hermes 的线性循环不同
- 可参考 Hermes 的工具执行模式增强 GrassFlow 的 Agent 执行

---

## 5. 会话管理

### 5.1 SQLite 存储

`hermes_state.py` 实现了 SQLite 会话存储：

```python
class SessionDB:
    """SQLite-backed session storage with FTS5 search."""

    def __init__(self, db_path=None, read_only=False):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._conn = sqlite3.connect(str(self.db_path), ...)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """创建表结构"""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL DEFAULT 'cli',
                title TEXT NOT NULL DEFAULT '',
                parent_session_id TEXT,
                model_config TEXT DEFAULT '{}',
                started_at TEXT NOT NULL,
                ended_at TEXT,
                end_reason TEXT,
                message_count INTEGER DEFAULT 0,
                ...
            )
        """)

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                tool_call_id TEXT,
                tool_calls TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)

        # FTS5 全文搜索
        self._conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
            USING fts5(content, content=messages, content_rowid=id)
        """)
```

### 5.2 会话恢复

```python
def resume_session(self, session_id: str) -> Optional[Dict]:
    """恢复会话"""
    session = self.get_session(session_id)
    if not session:
        return None

    messages = self.get_messages(session_id)
    return {
        "session": session,
        "messages": messages,
    }
```

### 5.3 GrassFlow 可借鉴点

**直接可用**：
- SQLite 表结构设计
- FTS5 全文搜索集成
- 会话恢复机制
- WAL 模式和并发处理

**已实现**：
- GrassFlow 的 `tui/session.py` 已有类似实现
- 可参考 Hermes 的 FTS5 集成增强搜索功能

---

## 6. 流式输出

### 6.1 流式回调机制

```python
# agent_init.py 中的回调注册
class AIAgent:
    def __init__(self, ...,
                 stream_delta_callback: callable = None,
                 thinking_callback: callable = None,
                 reasoning_callback: callable = None, ...):
        self.stream_delta_callback = stream_delta_callback
        self.thinking_callback = thinking_callback
        self.reasoning_callback = reasoning_callback

# conversation_loop.py 中的流式处理
for chunk in response:
    if chunk.choices[0].delta.content:
        token = chunk.choices[0].delta.content
        if agent.stream_delta_callback:
            agent.stream_delta_callback(token)
```

### 6.2 显示渲染

```python
# agent/display.py 中的 KawaiiSpinner
class KawaiiSpinner:
    """Animated spinner with kawaii faces."""

    def __init__(self, ...):
        self.faces = ["(◕‿◕)", "(◕ᴗ◕✿)", "(◠‿◠)", ...]
        self.current_face = 0

    def spin(self):
        """显示动画 spinner"""
        face = self.faces[self.current_face % len(self.faces)]
        self.current_face += 1
        return face
```

### 6.3 GrassFlow 可借鉴点

**直接可用**：
- 流式回调机制（`stream_delta_callback`）
- 动画 spinner 实现
- 实时 token 渲染

**已实现**：
- GrassFlow 的 `tui/stream_handler.py` 已有流式处理
- 可参考 Hermes 的回调机制增强灵活性

---

## 7. 工具系统

### 7.1 工具注册表

`tools/registry.py` 实现了工具注册表：

```python
class ToolRegistry:
    """Singleton registry that collects tool schemas + handlers."""

    def __init__(self):
        self._tools: Dict[str, ToolEntry] = {}
        self._toolset_checks: Dict[str, Callable] = {}
        self._lock = threading.RLock()

    def register(self, name, toolset, schema, handler, check_fn=None, ...):
        """注册工具"""
        self._tools[name] = ToolEntry(
            name=name,
            toolset=toolset,
            schema=schema,
            handler=handler,
            check_fn=check_fn,
            ...
        )

    def get_definitions(self, enabled_toolsets=None, disabled_toolsets=None):
        """获取工具定义（用于 LLM）"""
        definitions = []
        for entry in self._tools.values():
            if self._is_tool_available(entry, enabled_toolsets, disabled_toolsets):
                definitions.append({
                    "type": "function",
                    "function": {
                        "name": entry.name,
                        "description": entry.description,
                        "parameters": entry.schema,
                    }
                })
        return definitions
```

### 7.2 工具自注册

```python
# tools/file_tools.py 中的自注册
from tools.registry import registry

registry.register(
    name="read_file",
    toolset="file-ops",
    schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to read"},
            "offset": {"type": "integer", "description": "Start line"},
            "limit": {"type": "integer", "description": "Max lines"},
        },
        "required": ["path"],
    },
    handler=read_file_handler,
    check_fn=lambda: True,
    description="Read file contents",
    emoji="📄",
)
```

### 7.3 工具集（Toolset）

```python
# toolsets.py 中的工具集定义
TOOLSETS = {
    "hermes-cli": {
        "description": "Core CLI tools",
        "tools": ["read_file", "write_file", "terminal", "search_files", ...],
    },
    "web": {
        "description": "Web tools",
        "tools": ["web_search", "web_extract", "browser_navigate", ...],
    },
    "coding": {
        "description": "Coding tools",
        "tools": ["read_file", "write_file", "terminal", "search_files", ...],
    },
}
```

### 7.4 GrassFlow 可借鉴点

**直接可用**：
- 工具注册表模式（单例 + 自注册）
- 工具集分组机制
- 工具可用性检查（`check_fn`）
- 工具 Schema 定义格式

**已实现**：
- GrassFlow 的 `core/tool_registry.py` 已有类似实现
- 可参考 Hermes 的工具集分组机制

---

## 8. 显示系统

### 8.1 皮肤/主题系统

`hermes_cli/skin_engine.py` 实现了主题系统：

```python
@dataclass
class SkinConfig:
    """Complete skin configuration."""
    name: str
    description: str = ""
    colors: Dict[str, str] = field(default_factory=dict)
    spinner: Dict[str, Any] = field(default_factory=dict)
    branding: Dict[str, str] = field(default_factory=dict)
    tool_prefix: str = "┊"
    tool_emojis: Dict[str, str] = field(default_factory=dict)

# 内置主题
_BUILTIN_SKINS = {
    "default": {
        "name": "default",
        "description": "Classic Hermes — gold and kawaii",
        "colors": {
            "banner_border": "#CD7F32",
            "banner_title": "#FFD700",
            "ui_accent": "#FFBF00",
            "ui_ok": "#4caf50",
            "ui_error": "#ef5350",
            ...
        },
        "branding": {
            "agent_name": "Hermes Agent",
            "welcome": "Welcome to Hermes Agent!",
            "prompt_symbol": "❯",
            ...
        },
    },
    "ares": { ... },
    "mono": { ... },
    "slate": { ... },
}
```

### 8.2 Diff 显示

```python
# agent/display.py 中的 diff 渲染
def render_inline_diff(before: str, after: str, path: str) -> str:
    """渲染内联 diff"""
    diff = unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )

    lines = []
    for line in diff:
        if line.startswith("+"):
            lines.append(f"{_diff_plus()}{line}{_ANSI_RESET}")
        elif line.startswith("-"):
            lines.append(f"{_diff_minus()}{line}{_ANSI_RESET}")
        elif line.startswith("@@"):
            lines.append(f"{_diff_hunk()}{line}{_ANSI_RESET}")
        else:
            lines.append(line)

    return "\n".join(lines)
```

### 8.3 GrassFlow 可借鉴点

**直接可用**：
- YAML 定义的皮肤配置
- 内置主题系统
- Diff 渲染（统一 diff 格式）
- 颜色系统（ANSI 256 色 / True Color）

**需要适配**：
- GrassFlow 使用 Rich 库，可参考 Hermes 的皮肤配置格式
- 可添加 Diff 显示功能

---

## 9. 快捷键系统

### 9.1 Key Bindings

```python
# cli.py 中的快捷键定义
kb = KeyBindings()

@kb.add('enter')
def handle_enter(event):
    """处理回车键"""
    # 路由到正确的处理器
    ...

@kb.add('ctrl-c')
def handle_ctrl_c(event):
    """处理 Ctrl+C"""
    if self._agent_running:
        self._interrupt_requested = True
    else:
        self._should_exit = True

@kb.add('ctrl-d')
def handle_ctrl_d(event):
    """处理 Ctrl+D（EOF）"""
    self._should_exit = True

# prompt_toolkit 的 Keys 枚举
from prompt_toolkit.keys import Keys

@kb.add(Keys.Ignore, eager=True)
def handle_ignored_terminal_sequence(event):
    """处理终端序列"""
    return None
```

### 9.2 GrassFlow 可借鉴点

**直接可用**：
- `prompt_toolkit` 的 KeyBindings 使用模式
- 中断处理（Ctrl+C）
- EOF 处理（Ctrl+D）

---

## 10. 权限系统

### 10.1 危险命令检测

`tools/approval.py` 实现了权限系统：

```python
# 危险命令模式
DANGEROUS_PATTERNS = [
    (r'\brm\s+(-[^\s]*\s+)*/', "delete in root path"),
    (r'\brm\s+-[^\s]*r', "recursive delete"),
    (r'\bchmod\s+(-[^\s]*\s+)*(777|666)', "world-writable permissions"),
    (r'\bDROP\s+(TABLE|DATABASE)\b', "SQL DROP"),
    (r'\bDELETE\s+FROM\b(?![^\n]*\bWHERE\b)', "SQL DELETE without WHERE"),
    ...
]

# 硬性阻止列表（即使 YOLO 模式也不允许）
HARDLINE_PATTERNS = [
    (r'\brm\s+(-[^\s]*\s+)*(/|/\*|/ \*)(\s|$)', "recursive delete of root"),
    (r'\bmkfs(\.[a-z0-9]+)?\b', "format filesystem"),
    (r'\bkill\s+(-[^\s]+\s+)*-1\b', "kill all processes"),
    (r'(_CMDPOS + r'(shutdown|reboot|halt|poweroff)\b', "system shutdown"),
    ...
]

def detect_dangerous_command(command: str) -> tuple:
    """检测危险命令"""
    normalized = _normalize_command_for_detection(command)
    for pattern, description in DANGEROUS_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return (True, description)
    return (False, None)
```

### 10.2 审批流程

```python
def request_approval(command: str, description: str, ...) -> dict:
    """请求用户审批"""
    # 1. 检查硬性阻止
    is_hardline, hardline_desc = detect_hardline_command(command)
    if is_hardline:
        return {"approved": False, "hardline": True, "message": ...}

    # 2. 检查 YOLO 模式
    if _YOLO_MODE_FROZEN:
        return {"approved": True}

    # 3. 检查永久允许列表
    if _is_permanently_allowed(command):
        return {"approved": True}

    # 4. 请求用户审批
    return _request_interactive_approval(command, description, ...)
```

### 10.3 GrassFlow 可借鉴点

**直接可用**：
- 危险命令模式匹配
- 硬性阻止列表
- 审批流程框架
- YOLO 模式

**已实现**：
- GrassFlow 的 `core/permission.py` 已有权限系统
- 可参考 Hermes 的危险命令检测增强安全性

---

## 11. 错误处理

### 11.1 错误分类

`agent/error_classifier.py` 实现了错误分类：

```python
class FailoverReason(enum.Enum):
    """API 错误分类"""
    auth = "auth"                        # 认证错误
    auth_permanent = "auth_permanent"    # 永久认证错误
    billing = "billing"                  # 计费/配额
    rate_limit = "rate_limit"            # 速率限制
    overloaded = "overloaded"            # 服务器过载
    server_error = "server_error"        # 服务器错误
    timeout = "timeout"                  # 超时
    context_overflow = "context_overflow"  # 上下文溢出
    model_not_found = "model_not_found"  # 模型未找到
    ...

def classify_api_error(exc: Exception, provider: str, ...) -> ClassifiedError:
    """分类 API 错误"""
    # 1. 检查状态码
    status_code = getattr(exc, 'status_code', None)
    if status_code == 401:
        return ClassifiedError(reason=FailoverReason.auth, ...)
    if status_code == 429:
        return ClassifiedError(reason=FailoverReason.rate_limit, ...)
    if status_code == 503:
        return ClassifiedError(reason=FailoverReason.overloaded, ...)

    # 2. 检查错误消息
    message = str(exc).lower()
    for pattern in _BILLING_PATTERNS:
        if pattern in message:
            return ClassifiedError(reason=FailoverReason.billing, ...)

    # 3. 默认分类
    return ClassifiedError(reason=FailoverReason.unknown, ...)
```

### 11.2 恢复策略

```python
def get_recovery_action(classified: ClassifiedError) -> str:
    """获取恢复策略"""
    if classified.should_compress:
        return "compress_context"
    if classified.should_rotate_credential:
        return "rotate_credential"
    if classified.should_fallback:
        return "fallback_provider"
    if classified.retryable:
        return "retry"
    return "abort"
```

### 11.3 GrassFlow 可借鉴点

**直接可用**：
- 错误分类枚举
- 模式匹配分类逻辑
- 恢复策略决策

**已实现**：
- GrassFlow 的 `core/error_classifier.py` 已有错误分类
- 可参考 Hermes 的恢复策略机制

---

## 12. 可直接搬过来用的代码

### 12.1 高优先级（核心功能）

| 模块 | 文件 | 说明 |
|------|------|------|
| 工具注册表 | `tools/registry.py` | 单例 + 自注册模式，可直接移植 |
| 工具集定义 | `toolsets.py` | 工具分组机制 |
| 危险命令检测 | `tools/approval.py` | 模式匹配 + 硬性阻止列表 |
| 错误分类 | `agent/error_classifier.py` | 错误枚举 + 分类逻辑 |
| 会话存储 | `hermes_state.py` | SQLite + FTS5 设计 |

### 12.2 中优先级（增强功能）

| 模块 | 文件 | 说明 |
|------|------|------|
| 主题系统 | `hermes_cli/skin_engine.py` | YAML 皮肤配置 |
| Diff 显示 | `agent/display.py` | 统一 diff 渲染 |
| 动画 Spinner | `agent/display.py` | KawaiiSpinner |
| 快捷键系统 | `cli.py` | prompt_toolkit KeyBindings |
| 流式回调 | `agent/agent_init.py` | stream_delta_callback 模式 |

### 12.3 低优先级（参考设计）

| 模块 | 文件 | 说明 |
|------|------|------|
| REPL 框架 | `cli.py` | HermesCLI 类结构 |
| 命令分发 | `hermes_cli/main.py` | argparse 分层构建 |
| 会话恢复 | `hermes_state.py` | resume_session 机制 |
| 并发工具执行 | `agent/tool_executor.py` | ThreadPoolExecutor 模式 |

---

## 13. GrassFlow 现有实现对比

### 13.1 已实现模块

| 功能 | GrassFlow 实现 | Hermes 实现 | 差距 |
|------|---------------|-------------|------|
| REPL | `tui/repl.py` | `cli.py` | 缺少 prompt_toolkit 集成 |
| 会话管理 | `tui/session.py` | `hermes_state.py` | 缺少 FTS5 搜索 |
| 工具注册表 | `core/tool_registry.py` | `tools/registry.py` | 设计相似，可参考增强 |
| 权限系统 | `core/permission.py` | `tools/approval.py` | 缺少危险命令检测 |
| 流式输出 | `tui/stream_handler.py` | `agent/display.py` | 基本功能已有 |
| 错误分类 | `core/error_classifier.py` | `agent/error_classifier.py` | 设计相似 |

### 13.2 缺失模块

| 功能 | 说明 | 优先级 |
|------|------|--------|
| 主题/皮肤系统 | YAML 定义的可配置主题 | 中 |
| Diff 显示 | 文件修改的内联 diff | 中 |
| 工具集分组 | 按场景分组的工具集 | 高 |
| 危险命令检测 | 基于模式匹配的安全检查 | 高 |
| FTS5 全文搜索 | 会话内容搜索 | 中 |
| 动画 Spinner | 终端动画效果 | 低 |

---

## 14. 建议的移植路径

### 14.1 第一阶段：核心增强（1-2 天）

1. **危险命令检测**：从 `tools/approval.py` 提取模式匹配逻辑
2. **工具集分组**：参考 `toolsets.py` 实现工具分组
3. **FTS5 搜索**：在 `tui/session.py` 中添加 FTS5 支持

### 14.2 第二阶段：UI 增强（2-3 天）

1. **主题系统**：参考 `skin_engine.py` 实现 YAML 皮肤配置
2. **Diff 显示**：从 `agent/display.py` 提取 diff 渲染逻辑
3. **prompt_toolkit 集成**：增强 REPL 的输入处理

### 14.3 第三阶段：高级功能（3-5 天）

1. **并发工具执行**：参考 `tool_executor.py` 实现并行执行
2. **流式回调机制**：增强 `stream_handler.py` 的回调支持
3. **会话恢复**：增强 `session.py` 的恢复机制

---

## 15. 总结

Hermes Agent 是一个功能完善的 AI Agent 框架，其 TUI/CLI 实现具有以下特点：

1. **模块化设计**：工具、命令、主题等都是独立模块
2. **注册表模式**：工具、皮肤等使用注册表统一管理
3. **回调机制**：流式输出、工具执行等使用回调解耦
4. **安全优先**：危险命令检测、硬性阻止列表等安全机制
5. **可配置性**：YAML 配置文件、皮肤系统等

GrassFlow 可以借鉴 Hermes 的设计模式，特别是：
- 工具注册表和工具集分组
- 危险命令检测和权限系统
- 主题/皮肤系统
- prompt_toolkit 集成

这些功能可以直接移植或参考实现，加速 GrassFlow 的开发进程。
