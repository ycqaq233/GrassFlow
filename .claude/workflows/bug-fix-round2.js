export const meta = {
  name: 'bug-fix-round2',
  description: '修复扫描发现的剩余 bug（分模块逐个修复）',
  phases: [
    { title: '修复核心', detail: 'repl.py + agent_loop.py 关键 bug' },
    { title: '修复辅助', detail: 'config.py + session.py + context_compressor.py + mcp bug' },
    { title: '验证', detail: '验证所有修复' },
  ],
}

// 上一轮已修复: 鼠标滚动、undo 自我污染、stream_handler flush
// 本轮修复剩余的关键 bug

phase('修复核心')

const coreFixes = await parallel([
  // Agent 1: repl.py 关键 bug
  () => agent(
    '修复 E:/opencode-desktop/GrassFlow/tui/repl.py 中的以下 bug（先 Read 文件确认行号再 Edit）：\n\n' +
    'BUG 1 [严重]: _retry_last 从未初始化也从未被消费\n' +
    '  - _cmd_retry 设置 repl._retry_last = True，但 repl.py 从未初始化或读取\n' +
    '  - FIX: 在 __init__ 中初始化 self._retry_last = False\n' +
    '  - FIX: 在 _process_user_input 中，进入 _handle_agent_message 前检查 _retry_last\n' +
    '    如果为 True，从 output 中找最后一条 user 消息的文本，用它替换当前输入，然后重置标志\n\n' +
    'BUG 2 [中等]: _process_ui_updates 中 tool_result 忽略 is_error 标志\n' +
    '  - 第 321 行左右，tool_result 始终用 role="tool"\n' +
    '  - FIX: 检查 kwargs.get("is_error", False)，如果 True 用 role="error"\n\n' +
    'BUG 3 [中等]: _last_latency_ms 从未被更新\n' +
    '  - _apply_event 处理 usage 事件时从未设置 _last_latency_ms\n' +
    '  - FIX: 在 usage 事件处理中，如果有 latency_ms 字段则更新 self._last_latency_ms\n\n' +
    'BUG 4 [低]: Ctrl+D 和 Ctrl+X Q 同步调用 app.exit()\n' +
    '  - layout.py 中 handle_ctrl_d 和 handle_exit 同步调用 event.app.exit()\n' +
    '  - FIX: 改为 create_background_task 延迟退出（与 Ctrl+C 一致）\n' +
    '  - 注意：这个 bug 在 layout.py 中，不是 repl.py\n\n' +
    'BUG 5 [低]: clear_output 不清空 undo/redo 栈\n' +
    '  - FIX: 在 clear_output 中同时清空 _undo_stack 和 _redo_stack',
    {label: 'fix-repl', phase: '修复核心', model: 'sonnet'}
  ),

  // Agent 2: agent_loop.py 关键 bug
  () => agent(
    '修复 E:/opencode-desktop/GrassFlow/tui/agent_loop.py 中的以下 bug（先 Read 文件确认行号再 Edit）：\n\n' +
    'BUG 1 [严重]: tool_id 赋值错误，用了 tool_call.name 而非 tool_call.id\n' +
    '  - 大约在第 174 行\n' +
    '  - FIX: 改为 tool_id = tool_call.id\n\n' +
    'BUG 2 [严重]: 非流式路径 tool_calls 永远为空\n' +
    '  - _call_llm_with_retry 构造 LLMResponse 时未设置 tool_calls\n' +
    '  - FIX: 从 response 中提取 tool_calls 并设置到 LLMResponse\n\n' +
    'BUG 3 [严重]: tool 消息丢失 tool_call_id\n' +
    '  - 消息扁平化时丢弃了 tool_call_id 和 name 字段\n' +
    '  - 在两个位置：_call_llm_with_retry 和 process_streaming\n' +
    '  - FIX: 保留 tool_call_id 和 name 字段\n\n' +
    'BUG 4 [高]: TOOL_CALL_END 事件在工具执行之前发出\n' +
    '  - process_streaming 中 TOOL_CALL_END 在工具执行前就 yield 了\n' +
    '  - FIX: 将 TOOL_CALL_END 移到工具执行之后',
    {label: 'fix-agent-loop', phase: '修复核心', model: 'sonnet'}
  ),
])

phase('修复辅助')

const auxFixes = await parallel([
  // Agent 3: config.py + session.py + context_compressor.py
  () => agent(
    '修复以下文件中的 bug（先 Read 文件确认行号再 Edit）：\n\n' +
    '--- config.py ---\n' +
    'BUG [严重]: list_configs 中 load_project_config() 可能返回 None 导致 AttributeError\n' +
    '  - FIX: 添加 None 检查\n\n' +
    '--- context_compressor.py ---\n' +
    'BUG [严重]: AutoCompactingContext.add_message 执行了两次压缩\n' +
    '  - compact() 后又调用 compact_and_rebuild()，浪费 LLM 调用\n' +
    '  - FIX: 只调用一次，直接使用 compact() 的结果重建\n\n' +
    'BUG [中等]: 压缩截断策略方向反了\n' +
    '  - 截断循环从 turn_end-1 向 turn_begin 遍历，第一次就匹配到最小切片\n' +
    '  - FIX: 改为从 turn_begin 向 turn_end 遍历，找到最大的在预算内的切片',
    {label: 'fix-config-context', phase: '修复辅助', model: 'sonnet'}
  ),

  // Agent 4: mcp_integration.py + slash_commands.py 剩余
  () => agent(
    '修复以下文件中的 bug（先 Read 文件确认行号再 Edit）：\n\n' +
    '--- mcp_integration.py ---\n' +
    'BUG [中等]: _run_server_loop 重连计数器在进程正常退出时永不递增\n' +
    '  - FIX: 在进程正常退出的分支中也递增 attempt\n\n' +
    'BUG [中等]: _read_line 逐字节读取无累计超时\n' +
    '  - FIX: 在调用处用 asyncio.wait_for 包裹整个 _read_line\n\n' +
    '--- slash_commands.py ---\n' +
    'BUG [中等]: _handle_redo 也有自我污染问题（与 undo 相同）\n' +
    '  - FIX: 与 undo 修复一致，redo 时也跳过 system 消息\n\n' +
    'BUG [低]: _ARG_COMPLETIONS 中 "reasoning" 键是死代码\n' +
    '  - FIX: 删除 reasoning 条目',
    {label: 'fix-mcp-commands', phase: '修复辅助', model: 'sonnet'}
  ),
])

phase('验证')

const verify = await agent(
  '验证所有修复。步骤：\n' +
  '1. 运行 python -c "from tui import repl, layout, slash_commands, agent_loop, stream_handler, mcp_integration, skills_system, agents_md_loader; print(ALL OK)" 确认无导入错误\n' +
  '2. 读取每个被修改文件的关键行，确认修改正确\n' +
  '3. 列出所有已修复和未修复的 bug',
  {label: 'verify-all', phase: '验证', model: 'sonnet'}
)

return { coreFixes, auxFixes, verify }
