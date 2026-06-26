export const meta = {
  name: 'bug-fix-final',
  description: '全面 Bug 验证与修复 - 覆盖全部 25+ 个 bug',
  phases: [
    { title: '验证', detail: '确认 bug 是否真实存在' },
    { title: '修复', detail: '8 个 agent 并行修复' },
    { title: '最终验证', detail: '确认所有修复正确' },
  ],
}

// ============================================================
// Phase 1: 验证所有 bug 是否真实存在
// ============================================================
phase('验证')

const verifyScan = await agent(
  '你是一个 bug 验证者。逐一检查以下 bug 是否在当前代码中真实存在。\n\n' +
  '读取以下文件，对每个 bug 检查描述的代码位置是否匹配：\n' +
  '- E:/opencode-desktop/GrassFlow/tui/repl.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/layout.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/slash_commands.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/agent_loop.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/stream_handler.py\n' +
  '- E:/opencode-desktop/GrassFlow/core/config.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/session.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/context_compressor.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/mcp_integration.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/skills_system.py\n' +
  '- E:/opencode-desktop/GrassFlow/tui/agents_md_loader.py\n\n' +
  'Bug 列表：\n\n' +
  '[repl.py]\n' +
  '#1 _retry_last 从未初始化也从未被消费 (slash_commands.py 设置, repl.py 不读取)\n' +
  '#2 add_output() 自动滚到底部覆盖用户手动滚动 (vertical_scroll = 10**6)\n' +
  '#3 _redo_stack 初始化但从未使用 (_handle_redo 用的是 _undo_stack)\n' +
  '#4 _execute_shell 同步阻塞 UI 线程 (subprocess.run)\n' +
  '#5 _process_ui_updates 中 tool_result 忽略 is_error 标志\n' +
  '#6 _last_latency_ms 从未被更新，始终为 0\n' +
  '#7 _token_count 在 REPL 和 AgentIntegration 之间不同步\n' +
  '#8 _on_invalidate 回调可能触发不必要的重绘链\n' +
  '#9 undo/redo 可在 Agent 运行时被调用 (快捷键无检查)\n' +
  '#10 Ctrl+D 和 Ctrl+X Q 同步调用 app.exit() (layout.py)\n' +
  '#11 run() 异常回退路径设置不存在的 _output_buffer 属性\n' +
  '#12 clear_output 不清空 undo/redo 栈\n\n' +
  '[agent_loop.py]\n' +
  '#13 tool_id 赋值用了 tool_call.name 而非 tool_call.id\n' +
  '#14 非流式路径 _call_llm_with_retry 的 LLMResponse 未设置 tool_calls\n' +
  '#15 tool 消息扁平化时丢失 tool_call_id 和 name 字段 (两处)\n' +
  '#16 TOOL_CALL_END 事件在工具执行之前发出\n\n' +
  '[stream_handler.py]\n' +
  '#17 _handle_tool_call 从 event.data 读取的字段名不匹配\n' +
  '#18 ThinkingParser flush 不刷新 _pending 缓冲区\n\n' +
  '[config.py]\n' +
  '#19 list_configs 中 load_project_config() 返回 None 导致 AttributeError\n' +
  '#20 deep_merge 无法将字段显式设为 None\n\n' +
  '[context_compressor.py]\n' +
  '#21 AutoCompactingContext.add_message 执行两次压缩\n' +
  '#22 压缩截断策略方向反了 (保留最小而非最大切片)\n\n' +
  '[mcp_integration.py]\n' +
  '#23 _run_server_loop 重连计数器在进程正常退出时永不递增\n' +
  '#24 _read_line 逐字节读取无累计超时\n\n' +
  '[skills_system.py]\n' +
  '#25 _parse_yaml_simple 的 isdigit() 接受 Unicode 数字\n' +
  '#26 _parse_yaml_simple 不支持负整数\n\n' +
  '[agents_md_loader.py]\n' +
  '#27 get_context_file_info 调用 get_git_root 两次\n\n' +
  '[session.py]\n' +
  '#28 add_message 和 update_session 不在同一事务中\n\n' +
  '[slash_commands.py]\n' +
  '#29 _handle_redo 有自我污染问题 (与 undo 相同)\n' +
  '#30 _ARG_COMPLETIONS 中 "reasoning" 键是死代码\n\n' +
  '对每个 bug 输出：\n' +
  '  #N [EXISTS/FIXED/NOT_FOUND] 简要说明\n' +
  '其中 EXISTS=bug 存在需修复, FIXED=已被之前的修复解决, NOT_FOUND=代码已改变或描述不准确',
  {label: 'verify-bugs', phase: '验证', model: 'sonnet'}
)

// ============================================================
// Phase 2: 8 个 agent 并行修复
// ============================================================
phase('修复')

const fixResults = await parallel([
  // Agent 1: repl.py - 滚动 + undo/redo 安全
  () => agent(
    '修复 E:/opencode-desktop/GrassFlow/tui/repl.py 和 E:/opencode-desktop/GrassFlow/tui/layout.py 中的 bug。先 Read 文件确认行号再 Edit。\n\n' +
    'BUG #2: add_output() 自动滚到底部覆盖用户手动滚动\n' +
    '  在 repl.py 的 add_output 方法中，每次都设 self._output_window.vertical_scroll = SCROLL_TO_BOTTOM\n' +
    '  FIX: 添加 self._user_scrolled = False 标志（在 __init__ 中初始化）。\n' +
    '  在 layout.py 的 handle_mouse_scroll_up/down 和 handle_scroll_up/down 中设置 callbacks.set_user_scrolled()。\n' +
    '  在 add_output 中只在 not self._user_scrolled 时才滚动到底部。\n' +
    '  在 _handle_agent_message 开始时重置 self._user_scrolled = False。\n\n' +
    'BUG #9: undo/redo 可在 Agent 运行时被调用\n' +
    '  在 layout.py 的 handle_undo 和 handle_redo 快捷键中添加 agent_running() 检查：\n' +
    '  if callbacks.agent_running(): callbacks.add_output("Agent is running.", "system"); return\n\n' +
    'BUG #10: Ctrl+D 和 Ctrl+X Q 同步调用 app.exit()\n' +
    '  在 layout.py 中改为 create_background_task 延迟退出（与 Ctrl+C 一致）',
    {label: 'fix-repl-scroll', phase: '修复', model: 'sonnet'}
  ),

  // Agent 2: repl.py - retry + redo + clear
  () => agent(
    '修复 E:/opencode-desktop/GrassFlow/tui/repl.py 和 E:/opencode-desktop/GrassFlow/tui/slash_commands.py 中的 bug。先 Read 文件确认行号再 Edit。\n\n' +
    'BUG #1: _retry_last 从未初始化也从未被消费\n' +
    '  在 repl.py 的 __init__ 中添加 self._retry_last = False\n' +
    '  在 _process_user_input 中，调用 _handle_agent_message 前检查 self._retry_last：\n' +
    '  如果为 True，从 self.output 中找最后一条 role="user" 的条目，用它的 text 替换输入，重置标志\n\n' +
    'BUG #3: _redo_stack 初始化但从未使用\n' +
    '  确认 _redo_stack 在 __init__ 中初始化即可，当前 redo 实现用 _undo_stack 也可以工作\n' +
    '  如果 _handle_redo 中用了 _undo_stack，保持现状，但确保 redo 后从 _undo_stack 移除\n\n' +
    'BUG #12: clear_output 不清空 undo/redo 栈\n' +
    '  在 clear_output 中添加 self._undo_stack.clear() 和 self._redo_stack.clear()\n\n' +
    'BUG #29: _handle_redo 自我污染\n' +
    '  在 slash_commands.py 的 _handle_redo 中，与 undo 修复一致，跳过 system 消息',
    {label: 'fix-repl-retry', phase: '修复', model: 'sonnet'}
  ),

  // Agent 3: repl.py - 杂项
  () => agent(
    '修复 E:/opencode-desktop/GrassFlow/tui/repl.py 中的 bug。先 Read 文件确认行号再 Edit。\n\n' +
    'BUG #4: _execute_shell 同步阻塞 UI 线程\n' +
    '  subprocess.run 是阻塞调用，最长 30 秒\n' +
    '  FIX: 将 subprocess.run 放到线程中执行：\n' +
    '  import threading; def run_in_thread(): result = subprocess.run(...); self.add_output(result.stdout or result.stderr)\n' +
    '  threading.Thread(target=run_in_thread, daemon=True).start()\n\n' +
    'BUG #5: _process_ui_updates 中 tool_result 忽略 is_error\n' +
    '  找到 tool_result 处理分支，添加 is_error 检查：\n' +
    '  is_err = kwargs.get("is_error", False)\n' +
    '  role = "error" if is_err else "tool"\n' +
    '  prefix = "[ERROR] " if is_err else ""\n\n' +
    'BUG #6: _last_latency_ms 从未被更新\n' +
    '  在 _apply_event 的 usage 事件处理中，如果有 latency 信息则更新\n' +
    '  如果没有 latency 字段，记录调用时间差：在 _handle_agent_message 开始时记 self._api_start_time = time.time()\n' +
    '  在 usage 事件中：self._last_latency_ms = int((time.time() - self._api_start_time) * 1000)\n\n' +
    'BUG #11: run() 异常回退路径设置不存在的 _output_buffer\n' +
    '  找到 self._output_buffer = [...] 改为 self.add_output(BANNER.strip(), role="system")',
    {label: 'fix-repl-misc', phase: '修复', model: 'sonnet'}
  ),

  // Agent 4: agent_loop.py
  () => agent(
    '修复 E:/opencode-desktop/GrassFlow/tui/agent_loop.py 中的 bug。先 Read 文件确认行号再 Edit。\n\n' +
    'BUG #13: tool_id 赋值用了 tool_call.name 而非 tool_call.id\n' +
    '  找到 tool_id = tool_call.name 改为 tool_id = tool_call.id\n\n' +
    'BUG #14: 非流式路径 LLMResponse 未设置 tool_calls\n' +
    '  在 _call_llm_with_retry 中构造 LLMResponse 时，从 response 提取 tool_calls\n' +
    '  如果 response 有 tool_calls 属性，设置到 LLMResponse\n\n' +
    'BUG #15: tool 消息扁平化时丢失 tool_call_id\n' +
    '  找到消息扁平化的位置（两处），保留 tool_call_id 和 name：\n' +
    '  msg = {"role": m.role, "content": m.content}\n' +
    '  if hasattr(m, "tool_call_id") and m.tool_call_id: msg["tool_call_id"] = m.tool_call_id\n' +
    '  if hasattr(m, "name") and m.name: msg["name"] = m.name\n\n' +
    'BUG #16: TOOL_CALL_END 在工具执行之前发出\n' +
    '  找到 process_streaming 中 yield TOOL_CALL_END 的位置，移到工具执行之后',
    {label: 'fix-agent-loop', phase: '修复', model: 'sonnet'}
  ),

  // Agent 5: stream_handler.py + config.py
  () => agent(
    '修复 E:/opencode-desktop/GrassFlow/tui/stream_handler.py 和 E:/opencode-desktop/GrassFlow/core/config.py 中的 bug。先 Read 文件确认行号再 Edit。\n\n' +
    'BUG #17: _handle_tool_call 字段名不匹配\n' +
    '  event.data 的格式是 {"tool_call": ToolCall(...)} 而不是 {"tool_name": ..., "arguments": ...}\n' +
    '  FIX: 先尝试 event.data.get("tool_call")，如果有则从 tc.name 和 tc.arguments 获取\n\n' +
    'BUG #18: ThinkingParser feed("") 不刷新 _pending\n' +
    '  给 ThinkingParser 添加 flush() 方法，输出 _pending 中的残留数据\n' +
    '  在 _flush_output 中调用 parser.flush() 而非 parser.feed("")\n\n' +
    'BUG #19: list_configs 中 load_project_config() 返回 None\n' +
    '  FIX: 添加 None 检查：pc = self.load_project_config(); result = pc.model_dump() if pc else None\n\n' +
    'BUG #20: deep_merge 无法将字段显式设为 None\n' +
    '  FIX: 改为检查 key 是否在 override 中而非 value is not None：\n' +
    '  if key in override: merged[key] = override[key]',
    {label: 'fix-stream-config', phase: '修复', model: 'sonnet'}
  ),

  // Agent 6: mcp_integration.py
  () => agent(
    '修复 E:/opencode-desktop/GrassFlow/tui/mcp_integration.py 中的 bug。先 Read 文件确认行号再 Edit。\n\n' +
    'BUG #23: _run_server_loop 重连计数器在进程正常退出时永不递增\n' +
    '  在进程正常退出的分支中（logger.warning 之后），添加 attempt += 1\n' +
    '  并检查 if attempt >= MAX_RECONNECT_ATTEMPTS: break\n\n' +
    'BUG #24: _read_line 逐字节读取无累计超时\n' +
    '  在调用 _read_line 的地方，用 asyncio.wait_for 包裹整体调用\n' +
    '  或在 _read_line 内部使用 deadline = asyncio.get_event_loop().time() + timeout',
    {label: 'fix-mcp', phase: '修复', model: 'sonnet'}
  ),

  // Agent 7: skills_system.py + agents_md_loader.py
  () => agent(
    '修复 E:/opencode-desktop/GrassFlow/tui/skills_system.py 和 E:/opencode-desktop/GrassFlow/tui/agents_md_loader.py 中的 bug。先 Read 文件确认行号再 Edit。\n\n' +
    'BUG #25: _parse_yaml_simple 的 isdigit() 接受 Unicode 数字\n' +
    '  FIX: 改用 value.lstrip("-").isdigit() 或 re.fullmatch(r"-?\\d+", value)\n\n' +
    'BUG #26: _parse_yaml_simple 不支持负整数\n' +
    '  FIX: 在数字检测中先检查 value.lstrip("-").isdigit()\n\n' +
    'BUG #27: get_context_file_info 调用 get_git_root 两次\n' +
    '  FIX: 缓存结果：git_root = get_git_root(start_dir); 然后复用',
    {label: 'fix-skills-agents', phase: '修复', model: 'sonnet'}
  ),

  // Agent 8: context_compressor.py + session.py
  () => agent(
    '修复 E:/opencode-desktop/GrassFlow/tui/context_compressor.py 和 E:/opencode-desktop/GrassFlow/tui/session.py 中的 bug。先 Read 文件确认行号再 Edit。\n\n' +
    'BUG #21: AutoCompactingContext.add_message 执行两次压缩\n' +
    '  找到 compact() 后又调用 compact_and_rebuild() 的位置\n' +
    '  FIX: 只调用 compact()，然后用其结果直接重建消息列表：\n' +
    '  result = await self.compressor.compact(self.messages)\n' +
    '  if result.tokens_saved > 0:\n' +
    '      rebuilt = []\n' +
    '      if self.system_prompt: rebuilt.append(...)\n' +
    '      rebuilt.append(ChatMessage(role="system", content=f"[压缩摘要]\\n{result.summary}"))\n' +
    '      rebuilt.extend(result.tail_messages)\n' +
    '      self.messages = rebuilt\n\n' +
    'BUG #22: 压缩截断策略方向反了\n' +
    '  找到截断循环，当前从 turn_end-1 向 turn_begin 遍历\n' +
    '  FIX: 改为从 turn_begin 向 turn_end 遍历，找到第一个在预算内的切片\n\n' +
    'BUG #28: session 事务不一致\n' +
    '  这个优先级低，如果修改复杂可以跳过。简单方案：在 clear_session 中用一个连接完成所有操作',
    {label: 'fix-compressor', phase: '修复', model: 'sonnet'}
  ),
])

// ============================================================
// Phase 3: 最终验证
// ============================================================
phase('最终验证')

const finalVerify = await agent(
  '最终验证所有修复。步骤：\n\n' +
  '1. 运行导入测试：\n' +
  '   python -c "from tui import repl, layout, slash_commands, agent_loop, stream_handler, mcp_integration, skills_system, agents_md_loader, session, context_compressor; from core import config; print(ALL OK)"\n\n' +
  '2. 读取每个被修改文件的关键区域，确认修改正确\n\n' +
  '3. 列出所有已修复的 bug 编号和简要描述\n\n' +
  '4. 列出仍需关注的问题（如有）',
  {label: 'final-verify', phase: '最终验证', model: 'sonnet'}
)

return { verifyScan, fixResults, finalVerify }
