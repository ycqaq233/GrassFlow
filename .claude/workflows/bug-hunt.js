export const meta = {
  name: 'bug-hunt',
  description: 'GrassFlow 全面 Bug 排查与修复',
  phases: [
    { title: '扫描', detail: '5个agent并行扫描不同模块' },
    { title: '修复', detail: '汇总并修复所有bug' },
    { title: '验证', detail: '验证修复正确性' },
  ],
}

// Phase 1: 5 个 agent 并行扫描
phase('扫描')

const scanResults = await parallel([
  // Agent 1: Layout + Keybindings + 鼠标滚动
  () => agent(
    '你是一个 Python/TUI bug 猎手。全面审查 E:/opencode-desktop/GrassFlow/tui/layout.py 中的所有 bug。\n\n' +
    '已知问题：鼠标滚动又不能使用了。\n\n' +
    '审查要点：\n' +
    '1. build_layout 函数：检查 Application 创建时是否启用了 mouse_support\n' +
    '2. build_keybindings 函数：检查所有快捷键绑定是否正确\n' +
    '3. 鼠标滚轮事件处理：是否有 mouse_scroll 相关绑定？prompt_toolkit 的 full_screen=False 模式下鼠标滚动需要特殊处理\n' +
    '4. KeybindingCallbacks 类：检查所有回调是否正确传递\n' +
    '5. build_pt_style：检查样式定义是否有语法错误\n' +
    '6. make_header_text_cb：检查新增的 thinking 模式显示是否有 bug（session 可能为 None，metadata 可能不存在）\n' +
    '7. OutputEntry 类：是否有潜在问题\n' +
    '8. 浮动窗口/补全菜单：布局中是否有 Float 配置问题\n\n' +
    '关键检查：\n' +
    '- prompt_toolkit 在 full_screen=False 模式下，鼠标滚动默认可能不工作\n' +
    '- 需要在 Application() 中设置 mouse_support=True\n' +
    '- 或者需要在 HSplit 容器上设置 mouse_scroll=True\n' +
    '- 检查 Window 的 scroll_offsets 配置\n\n' +
    '读取文件，逐行审查，列出所有发现的 bug（包括潜在 bug）。\n' +
    '格式：BUG [严重程度] [行号] 描述 / FIX: 修复建议',
    {label: 'scan-layout', phase: '扫描', model: 'sonnet'}
  ),

  // Agent 2: Slash Commands + Completer
  () => agent(
    '你是一个 Python/TUI bug 猎手。全面审查 E:/opencode-desktop/GrassFlow/tui/slash_commands.py 中的所有 bug。\n\n' +
    '这个文件最近被大幅修改（从 777 行扩展到 1200+ 行），新增了 13 个命令和补全器重构。\n\n' +
    '审查要点：\n' +
    '1. COMMAND_REGISTRY 列表：所有 CommandDef 是否正确定义\n' +
    '2. _HANDLER_MAP 字典：是否与 COMMAND_REGISTRY 中的 handler_name 一一对应\n' +
    '3. 所有新增 handler 函数（think/resume/retry/fork/title/agent/mcp/skills/copy/usage/version/connect/yolo）\n' +
    '4. SlashCommandCompleter：从 COMMAND_REGISTRY 动态获取是否正确\n' +
    '5. CommandRegistry 类：register/get/execute 方法\n' +
    '6. parse_reasoning_effort 函数\n' +
    '7. 原有的 21 个命令 handler 是否被破坏\n\n' +
    '逐行审查，列出所有 bug。格式：BUG [严重程度] [行号] 描述 / FIX: 修复建议',
    {label: 'scan-commands', phase: '扫描', model: 'sonnet'}
  ),

  // Agent 3: REPL Core
  () => agent(
    '你是一个 Python/TUI bug 猎手。全面审查 E:/opencode-desktop/GrassFlow/tui/repl.py 中的所有 bug。\n\n' +
    '审查要点：\n' +
    '1. GrassFlowREPL 类初始化\n' +
    '2. run_async() 方法：prompt_toolkit Application 创建\n' +
    '3. _process_user_input：/exit 处理\n' +
    '4. _handle_slash_command：命令解析和分发\n' +
    '5. add_output 方法：SCROLL_TO_BOTTOM、invalidate\n' +
    '6. _apply_event：流式事件处理\n' +
    '7. _process_ui_updates：批量 UI 更新\n' +
    '8. _run_agent_loop_async：异步 agent 循环\n' +
    '9. _handle_undo / _handle_redo\n' +
    '10. _retry_last 标志是否被正确使用（新增的 /retry 命令依赖它）\n\n' +
    '逐行审查，列出所有 bug。格式：BUG [严重程度] [行号] 描述 / FIX: 修复建议',
    {label: 'scan-repl', phase: '扫描', model: 'sonnet'}
  ),

  // Agent 4: 新模块
  () => agent(
    '你是一个 Python/TUI bug 猎手。全面审查以下 3 个新创建的模块：\n' +
    '1. E:/opencode-desktop/GrassFlow/tui/mcp_integration.py\n' +
    '2. E:/opencode-desktop/GrassFlow/tui/skills_system.py\n' +
    '3. E:/opencode-desktop/GrassFlow/tui/agents_md_loader.py\n\n' +
    '审查要点：\n' +
    'mcp_integration.py: MCPServerConfig/MCPTool/MCPManager 的所有方法，JSON-RPC 协议，资源泄漏\n' +
    'skills_system.py: SKILL.md 解析，YAML 解析器，平台过滤，缓存\n' +
    'agents_md_loader.py: 文件搜索优先级，git root 检测，截断逻辑\n\n' +
    '逐行审查，列出所有 bug。格式：BUG [严重程度] [行号] 描述 / FIX: 修复建议',
    {label: 'scan-new-modules', phase: '扫描', model: 'sonnet'}
  ),

  // Agent 5: 核心模块
  () => agent(
    '你是一个 Python/TUI bug 猎手。全面审查以下文件：\n' +
    '1. E:/opencode-desktop/GrassFlow/tui/agent_loop.py\n' +
    '2. E:/opencode-desktop/GrassFlow/tui/stream_handler.py\n' +
    '3. E:/opencode-desktop/GrassFlow/core/config.py\n' +
    '4. E:/opencode-desktop/GrassFlow/tui/session.py\n' +
    '5. E:/opencode-desktop/GrassFlow/tui/context_compressor.py\n\n' +
    '审查要点：\n' +
    'agent_loop.py: LLM client 创建，流式处理，tool_call 执行，Doom Loop 检测\n' +
    'stream_handler.py: 事件回调，text_delta/thinking_delta 处理\n' +
    'config.py: Pydantic 模型验证，mcp_servers 字段，ConfigManager\n' +
    'session.py: SQLite 操作，会话恢复，消息存储\n' +
    'context_compressor.py: 压缩算法，边界情况\n\n' +
    '逐行审查，列出所有 bug。格式：BUG [严重程度] [行号] 描述 / FIX: 修复建议',
    {label: 'scan-core', phase: '扫描', model: 'sonnet'}
  ),
])

// Phase 2: 汇总并修复
phase('修复')

const fixResult = await agent(
  '你是一个 Python 开发者。你的任务是汇总所有扫描 agent 的发现，并修复所有确认的 bug。\n\n' +
  '请先读取以下文件获取最新的扫描结果（因为 agent 输出可能被截断）：\n' +
  '- E:/opencode-desktop/GrassFlow/tui/layout.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/slash_commands.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/repl.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/mcp_integration.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/skills_system.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/agents_md_loader.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/agent_loop.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/stream_handler.py\n' +
  '- E:/opencode-desktop/GrassFlow/core/config.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/session.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/context_compressor.py\n\n' +
  '同时参考上面 5 个 scan agent 的输出（scan-layout, scan-commands, scan-repl, scan-new-modules, scan-core）。\n\n' +
  '修复规则：\n' +
  '1. 只修复确认的 bug（有明确的错误逻辑），不修复"可能的问题"\n' +
  '2. 修复前先 Read 文件确认行号\n' +
  '3. 使用 Edit 工具精确修改\n' +
  '4. 每个修复保持最小改动\n' +
  '5. 不要引入新功能，只修 bug\n' +
    '6. 特别注意：鼠标滚动问题必须修复\n\n' +
  '修复完成后，列出所有修复的 bug 和对应的修改。',
  {label: 'fix-all', phase: '修复', model: 'sonnet'}
)

// Phase 3: 验证
phase('验证')

const verifyResult = await agent(
  '你是一个代码审查者。验证所有修复是否正确。\n\n' +
  '验证步骤：\n' +
  '1. 读取每个被修改的文件，确认修改正确\n' +
  '2. 运行 python -c "import tui.xxx" 确认没有导入错误\n' +
  '3. 检查修复是否引入了新问题\n' +
  '4. 确认鼠标滚动修复方案正确（prompt_toolkit full_screen=False 模式下）\n\n' +
  '输出：已修复列表 / 需要额外修复列表 / 引入的新问题列表',
  {label: 'verify', phase: '验证', model: 'sonnet'}
)

return { scanResults, fixResult, verifyResult }
