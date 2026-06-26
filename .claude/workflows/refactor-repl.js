export const meta = {
  name: 'refactor-repl',
  description: '重构 repl.py — 拆分为6个职责清晰的模块',
  phases: [
    { title: 'Extract', detail: '并行提取 slash_commands/layout/agent_integration/compat/fallback' },
    { title: 'Rewrite', detail: '重写 repl.py 主文件，引用新模块' },
    { title: 'Verify', detail: '运行测试验证重构正确性' },
  ],
}

/**
 * 阶段1：并行提取 5 个模块
 * 每个 agent 负责从 repl.py 中提取一个职责到独立文件
 */
phase('Extract')

const EXTRACT_TASKS = [
  {
    label: 'extract:slash_commands',
    prompt: `你是 GrassFlow 重构子代理。任务：从 tui/repl.py 中提取斜杠命令系统到 tui/slash_commands.py。

## 要求

1. 读取 E:/opencode-desktop/GrassFlow/tui/repl.py
2. 提取以下内容到 E:/opencode-desktop/GrassFlow/tui/slash_commands.py：
   - 所有 _cmd_* 方法（_cmd_help, _cmd_model, _cmd_list_models, _cmd_new_session, _cmd_clear, _cmd_compact, _cmd_list_sessions, _cmd_init, _cmd_undo, _cmd_redo, _cmd_exit, _cmd_theme, _cmd_provider, _cmd_run, _cmd_list_workflows, _cmd_history, _cmd_validate, _cmd_templates, _cmd_config, _cmd_stats, _cmd_status）
   - 所有 _handle_* 方法（_handle_compact, _handle_new_session, _handle_list_sessions, _handle_undo, _handle_redo, _handle_list_models）
   - SlashCommandCompleter 类
3. 创建 CommandDef dataclass（参考 hermes 的设计）：
   @dataclass(frozen=True)
   class CommandDef:
       name: str           # "model"
       description: str    # "切换模型"
       category: str       # "Configuration"
       aliases: tuple      # ("mo",)
       args_hint: str      # "[provider:model]"
       handler_name: str   # "_cmd_model"
       visible: bool = True
4. 创建 COMMAND_REGISTRY 列表，注册所有命令
5. 创建 CommandRegistry 类，提供：
   - register(cmd: CommandDef) 方法
   - get(name: str) -> Optional[CommandDef] 方法（支持别名查找）
   - execute(name: str, args: list, repl_instance) -> None 方法
   - all_commands() -> list[CommandDef] 方法
6. 处理函数需要能访问 repl_instance（GrassFlowREPL 实例），通过参数传入
7. 确保导入正确，不引入循环依赖

## 参考
hermes 的 COMMAND_REGISTRY 设计（E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/commands.py）
opencode 的声明式命令注册（slashName, slashAliases, category）

## 输出
写入 E:/opencode-desktop/GrassFlow/tui/slash_commands.py
报告提取了多少个命令、多少行代码。`,
  },
  {
    label: 'extract:layout',
    prompt: `你是 GrassFlow 重构子代理。任务：从 tui/repl.py 中提取 prompt_toolkit 布局和渲染逻辑到 tui/layout.py。

## 要求

1. 读取 E:/opencode-desktop/GrassFlow/tui/repl.py
2. 提取以下内容到 E:/opencode-desktop/GrassFlow/tui/layout.py：
   - build_pt_style() 函数（如果存在）或样式相关代码
   - prompt_toolkit Layout 构建代码（HSplit, Window, FloatContainer 等）
   - 输出区域渲染控制（OutputAreaControl 或类似类）
   - HeaderControl / StatusBarControl 等自定义 UIControl
   - KeyBindings 设置逻辑（_setup_keybindings 方法的内容）
   - BANNER 常量
   - PROMPT / PROMPT_STYLE 常量
3. 创建函数：
   - build_layout(theme: REPLTheme, input_buffer: Buffer, output_entries: list, ...) -> Layout
   - build_keybindings(repl_instance) -> KeyBindings
   - build_pt_style(theme: REPLTheme) -> Style
4. 保持与 repl.py 中原有逻辑的一致性
5. 确保 repl.py 中的 self.xxx 属性引用能通过参数传递解决

## 输出
写入 E:/opencode-desktop/GrassFlow/tui/layout.py
报告提取了多少行代码。`,
  },
  {
    label: 'extract:agent_integration',
    prompt: `你是 GrassFlow 重构子代理。任务：从 tui/repl.py 中提取 Agent Loop 集成逻辑到 tui/agent_integration.py。

## 要求

1. 读取 E:/opencode-desktop/GrassFlow/tui/repl.py
2. 提取以下内容到 E:/opencode-desktop/GrassFlow/tui/agent_integration.py：
   - _init_agent_loop() 方法
   - _process_entry() 方法中与 Agent Loop 交互的部分
   - Agent Loop 流式输出处理逻辑
   - _run_fallback() 方法中的 Agent Loop 调用部分
3. 创建 AgentIntegration 类：
   class AgentIntegration:
       def __init__(self, config_manager, session_manager=None):
           self._agent_loop = None
           self._session_mgr = session_manager

       def init_agent_loop(self) -> None:
           """初始化 Agent Loop（使用 create_agent_loop_from_config）"""

       async def process_streaming(self, messages, on_token=None, on_tool_call=None, on_error=None):
           """流式处理消息"""

       async def process(self, messages) -> str:
           """非流式处理消息"""
4. 确保正确导入 agent_loop 模块
5. 保留原有的错误处理和重试逻辑

## 输出
写入 E:/opencode-desktop/GrassFlow/tui/agent_integration.py
报告提取了多少行代码。`,
  },
  {
    label: 'extract:compat',
    prompt: `你是 GrassFlow 重构子代理。任务：从 tui/repl.py 中提取向后兼容层到 tui/compat.py。

## 要求

1. 读取 E:/opencode-desktop/GrassFlow/tui/repl.py
2. 提取文件末尾（约第 1800 行之后）的向后兼容代码到 E:/opencode-desktop/GrassFlow/tui/compat.py：
   - MessageRole 类（_Enum 枚举）
   - Message 数据类
   - CommandResult 数据类
   - CommandHandler 类
   - InputHandler 类
   - MessageRenderer 类
   - REPL 类（旧版 GrassFlowREPL 包装器）
3. 在 compat.py 中从 tui.repl 导入 GrassFlowREPL（如果需要的话）
4. 确保旧的 import 路径仍然可用：
   - from tui.repl import Message, MessageRole, CommandResult 仍然能用
   - 可以在 repl.py 中 re-export 这些类

## 输出
写入 E:/opencode-desktop/GrassFlow/tui/compat.py
报告提取了多少行代码。`,
  },
  {
    label: 'extract:fallback',
    prompt: `你是 GrassFlow 重构子代理。任务：从 tui/repl.py 中提取降级模式逻辑到 tui/fallback.py。

## 要求

1. 读取 E:/opencode-desktop/GrassFlow/tui/repl.py
2. 提取 _run_fallback() 方法到 E:/opencode-desktop/GrassFlow/tui/fallback.py
3. 创建 run_fallback_mode() 函数：
   - 参数：agent_integration, session_manager, theme, notice
   - 功能：使用 input() + Rich console 实现降级 REPL
   - 保持原有的流式输出逻辑（asyncio.run 包装）
4. 确保正确处理：
   - Windows 编码问题（UTF-8）
   - Ctrl+C 中断
   - 退出命令

## 输出
写入 E:/opencode-desktop/GrassFlow/tui/fallback.py
报告提取了多少行代码。`,
  },
]

// 并行执行 5 个提取任务
const extracted = await parallel(
  EXTRACT_TASKS.map(t => () => agent(t.prompt, { label: t.label, phase: 'Extract' }))
)

log(`Extract phase complete: ${extracted.filter(Boolean).length}/5 modules extracted`)

/**
 * 阶段2：重写 repl.py 主文件
 */
phase('Rewrite')

await agent(`你是 GrassFlow 重构子代理。任务：重写 tui/repl.py，引用新提取的模块。

## 背景
已完成以下模块的提取：
- tui/slash_commands.py — 命令系统
- tui/layout.py — 布局渲染
- tui/agent_integration.py — Agent Loop 集成
- tui/compat.py — 向后兼容层
- tui/fallback.py — 降级模式

## 要求

1. 读取当前的 E:/opencode-desktop/GrassFlow/tui/repl.py
2. 读取所有新提取的模块，了解它们的接口
3. 重写 repl.py，使其：
   - 从新模块导入所需类和函数
   - GrassFlowREPL 类变瘦，只保留：
     - __init__（初始化，组合各模块）
     - run() 方法（启动 prompt_toolkit Application）
     - add_output() / _render_output() 等输出管理方法
     - _accept_input() 方法（输入处理入口）
     - _process_user_input() 方法（区分斜杠命令和普通输入）
     - _handle_slash_command() 方法（委托给 CommandRegistry）
     - _handle_agent_message() 方法（委托给 AgentIntegration）
     - 属性访问器（theme, mode, session 等）
   - 从 tui.compat 导入并向外 re-export Message, MessageRole, CommandResult 等
   - AsyncGrassFlowREPL 保持不变
   - 底部的 create_repl() 等工厂函数保持不变
4. 确保所有导入正确，不引入循环依赖
5. 保持原有的公共 API 不变（GrassFlowREPL.run(), add_output() 等）

## 关键约束
- repl.py 不应超过 500 行
- 不要修改新提取的模块文件
- 保持向后兼容

## 输出
重写 E:/opencode-desktop/GrassFlow/tui/repl.py
报告新文件的行数。`, { label: 'rewrite:repl', phase: 'Rewrite' })

/**
 * 阶段3：验证
 */
phase('Verify')

await agent(`你是 GrassFlow 测试子代理。任务：验证 repl.py 重构的正确性。

## 要求

1. 检查 E:/opencode-desktop/GrassFlow/tui/ 下的新文件是否存在：
   - slash_commands.py
   - layout.py
   - agent_integration.py
   - compat.py
   - fallback.py
   - repl.py（已更新）

2. 检查导入关系：
   - python -c "from tui.repl import GrassFlowREPL, Message, MessageRole"
   - python -c "from tui.slash_commands import CommandRegistry, COMMAND_REGISTRY"
   - python -c "from tui.layout import build_layout, build_keybindings"
   - python -c "from tui.agent_integration import AgentIntegration"
   - python -c "from tui.compat import Message, CommandResult, REPL"
   - python -c "from tui.fallback import run_fallback_mode"

3. 运行现有测试：
   - cd E:/opencode-desktop/GrassFlow && .venv/Scripts/python -m pytest tests/ -x -q

4. 检查文件行数：
   - repl.py 应该不超过 500 行
   - 各模块行数合理

5. 输出验证报告：
   - 哪些导入成功
   - 哪些测试通过/失败
   - 各文件行数统计
   - 是否有循环依赖问题`, { label: 'verify:imports', phase: 'Verify' })
