export const meta = {
  name: 'grassflow-cli-enhancement',
  description: 'GrassFlow CLI 大规模增强: 思考模式 + 命令扩展 + MCP集成 + Skills/AGENTS.md',
  phases: [
    { title: '实现', detail: '4个agent并行实现4大功能模块' },
    { title: '验证', detail: '测试和代码审查' },
  ],
}

const results = await parallel([
  // Agent 1: Thinking 模式 + /think 命令 + 扩展 slash commands
  () => agent(`
你是一个 Python 开发者，负责增强 GrassFlow TUI 的 slash commands 和 thinking 模式。

--- 任务 1: 实现 /think 命令（思考模式切换） ---

参考 hermes 的推理力度系统：
- hermes 有 5 个推理力度级别：minimal, low, medium, high, xhigh
- hermes 的 /reasoning 命令支持子命令：none/minimal/low/medium/high/xhigh/show/hide
- hermes 在 agent/anthropic_adapter.py 中实现了两种 thinking 模式：
  - Adaptive Thinking (Claude 4.6+): type=adaptive, display=summarized
  - Manual Budget (旧版): type=enabled, budget_tokens=N

请在 E:/opencode-desktop/GrassFlow/tui/slash_commands.py 中：

1. 在 COMMAND_REGISTRY 中添加 /think 命令：
   - name="think", category="Configuration"
   - description="Toggle/set thinking mode (on/off/low/medium/high/xhigh)"
   - handler: _cmd_think

2. 实现 _cmd_think(repl_instance, args) 函数：
   - 无参数：显示当前 thinking 状态（从 session.metadata["thinking"] 读取）
   - "on"：设置 thinking enabled=True, effort="medium"
   - "off"：设置 thinking enabled=False
   - "low"/"medium"/"high"/"xhigh"：设置对应 effort 并 enabled=True
   - "show"：显示详细配置
   - 修改 session.metadata["thinking"] = {"enabled": True/False, "effort": "xxx"}
   - 通过 repl_instance.add_output() 输出确认信息

3. 更新 SlashCommandCompleter：
   - 删除硬编码的 COMMANDS 字典
   - 从 COMMAND_REGISTRY 动态获取命令列表做补全
   - 为 /think 添加参数补全：on, off, low, medium, high, xhigh, show
   - 为 /model 添加模型名参数补全（从 config 读取）

--- 任务 2: 添加新 slash commands ---

在 COMMAND_REGISTRY 中添加以下命令（每个都是一个 CommandDef + handler 函数）：

命令 /resume, 别名 ["sessions"], 类别 Session, 说明 "恢复历史会话"
  -> 调用 _cmd_sessions（复用已有逻辑）

命令 /retry, 别名 [], 类别 Session, 说明 "重试上一条消息"
  -> 从 repl 获取最后一条用户消息，重新发送给 agent

命令 /fork, 别名 ["branch"], 类别 Session, 说明 "分叉当前会话"
  -> 显示 "Fork not yet implemented" 提示

命令 /title, 别名 [], 类别 Session, 说明 "设置会话标题"
  -> 设置 session.title，无参数显示当前标题

命令 /agent, 别名 [], 类别 Configuration, 说明 "切换/列出 Agent"
  -> 显示当前 agent 信息

命令 /mcp, 别名 [], 类别 Configuration, 说明 "MCP 服务器管理"
  -> 显示 MCP 状态（骨架实现）

命令 /skills, 别名 [], 类别 Info, 说明 "浏览技能列表"
  -> 显示可用技能（骨架实现）

命令 /copy, 别名 [], 类别 Info, 说明 "复制最后助手回复"
  -> 用 pyperclip 或 subprocess 复制到剪贴板

命令 /usage, 别名 [], 类别 Info, 说明 "显示 token 用量"
  -> 增强版 stats

命令 /version, 别名 ["v"], 类别 Info, 说明 "显示版本信息"
  -> 读取并显示版本号

命令 /connect, 别名 [], 类别 Configuration, 说明 "连接 Provider"
  -> 配置 API key 的骨架

命令 /yolo, 别名 [], 类别 Configuration, 说明 "切换 YOLO 模式"
  -> 切换 permission 设置

--- 参考文件 ---
- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_constants.py (parse_reasoning_effort 第551行)
- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/commands.py (COMMAND_REGISTRY)
- E:/opencode-desktop/GrassFlow/tui/slash_commands.py (当前实现，约777行)

--- 约束 ---
- 只修改 E:/opencode-desktop/GrassFlow/tui/slash_commands.py
- 保持现有 21 个命令不变，只添加新命令和修改补全器
- handler 函数签名：handler(repl_instance, args) -> None
- 代码风格与现有代码一致（中文注释，from __future__ import annotations）
- 不要删除任何现有代码，只添加和修改
`, {label: 'commands+thinking', phase: '实现', model: 'sonnet'}),

  // Agent 2: MCP 集成
  () => agent(`
你是一个 Python 开发者，负责将 MCP 客户端集成到 GrassFlow REPL。

创建文件 E:/opencode-desktop/GrassFlow/tui/mcp_integration.py

参考 hermes 的 MCP 实现（tools/mcp_tool.py 约2500行，hermes_cli/mcp_config.py，hermes_cli/mcp_startup.py）。

hermes 的 MCP 架构要点：
1. 配置格式存在 config.yaml 的 mcp_servers 键下
2. 支持 stdio / HTTP / SSE 三种传输
3. 每个服务器一个长生命周期 asyncio Task
4. 自动重连（指数退避，最多 5 次）
5. 动态工具发现（监听 notifications/tools/list_changed）
6. 工具注册到 ToolRegistry

请实现以下类和函数：

MCPServerConfig(dataclass):
  - name: str
  - command: Optional[str] (stdio 传输)
  - args: List[str]
  - env: Dict[str, str]
  - cwd: Optional[str]
  - url: Optional[str] (HTTP/SSE 传输)
  - headers: Dict[str, str]
  - transport: str = "stdio" (stdio/http/sse)
  - timeout: int = 120
  - connect_timeout: int = 60
  - keepalive_interval: int = 10
  - enabled: bool = True
  - tools_include: Optional[List[str]]
  - tools_exclude: Optional[List[str]]

MCPTool(dataclass):
  - name: str (格式: mcp_{server}_{tool})
  - server_name: str
  - description: str
  - input_schema: Dict[str, Any]
  - enabled: bool = True

MCPManager:
  - __init__(config_dir: Optional[Path])
  - load_config(config: Dict) -> None (从配置字典加载 mcp_servers)
  - start_all() -> None (启动所有启用的服务器)
  - stop_all() -> None (停止所有服务器)
  - _start_server(name, config) -> None
  - _start_stdio_server(name, config) -> None (asyncio.create_subprocess_exec)
  - _start_http_server(name, config) -> None (骨架)
  - _discover_tools(name, process, config) -> None (JSON-RPC tools/list)
  - call_tool(tool_name, arguments) -> Any (JSON-RPC tools/call)
  - get_tools_summary() -> str (用于 /mcp 命令)
  - _send_message(process, message) -> None
  - _read_message(process, timeout) -> Optional[Dict]
  - _stop_server(name) -> None

JSON-RPC 2.0 协议：
  - initialize: method="initialize", params={protocolVersion:"2024-11-05", capabilities:{}, clientInfo:{name:"GrassFlow", version:"0.1.0"}}
  - initialized: method="notifications/initialized"
  - list_tools: method="tools/list"
  - call_tool: method="tools/call", params={name:"tool_name", arguments:{...}}

同时修改 E:/opencode-desktop/GrassFlow/core/config.py，在 GrassFlowConfig 类中添加:
  mcp_servers: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

--- 约束 ---
- 创建 E:/opencode-desktop/GrassFlow/tui/mcp_integration.py（新文件）
- 修改 E:/opencode-desktop/GrassFlow/core/config.py（只添加 mcp_servers 字段）
- 使用 asyncio + subprocess（不依赖 mcp 库，先实现骨架）
- JSON-RPC 2.0 协议
- 代码风格与项目一致，from __future__ import annotations
`, {label: 'mcp-integration', phase: '实现', model: 'sonnet'}),

  // Agent 3: Skills 系统 + AGENTS.md 支持
  () => agent(`
你是一个 Python 开发者，负责实现 GrassFlow 的 Skills 系统和 AGENTS.md 加载功能。

--- 文件 1: 创建 E:/opencode-desktop/GrassFlow/tui/skills_system.py ---

参考 hermes 的 skills 实现（tools/skills_tool.py, agent/prompt_builder.py, agent/skill_utils.py）。

hermes 的 Skills 架构要点：
1. SKILL.md 格式：YAML frontmatter + Markdown 内容
2. 目录结构：~/.hermes/skills/{skill-name}/SKILL.md
3. 两级缓存：进程内 LRU + 磁盘快照
4. 平台过滤：platforms 字段限制 OS
5. 技能索引注入到系统提示词

SKILL.md 格式示例:
  ---
  name: skill-name
  description: Brief description
  version: 1.0.0
  platforms: [windows, linux, macos]
  prerequisites:
    env_vars: [API_KEY]
    commands: [curl, jq]
  metadata:
    tags: [coding, research]
  ---
  (Markdown content)

请实现：

Skill(dataclass):
  - name: str
  - description: str
  - version: str = "1.0.0"
  - platforms: List[str] (空=所有平台)
  - prerequisites: Dict[str, List[str]]
  - metadata: Dict[str, Any]
  - content: str (Markdown 内容)
  - path: Optional[Path]
  - enabled: bool = True

SkillsManager:
  - __init__(skills_dir: Optional[Path]) 默认 ~/.Grass/skills/
  - scan() -> List[Skill] (扫描 SKILL.md 文件)
  - _parse_skill_file(path) -> Optional[Skill]
  - _split_frontmatter(content) -> (dict, str) (分离 YAML frontmatter)
  - get_skill(name) -> Optional[Skill]
  - list_skills() -> List[Skill]
  - build_skills_prompt() -> str (构建技能索引提示词)
  - get_skills_summary() -> str (用于 /skills 命令)

注意：不依赖 yaml 库，提供简单降级解析（逐行解析 key: value）

--- 文件 2: 创建 E:/opencode-desktop/GrassFlow/tui/agents_md_loader.py ---

参考 hermes 的 agent/prompt_builder.py:build_context_files_prompt()。

上下文文件优先级（第一个匹配的胜出）：
1. .grassflow.md / GRASSFLOW.md - 向上查找到 git root
2. AGENTS.md / agents.md - 仅当前目录
3. CLAUDE.md / claude.md - 仅当前目录
4. .cursorrules - 仅当前目录

请实现：

CONTEXT_FILE_CANDIDATES: List[Tuple[str, str]] (filename, search_mode)

find_context_file(start_dir) -> Tuple[Optional[Path], Optional[str]]
  - search_mode="here": 仅在 start 目录查找
  - search_mode="up": 向上查找到 git root（通过 .git 目录判断）

load_context_file(start_dir, max_size=50000) -> Tuple[str, Optional[str]]
  - 读取文件内容，超过 max_size 则截断

build_context_prompt(start_dir) -> str
  - 构建格式化的上下文提示词

get_git_root(start_dir) -> Optional[Path]
  - 通过 subprocess 运行 git rev-parse --show-toplevel

list_context_files(start_dir) -> str
  - 列出所有发现的上下文文件（调试用）

--- 约束 ---
- 创建两个新文件
- 不依赖 yaml 库
- 代码风格与项目一致，from __future__ import annotations
`, {label: 'skills+agents-md', phase: '实现', model: 'sonnet'}),

  // Agent 4: 状态栏显示 thinking + 补全器增强
  () => agent(`
你是一个 Python 开发者，负责增强 GrassFlow 的状态栏显示和命令补全。

--- 任务 1: 修改 E:/opencode-desktop/GrassFlow/tui/layout.py ---

在 make_header_text_cb 函数中，找到 mode_text 显示的位置（约第258行附近），在 result.append(("class:header-dim", f" |  {mode_text}")) 之后，添加 thinking 模式显示：

代码逻辑：
  thinking_config = None
  if session:
      thinking_config = session.metadata.get("thinking") if hasattr(session, 'metadata') else None
  if thinking_config and isinstance(thinking_config, dict) and thinking_config.get("enabled", False):
      effort = thinking_config.get("effort", "medium")
      result.append(("class:header-dim", f" | 🧠 {effort}"))

注意：只修改 make_header_text_cb 函数内部，不要改其他任何东西。

--- 任务 2: 修改 E:/opencode-desktop/GrassFlow/tui/slash_commands.py 的 SlashCommandCompleter ---

注意：另一个 agent 正在同时修改这个文件的 COMMAND_REGISTRY 部分。你只修改 SlashCommandCompleter 类（文件末尾约第696-777行）。

修改 get_completions 方法：
1. 删除硬编码的 self.COMMANDS 字典（在 __init__ 中）
2. 命令补全改为从 COMMAND_REGISTRY 动态获取：
   - 遍历 COMMAND_REGISTRY.items()
   - 前缀匹配 cmd_name
   - 显示 display_meta=cmd_def.description
   - 也检查 cmd_def.aliases

3. 添加 _get_argument_completions 方法：
   - /think 或 /reasoning: 补全 on, off, low, medium, high, xhigh, show
   - /model: 从 config 读取模型名补全
   - /theme: 补全 default, dark, light, cyber, ocean
   - /mcp: 补全 list, start, stop, status, add, remove, test
   - /skills: 补全 list, view, search, install

--- 约束 ---
- layout.py 只改 make_header_text_cb 函数
- slash_commands.py 只改 SlashCommandCompleter 类
- 不要修改其他已有命令的 handler
- 代码风格与项目一致
`, {label: 'completion+display', phase: '实现', model: 'sonnet'}),
])

// Phase 2: 验证
phase('验证')

const verification = await agent(`
你是一个代码审查者。检查以下文件的实现质量：

1. E:/opencode-desktop/GrassFlow/tui/slash_commands.py -- 新增的 /think 命令和其他命令
2. E:/opencode-desktop/GrassFlow/tui/mcp_integration.py -- MCP 集成模块
3. E:/opencode-desktop/GrassFlow/tui/skills_system.py -- Skills 系统
4. E:/opencode-desktop/GrassFlow/tui/agents_md_loader.py -- AGENTS.md 加载器
5. E:/opencode-desktop/GrassFlow/tui/layout.py -- 状态栏 thinking 显示

审查要点：
- 新命令是否正确注册到 COMMAND_REGISTRY
- handler 函数签名是否统一：handler(repl_instance, args) -> None
- MCP 集成是否使用正确的 JSON-RPC 2.0 协议
- Skills 系统的 SKILL.md 解析是否健壮
- AGENTS.md 加载器的优先级是否正确
- 是否有明显的 bug 或遗漏
- 代码风格是否与项目一致

输出格式：
  通过 - [列表]
  问题 - [文件:行号] [严重程度] [描述]
  建议 - [列表]
`, {label: 'code-review', phase: '验证', model: 'sonnet'})

return { results, verification }
