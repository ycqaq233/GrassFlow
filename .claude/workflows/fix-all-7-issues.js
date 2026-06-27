export const meta = {
  name: 'fix-all-7-issues',
  description: 'Fix 7 remaining issues: output duplication, thinking/tool folding, tests, compression, MCP transport',
  phases: [
    { title: 'Research', detail: 'Study hermes/opencode implementations' },
    { title: 'Implement', detail: '7 parallel agents in worktrees' },
    { title: 'Merge', detail: 'Merge worktree branches back to master' },
    { title: 'Bug Hunt', detail: '4 agents hunting bugs in parallel' },
    { title: 'Bug Fix', detail: 'Fix all found bugs' },
  ],
}

// ========================================
// Phase 1: Research — Study reference implementations
// ========================================
phase('Research')

const researchBatch1 = await parallel([
  () => agent(
    'Read these files and extract the output duplication prevention pattern:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/display.py (how does hermes prevent streaming output from being printed twice?)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (find _apply_event_type method, especially text_end and thinking_delta handlers)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/stream_handler.py (how does StreamingThinkParser work?)\n\n' +
    'Output:\n' +
    '1. In hermes, how is streaming output handled to avoid duplication?\n' +
    '2. In GrassFlow repl.py, identify exactly where content gets printed AND added to output list (the duplication root cause)\n' +
    '3. What is the pattern for _stream_collected_text and how should it interact with add_output?',
    { label: 'research-output-dup' }
  ),
  () => agent(
    'Read these files and extract the thinking/reasoning display pattern:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/display.py (search for thinking, reasoning, collapsed, expand, fold)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/repl.py (search for reasoning_effort, thinking display toggle)\n' +
    '- E:/opencode-desktop/opencode-dev/opencode-dev/packages/tui/src/ (search for thinking, collapsed, fold in TUI components)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (current thinking display code, _thinking_buf, _thinking_box_opened)\n\n' +
    'Output:\n' +
    '1. How does hermes implement thinking process folding? (collapsed vs full mode)\n' +
    '2. How does opencode implement thinking folding? (default collapsed, click to expand?)\n' +
    '3. What changes are needed in GrassFlow repl.py to support collapsed/expanded thinking?',
    { label: 'research-thinking-fold' }
  ),
  () => agent(
    'Read these files and extract the tool call folding/display pattern:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/display.py (search for tool_call, tool_result, fold, collapse)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/stream_handler.py (tool call rendering)\n' +
    '- E:/opencode-desktop/opencode-dev/opencode-dev/packages/tui/src/ (search for tool call display, folding)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (current tool call handling in _apply_event_type)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/stream_handler.py (tool call fields)\n\n' +
    'Output:\n' +
    '1. How does hermes display tool calls? Is it foldable?\n' +
    '2. How does opencode display tool calls? Is it foldable?\n' +
    '3. What changes are needed in GrassFlow to make tool calls foldable?',
    { label: 'research-tool-fold' }
  ),
])

const researchBatch2 = await parallel([
  () => agent(
    'Read these files and extract test patterns:\n' +
    '- E:/opencode-desktop/GrassFlow/tests/ (list all test files, read test_streaming.py or any streaming-related test)\n' +
    '- E:/opencode-desktop/GrassFlow/tests/ (read test_agent_loop.py or test_repl.py if exists)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/stream_handler.py (current implementation)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/agent_loop.py (current implementation, focus on process_streaming)\n\n' +
    'Output:\n' +
    '1. What test patterns does the project use? (pytest, unittest, fixtures?)\n' +
    '2. What streaming edge cases should be tested? (empty delta, think token counting, tool call parsing, code blocks)\n' +
    '3. What REPL integration scenarios should be tested? (multi-turn, tool calls, history management)',
    { label: 'research-tests' }
  ),
  () => agent(
    'Read these files and extract context compression pattern:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/context_manager.py (context window management)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/agent/prompt_builder.py (how compression integrates with prompt building)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/context_compressor.py (current implementation)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (search for compressor, compress, context -- how is it currently used?)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/agent_loop.py (how does agent loop handle context?)\n\n' +
    'Output:\n' +
    '1. How does hermes integrate context compression into the REPL/agent loop?\n' +
    '2. What is the current state of GrassFlow context_compressor.py? (token detection, summarization)\n' +
    '3. Where exactly should compression be triggered in GrassFlow? (before LLM call? on threshold?)',
    { label: 'research-compression' }
  ),
  () => agent(
    'Read these files and extract MCP transport patterns:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/tools/mcp_tool.py (MCP client with HTTP/SSE transport)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/mcp_integration.py (current stdio-only implementation)\n' +
    '- E:/opencode-desktop/GrassFlow/core/mcp_client.py (core MCP client)\n\n' +
    'Output:\n' +
    '1. How does hermes implement HTTP and SSE transports for MCP?\n' +
    '2. What is the current GrassFlow MCP transport architecture?\n' +
    '3. What classes/functions need to be added for HTTP and SSE support?',
    { label: 'research-mcp-transport' }
  ),
])

// ========================================
// Phase 2: Implement — 7 parallel agents in worktrees
// ========================================
phase('Implement')

const implResults = await parallel([
  () => agent(
    'Fix output duplication in GrassFlow TUI.\n\n' +
    'PROBLEM: Thinking content and response text are displayed twice in the CLI. The root cause is in tui/repl.py _apply_event_type():\n' +
    '- thinking_delta: prints via cprint() AND accumulates in _thinking_buf\n' +
    '- text (streaming): prints via _emit_stream_text() AND accumulates in _stream_collected_text\n' +
    '- text_end: calls add_output() which ALSO prints the content again\n\n' +
    'FIX APPROACH:\n' +
    '1. In _apply_event_type, text_end handler: do NOT print the content again. Only add to _conversation_history and self.output (for history). The streaming text was already printed by _emit_stream_text().\n' +
    '2. In _apply_event_type, thinking_delta handler: do NOT print thinking tokens directly. Only accumulate in _thinking_buf. Print the thinking block ONCE when thinking_end arrives.\n' +
    '3. Ensure _emit_stream_text() is the ONLY place where response text gets printed during streaming.\n' +
    '4. Ensure _close_thinking_block() is the ONLY place where thinking content gets printed.\n\n' +
    'CRITICAL: The _conversation_history list is the single source of truth for LLM context. self.output is for display only. Do NOT merge them.\n\n' +
    'Read tui/repl.py first to understand the current flow, then make targeted edits.',
    { label: 'fix-output-dup', isolation: 'worktree' }
  ),
  () => agent(
    'Add thinking process folding to GrassFlow TUI.\n\n' +
    'CURRENT STATE: Thinking is displayed in "full" mode only (box-drawing characters, all tokens printed).\n\n' +
    'REQUIREMENTS:\n' +
    '1. Default display mode should be "collapsed" -- show only a summary line like "💭 Thought for 2.3s (150 tokens)"\n' +
    '2. When display mode is "full", show the thinking content with box-drawing characters (current behavior)\n' +
    '3. /think command should support: /think on|off|full|collapsed\n' +
    '4. Session metadata stores {"enabled": true, "effort": "medium", "display": "collapsed"} by default\n\n' +
    'IMPLEMENTATION:\n' +
    '1. In tui/repl.py, modify _close_thinking_block():\n' +
    '   - If display == "collapsed": print summary line with duration and token count\n' +
    '   - If display == "full": print the box-drawing block (current behavior)\n' +
    '2. In tui/repl.py, modify _apply_event_type thinking_delta handler:\n' +
    '   - If display == "collapsed": accumulate in _thinking_buf but do NOT print\n' +
    '   - If display == "full": print tokens as they arrive (current behavior)\n' +
    '3. In tui/slash_commands.py, update /think command to handle full|collapsed subcommands\n' +
    '4. Update default session metadata to use "collapsed" display\n\n' +
    'Read tui/repl.py and tui/slash_commands.py first, then make targeted edits.',
    { label: 'fix-thinking-fold', isolation: 'worktree' }
  ),
  () => agent(
    'Add tool call folding to GrassFlow TUI.\n\n' +
    'CURRENT STATE: Tool calls are printed inline with full details, not foldable.\n\n' +
    'REQUIREMENTS:\n' +
    '1. Tool call should show a summary line: "🔧 tool_name(args...)"\n' +
    '2. Tool result should show a summary: "✅ tool_name → result_preview" or "❌ tool_name → error"\n' +
    '3. Tool output should be truncated to ~200 chars by default\n' +
    '4. A /tools command or config option to toggle verbose/compact tool display\n\n' +
    'IMPLEMENTATION:\n' +
    '1. In tui/repl.py, modify _apply_event_type tool_call handler:\n' +
    '   - Print compact summary line instead of full JSON\n' +
    '   - Format: "🔧 tool_name" with args preview (truncated)\n' +
    '2. In tui/repl.py, modify _apply_event_type tool_result handler:\n' +
    '   - Print compact result: "✅ tool_name → first_line_of_result" (truncated to 200 chars)\n' +
    '   - On error: "❌ tool_name → error_message"\n' +
    '3. Add _tool_verbose flag (default False) to control verbose/compact mode\n' +
    '4. Ensure full tool output is still stored in _conversation_history for LLM context\n\n' +
    'Read tui/repl.py and tui/stream_handler.py first, then make targeted edits.',
    { label: 'fix-tool-fold', isolation: 'worktree' }
  ),
  () => agent(
    'Write streaming output unit tests for GrassFlow.\n\n' +
    'FILES TO TEST:\n' +
    '- tui/stream_handler.py (StreamingThinkParser, code block detection, tool_call field handling)\n' +
    '- tui/agent_loop.py (process_streaming event handling)\n\n' +
    'TEST FILE: Create tests/test_streaming_output.py\n\n' +
    'TEST CASES TO COVER:\n' +
    '1. StreamingThinkParser:\n' +
    '   - Parse thinking tokens: "<think>\\ntoken1\\ntoken2\\n" → tokens extracted\n' +
    '   - Nested think tags: "<think>outer <think>inner" → handled correctly\n' +
    '   - Flush without closing tag → partial content returned\n' +
    '   - Empty think block → no crash\n' +
    '2. Code block detection:\n' +
    '   - "```python\\ncode\\n```" → code_block_start, code, code_end events\n' +
    '   - Nested code blocks → handled correctly\n' +
    '   - Unclosed code block → no crash\n' +
    '3. Tool call parsing:\n' +
    '   - tool_call event with function name and arguments\n' +
    '   - tool_result event with success/error\n' +
    '   - tool_call with missing fields → graceful handling\n' +
    '4. Edge cases:\n' +
    '   - Empty delta → no event emitted\n' +
    '   - Very long token → handled without overflow\n' +
    '   - Special characters in tokens → no crash\n\n' +
    'Read the existing test files in tests/ first to match the project test style (pytest, fixtures).',
    { label: 'test-streaming', isolation: 'worktree' }
  ),
  () => agent(
    'Write REPL integration tests for GrassFlow.\n\n' +
    'FILE TO TEST: tui/repl.py\n\n' +
    'TEST FILE: Create tests/test_repl_integration.py\n\n' +
    'TEST CASES TO COVER:\n' +
    '1. History management:\n' +
    '   - User message added to _conversation_history\n' +
    '   - Assistant response added to _conversation_history\n' +
    '   - History does not contain duplicates\n' +
    '   - _build_history() returns correct format\n' +
    '2. Session metadata:\n' +
    '   - Thinking metadata default: enabled=true, effort=medium, display=collapsed\n' +
    '   - Metadata persisted across turns\n' +
    '3. System prompt construction:\n' +
    '   - _get_system_prompt() includes AGENTS.md content\n' +
    '   - _get_system_prompt() includes skills prompt\n' +
    '   - _get_system_prompt() includes thinking instructions\n' +
    '4. Slash command dispatch:\n' +
    '   - /think on|off|full|collapsed → metadata updated\n' +
    '   - /clear → history cleared\n' +
    '   - /model → model changed\n' +
    '5. Multi-turn conversation:\n' +
    '   - 3+ turns without history corruption\n' +
    '   - Tool call round-trip (user → assistant with tool_call → tool_result → assistant response)\n\n' +
    'Read tui/repl.py and existing tests first. Use pytest with mocking for LLM calls.',
    { label: 'test-repl', isolation: 'worktree' }
  ),
  () => agent(
    'Integrate context compression into GrassFlow REPL.\n\n' +
    'CURRENT STATE: tui/context_compressor.py exists but is NOT integrated into the REPL.\n\n' +
    'IMPLEMENTATION:\n' +
    '1. Read tui/context_compressor.py to understand its API (token detection, summarization)\n' +
    '2. Read tui/repl.py to find where to integrate:\n' +
    '   - Before calling agent_integration.process_streaming(), check token count\n' +
    '   - If token count exceeds threshold (e.g., 80k tokens), compress older messages\n' +
    '   - Keep the last N messages uncompressed, summarize older ones\n' +
    '3. In tui/repl.py _handle_agent_message():\n' +
    '   - Before passing history to agent, call compressor.check_and_compress()\n' +
    '   - If compression triggered, update _conversation_history with compressed version\n' +
    '   - Show a message: "📝 Context compressed (X tokens → Y tokens)"\n' +
    '4. Configuration:\n' +
    '   - Add compress_threshold to session metadata (default: 80000 tokens)\n' +
    '   - Add /compress command to manually trigger compression\n\n' +
    'CRITICAL: Do NOT break the existing _conversation_history flow. Compression should be transparent.\n\n' +
    'Read all relevant files first, then make targeted edits.',
    { label: 'fix-compression', isolation: 'worktree' }
  ),
  () => agent(
    'Add HTTP and SSE transport support to GrassFlow MCP client.\n\n' +
    'CURRENT STATE: tui/mcp_integration.py only supports stdio transport.\n\n' +
    'IMPLEMENTATION:\n' +
    '1. Read tui/mcp_integration.py to understand current architecture\n' +
    '2. Read core/mcp_client.py for protocol details\n' +
    '3. Add HTTP transport class:\n' +
    '   - MCPHTTPTransport: sends JSON-RPC via HTTP POST, receives response\n' +
    '   - Support for custom headers (Authorization, etc.)\n' +
    '   - Timeout handling\n' +
    '4. Add SSE transport class:\n' +
    '   - MCPSSETransport: connects to SSE endpoint for server-initiated messages\n' +
    '   - Support for event stream parsing\n' +
    '   - Reconnection handling\n' +
    '5. Update MCPManager to auto-detect transport type from config:\n' +
    '   - "command" field → stdio transport\n' +
    '   - "url" field → HTTP transport\n' +
    '   - "sse_url" field → SSE transport\n' +
    '6. Update config format to support transport selection:\n' +
    '   {"mcpServers": {"name": {"url": "http://...", "transport": "http"}}}\n\n' +
    'Read the reference implementation in hermes first:\n' +
    'E:/opencode-desktop/hermes-agent-main/hermes-agent-main/tools/mcp_tool.py',
    { label: 'fix-mcp-transport', isolation: 'worktree' }
  ),
])

// ========================================
// Phase 3: Merge — Merge all worktree branches
// ========================================
phase('Merge')

const branches = implResults.filter(Boolean).map((_, i) => {
  const labels = ['fix-output-dup', 'fix-thinking-fold', 'fix-tool-fold', 'test-streaming', 'test-repl', 'fix-compression', 'fix-mcp-transport']
  return labels[i]
}).filter(Boolean)

log('Merging ' + branches.length + ' worktree branches...')

await agent(
  'Merge all worktree branches into master. The branches are:\n' +
  branches.map(b => '- ' + b).join('\n') + '\n\n' +
  'Steps:\n' +
  '1. For each branch, do: git merge <branch> --no-edit\n' +
  '2. If conflicts, resolve them. Priority: keep changes from both sides when possible.\n' +
  '3. If a branch has no commits (identical to master), skip it.\n' +
  '4. After all merges, verify the code compiles: python -c "import tui.repl; import tui.stream_handler; import tui.mcp_integration; print(\'OK\')"',
  { label: 'merge-all' }
)

// ========================================
// Phase 4: Bug Hunt — 4 agents hunting bugs
// ========================================
phase('Bug Hunt')

const bugs = await parallel([
  () => agent(
    'Hunt for bugs in the output display system.\n\n' +
    'FILES TO AUDIT:\n' +
    '- tui/repl.py (_apply_event_type, _emit_stream_text, _close_thinking_block, add_output)\n' +
    '- tui/stream_handler.py (StreamingThinkParser, all event emission)\n\n' +
    'CHECK FOR:\n' +
    '1. Any remaining path where content gets printed twice\n' +
    '2. Thinking content leaked into response text\n' +
    '3. Response text leaked into thinking content\n' +
    '4. _stream_collected_text not cleared between turns\n' +
    '5. _thinking_buf not cleared between turns\n' +
    '6. add_output called with content that was already streamed\n' +
    '7. Race conditions in async streaming\n\n' +
    'For each bug found, output: file, line number, description, severity (critical/high/medium/low)',
    { label: 'hunt-display' }
  ),
  () => agent(
    'Hunt for bugs in the folding and compression systems.\n\n' +
    'FILES TO AUDIT:\n' +
    '- tui/repl.py (thinking collapsed/expanded logic, tool call compact/verbose logic)\n' +
    '- tui/slash_commands.py (/think command, /tools command)\n' +
    '- tui/context_compressor.py (compression logic)\n\n' +
    'CHECK FOR:\n' +
    '1. Thinking collapsed mode still showing content (not just summary)\n' +
    '2. Thinking full mode not showing content\n' +
    '3. Tool call compact mode showing too much or too little\n' +
    '4. Context compression corrupting conversation history\n' +
    '5. Compression triggered at wrong thresholds\n' +
    '6. Compression summary losing important context\n' +
    '7. /think and /tools command edge cases (no args, invalid args)\n\n' +
    'For each bug found, output: file, line number, description, severity',
    { label: 'hunt-fold-compress' }
  ),
  () => agent(
    'Hunt for bugs in the test suites.\n\n' +
    'FILES TO AUDIT:\n' +
    '- tests/test_streaming_output.py (new streaming tests)\n' +
    '- tests/test_repl_integration.py (new REPL tests)\n\n' +
    'CHECK FOR:\n' +
    '1. Tests that pass but test the wrong thing (false positives)\n' +
    '2. Missing edge cases\n' +
    '3. Tests that depend on implementation details (brittle)\n' +
    '4. Incorrect mocking (mocking the wrong thing)\n' +
    '5. Tests that would fail in CI (async issues, resource leaks)\n' +
    '6. Duplicate test coverage with existing tests\n\n' +
    'Also run: cd E:/opencode-desktop/GrassFlow && .venv/Scripts/python -m pytest tests/test_streaming_output.py tests/test_repl_integration.py -v\n\n' +
    'For each bug found, output: file, line number, description, severity',
    { label: 'hunt-tests' }
  ),
  () => agent(
    'Hunt for bugs in the MCP transport layer.\n\n' +
    'FILES TO AUDIT:\n' +
    '- tui/mcp_integration.py (HTTP/SSE transport classes)\n' +
    '- core/mcp_client.py (protocol client)\n\n' +
    'CHECK FOR:\n' +
    '1. HTTP transport: missing error handling, timeout issues\n' +
    '2. SSE transport: reconnection logic, event parsing\n' +
    '3. Transport auto-detection: edge cases in config parsing\n' +
    '4. JSON-RPC message framing: incomplete messages, encoding issues\n' +
    '5. Resource cleanup: connections not closed on error\n' +
    '6. Security: missing auth headers, credential exposure in logs\n\n' +
    'For each bug found, output: file, line number, description, severity',
    { label: 'hunt-mcp' }
  ),
])

// ========================================
// Phase 5: Bug Fix — Fix all found bugs
// ========================================
phase('Bug Fix')

const allBugs = bugs.filter(Boolean).flatMap((b, i) => {
  if (typeof b === 'string') return [{ report: b, agent: i }]
  return []
})

log('Found bugs from ' + allBugs.length + ' hunt agents. Fixing...')

await parallel(
  allBugs.map(b => () => agent(
    'Fix the following bugs found during audit:\n\n' +
    b.report + '\n\n' +
    'For each bug:\n' +
    '1. Read the relevant file\n' +
    '2. Understand the bug\n' +
    '3. Apply the minimal fix\n' +
    '4. Verify the fix does not break other functionality\n' +
    '5. Commit the fix',
    { label: 'fix-bugs-' + b.agent, isolation: 'worktree' }
  ))
)

// Final merge of bug fix branches
await agent(
  'Merge all bug fix branches into master.\n' +
  'Steps:\n' +
  '1. git merge <branch> --no-edit for each branch\n' +
  '2. Resolve conflicts if any\n' +
  '3. Run full test suite: .venv/Scripts/python -m pytest tests/ -v\n' +
  '4. Report final status',
  { label: 'merge-bugfixes' }
)
