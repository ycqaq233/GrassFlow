export const meta = {
  name: 'fix-history-thinking',
  description: 'Fix conversation history duplication and thinking mode not working',
  phases: [
    { title: 'Study', detail: '5 agents study history building, thinking chain, hermes patterns' },
    { title: 'Design', detail: 'Design fixes based on findings' },
    { title: 'Implement', detail: '4 agents implement fixes in parallel' },
    { title: 'Verify', detail: 'Verify all changes' },
  ],
}

// Phase 1: Study
phase('Study')

const [historyReport, thinkingChainReport, hermesHistoryReport, hermesThinkingReport, opencodeReport] = await parallel([
  () => agent(
    `Diagnose the conversation history bug. The user reports that the 4th message produced a response that answered ALL previous questions, suggesting the LLM received duplicate messages.

Read these files and trace the history building:
1. tui/repl.py -- find _build_history() method, trace how it builds the message list
2. tui/repl.py -- find _handle_agent_message() and _run_agent_loop_async(), trace what history is passed to agent
3. tui/repl.py -- find add_output() method, trace how messages are stored in self.output
4. tui/agent_integration.py -- find process_streaming() and process_in_background(), trace how history is forwarded
5. tui/agent_loop.py -- find process_streaming(), trace how conversation_history is used to build the messages list for the LLM call

The key question: does _build_history() return ALL previous messages including the current user message? If so, and if the agent_loop also adds the user message again, the LLM would see duplicates.

Also check: is the session message persistence (add_user_message/add_assistant_message) interfering with the history? Does the session DB get loaded and merged into the in-memory output list?

Report the EXACT flow: user types message -> where stored -> how built into history -> how passed to LLM.`,
    { label: 'study:history', phase: 'Study' }
  ),
  () => agent(
    `Diagnose why thinking mode is not producing visible thinking content. The user sees "Thought (N tokens)" but no actual thinking text was displayed before it.

Read these files:
1. tui/repl.py -- find the thinking_delta handler in _apply_event_type, check if it actually prints content in collapsed vs full mode
2. tui/repl.py -- find _close_thinking_block(), check what it prints
3. tui/repl.py -- find the session metadata initialization, check if thinking display mode defaults
4. tui/agent_loop.py -- find where REASONING_DELTA / THINKING_DELTA events are emitted, check if they are actually fired
5. core/llm_protocol.py -- find OpenAIChatStream.step(), check how reasoning_content deltas are parsed from the API response
6. core/llm.py -- check if the LLM client actually sends reasoning_effort in the request

The key question: is the DeepSeek API actually returning reasoning_content in the response? If not, thinking_delta events would never fire.

Also check: does DeepSeek's API support reasoning_effort? What parameter name does it use?`,
    { label: 'study:thinking-chain', phase: 'Study' }
  ),
  () => agent(
    `Study how hermes handles conversation history to avoid duplication.

Search in E:\\opencode-desktop\\hermes-agent-main:
1. Find how hermes builds the messages list for the LLM call (search for messages, chat_messages, conversation)
2. Find how user messages are stored and retrieved (in-memory list vs database)
3. Find if hermes uses a single source of truth for history (e.g., only in-memory, or only DB)
4. Find how hermes handles the current user message -- is it added to history BEFORE or AFTER the LLM call?
5. Find if hermes has any deduplication logic

Report the exact pattern: where messages live, how they are assembled for the API call, and how duplication is prevented.`,
    { label: 'study:hermes-history', phase: 'Study' }
  ),
  () => agent(
    `Study how hermes handles the thinking/reasoning display, specifically:

1. Search in E:\\opencode-desktop\\hermes-agent-main for how reasoning_content or thinking deltas are parsed from the DeepSeek API response
2. Find if hermes uses a different API endpoint or parameter name for DeepSeek reasoning
3. Find how hermes determines whether to show the reasoning box vs the collapsed summary
4. Find the exact ANSI rendering code for the reasoning box (the box borders, dim text, etc.)
5. Find if hermes has a /reasoning or /think command and what it does

Report: DeepSeek-specific API handling, reasoning event parsing, and rendering approach.`,
    { label: 'study:hermes-thinking', phase: 'Study' }
  ),
  () => agent(
    `Study how opencode handles conversation history and thinking display.

Search in E:\\opencode-desktop\\opencode-dev:
1. Find how opencode builds the messages array for LLM calls -- is it from an in-memory store or database?
2. Find how opencode prevents message duplication
3. Find how opencode handles DeepSeek reasoning_content parsing
4. Find the thinking display component -- how does it show/hide thinking content?

Report the exact patterns used.`,
    { label: 'study:opencode', phase: 'Study' }
  ),
])

log('Study phase complete')

// Phase 2: Design
phase('Design')

const designReport = await agent(
  `Based on these study reports, design fixes for the two bugs.

HISTORY BUG REPORT:
${historyReport}

THINKING CHAIN REPORT:
${thinkingChainReport}

HERMES HISTORY PATTERN:
${hermesHistoryReport}

HERMES THINKING PATTERN:
${hermesThinkingReport}

OPENCODE PATTERN:
${opencodeReport}

Design fixes for:

1. CONVERSATION HISTORY DUPLICATION:
   - Find the root cause of why the 4th message got responses to all previous messages
   - Design a fix that uses a single source of truth for history
   - The fix should match hermes pattern: one in-memory list, user message added BEFORE LLM call, assistant message added AFTER
   - Session DB persistence should be write-only (append), never loaded back into the active history

2. THINKING NOT WORKING:
   - Find why thinking_delta events are not fired
   - Check if DeepSeek API uses a different field name for reasoning (e.g., "reasoning_content" vs "thinking" vs "reasoning")
   - Check if the reasoning_effort parameter is actually sent in the HTTP request
   - Design the fix so thinking works with DeepSeek specifically

For each fix specify: exact file, function, line numbers, what to change.`,
  { label: 'design:fixes', phase: 'Design' }
)

log('Design phase complete')

// Phase 3: Implement
phase('Implement')

const implResults = await parallel([
  // Agent 1: Fix conversation history
  () => agent(
    `Fix the conversation history duplication bug.

DESIGN:
${designReport}

Task:
1. Read tui/repl.py fully -- find _build_history(), _handle_agent_message(), _run_agent_loop_async(), add_output()
2. The fix: _build_history() should return ALL messages from self.output EXCEPT the last user message (which is being sent right now)
3. OR better: follow hermes pattern -- keep a separate self._conversation_history list that is the single source of truth
4. User message gets appended to self._conversation_history BEFORE the LLM call
5. Assistant message gets appended AFTER the LLM response
6. _build_history() returns self._conversation_history (not self.output)
7. self.output is ONLY for display, NOT for history building
8. Session DB persistence (add_user_message/add_assistant_message) stays as write-only, never loaded back

Read the file first. Make minimal changes -- do not rewrite the entire file.`,
    { label: 'fix:history', phase: 'Implement', isolation: 'worktree' }
  ),

  // Agent 2: Fix thinking for DeepSeek
  () => agent(
    `Fix thinking mode for DeepSeek API.

DESIGN:
${designReport}

Task:
1. Read core/llm_protocol.py -- find OpenAIChatStream.step() and how it parses reasoning deltas
2. Read core/llm_protocol.py -- find how reasoning_effort is encoded in the request body
3. DeepSeek API uses "reasoning_content" field in the response delta, NOT "thinking" or "reasoning"
4. Check if OpenAIChatStream.step() correctly handles "reasoning_content" field
5. Check if the request body includes "reasoning_effort" parameter (DeepSeek may not support this -- check)
6. If DeepSeek does not support reasoning_effort as a parameter, remove it from the request to avoid 400 errors
7. Make sure REASONING_START, REASONING_DELTA, REASONING_END events are properly emitted for DeepSeek responses

Read all relevant files before making changes.`,
    { label: 'fix:thinking-deepseek', phase: 'Implement', isolation: 'worktree' }
  ),

  // Agent 3: Fix thinking display
  () => agent(
    `Fix the thinking display so users can see actual thinking content.

DESIGN:
${designReport}

Task:
1. Read tui/repl.py -- find thinking_delta handler and _close_thinking_block()
2. The current default is "collapsed" mode which shows NO thinking content, only a summary
3. Change default display mode to "full" so users can see the thinking process
4. In _close_thinking_block(), the collapsed mode shows "Thought (N tokens)" but the user wants to see the content
5. Also: make sure the thinking box header/footer are properly styled
6. The thinking content should be dim/italic to distinguish from regular output

Read the file first before making changes.`,
    { label: 'fix:thinking-display', phase: 'Implement', isolation: 'worktree' }
  ),

  // Agent 4: Fix /think show command
  () => agent(
    `Fix the /think command to properly show status and handle display toggle.

DESIGN:
${designReport}

Task:
1. Read tui/slash_commands.py -- find _cmd_think() handler
2. Make /think with no args show: current effort level, display mode, and whether thinking is enabled
3. Make /think show toggle between collapsed and full display mode (or show current mode)
4. Make sure changing effort level preserves the display setting
5. Add /think full and /think collapsed as shortcuts for display mode
6. Update the args_hint to include all options

Read the file first before making changes.`,
    { label: 'fix:think-cmd', phase: 'Implement', isolation: 'worktree' }
  ),
])

log('Implementation phase complete')

// Phase 4: Verify
phase('Verify')

const verifyReport = await agent(
  `Verify all changes for conversation history and thinking mode.

Changes made:
${implResults.map((r, i) => `--- Agent ${i+1} ---\n${r}`).join('\n\n')}

Task:
1. Read all modified files: tui/repl.py, tui/slash_commands.py, core/llm_protocol.py, tui/agent_loop.py
2. Verify conversation history: _build_history() does not produce duplicates
3. Verify thinking: reasoning_content deltas are parsed, thinking_delta events fire
4. Verify thinking display: default is "full" mode, content is visible
5. Run: cd E:\\opencode-desktop\\GrassFlow && .venv\\Scripts\\python -m pytest tests/test_repl.py tests/test_llm_protocol.py -q --tb=short
6. Report any issues.`,
  { label: 'verify:all', phase: 'Verify' }
)

return { historyReport, thinkingChainReport, designReport, implResults, verifyReport }
