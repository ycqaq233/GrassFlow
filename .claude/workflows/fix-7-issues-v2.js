export const meta = {
  name: 'fix-7-issues-v2',
  description: 'Fix 7 issues: skill prompt, approval, webfetch, MCP, system prompt, MCP status, tab completion',
  phases: [
    { title: 'Research', detail: 'Study hermes skill injection, approval, system prompt, tab completion' },
    { title: 'Diagnose', detail: 'Read actual code to find root causes' },
    { title: 'Fix', detail: '7 parallel agents fix each issue' },
    { title: 'Merge', detail: 'Merge and verify' },
  ],
}

// ========================================
// Phase 1: Research
// ========================================
phase('Research')

await parallel([
  () => agent(
    'Study how hermes injects skill content and MCP info into the system prompt.\n\n' +
    'Read:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/agent/prompt_builder.py (build_system_prompt, skills injection, MCP tools injection)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/agent/skill_commands.py (how skill content is sent to agent)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/tools/mcp_tool.py (how MCP tools are exposed to the agent)\n\n' +
    'Find:\n' +
    '1. How does hermes tell the agent about available skills in the system prompt?\n' +
    '2. How does hermes tell the agent about available MCP tools?\n' +
    '3. When a skill is loaded by name, how is its content injected?\n' +
    '4. How does the agent know it can call MCP tools?\n\n' +
    'Output: complete code snippets showing system prompt construction for skills and MCP.',
    { label: 'study-hermes-prompt' }
  ),
  () => agent(
    'Study how hermes tab completion works.\n\n' +
    'Read:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/completers.py (completer classes)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/repl.py (how completer is attached to PromptSession, key bindings for Tab)\n\n' +
    'Find:\n' +
    '1. What completer class does hermes use?\n' +
    '2. How is Tab key bound to trigger completion?\n' +
    '3. How does the completer handle slash commands?\n\n' +
    'Output: complete code of the completer and how it\'s wired up.',
    { label: 'study-hermes-tab' }
  ),
  () => agent(
    'Study how hermes inline approval prompt works in detail.\n\n' +
    'Read:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/approval.py (the full approval flow)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/agent/permission_manager.py (how approval is checked)\n\n' +
    'Find:\n' +
    '1. How does the approval prompt appear inline in the terminal?\n' +
    '2. How does it handle the async nature (tool execution is async, approval is sync user input)?\n' +
    '3. What is the exact prompt format and user input handling?\n\n' +
    'Output: complete code of the approval flow.',
    { label: 'study-hermes-approval' }
  ),
])

// ========================================
// Phase 2: Diagnose
// ========================================
phase('Diagnose')

await parallel([
  () => agent(
    'Diagnose why skill loading doesn\'t include the skill prompt.\n\n' +
    'Read:\n' +
    '- E:/opencode-desktop/GrassFlow/tui/slash_commands.py (find _cmd_skill_load, how skill content is loaded)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/skills_system.py (SkillsManager, how skill content is retrieved)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (how _conversation_history is built and sent to LLM)\n\n' +
    'Check:\n' +
    '1. When /hello-skill is called, does it read the SKILL.md content?\n' +
    '2. Is the skill content added to _conversation_history as a system message?\n' +
    '3. Is the skill content included in the system prompt or as a separate message?\n' +
    '4. Does the LLM actually receive the skill content?\n\n' +
    'Output: exact file:line, what code exists, what\'s missing.',
    { label: 'diag-skill-prompt' }
  ),
  () => agent(
    'Diagnose why ASK approval doesn\'t work (auto-denies).\n\n' +
    'Read:\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (find _setup_approval_callback, the current callback implementation)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/tool_executor.py (where approval is checked)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/permission_handler.py (PermissionHandler)\n\n' +
    'The test.log shows "用户拒绝了工具 \'shell\' 的调用" without showing the inline approval prompt.\n' +
    'Find:\n' +
    '1. Is the approval callback actually set?\n' +
    '2. When the callback runs, does it show the prompt?\n' +
    '3. Or does it auto-deny for some reason?\n\n' +
    'Output: exact file:line, the bug.',
    { label: 'diag-approval' }
  ),
  () => agent(
    'Diagnose why webfetch doesn\'t work and why MCP tools are invisible.\n\n' +
    'Read:\n' +
    '- E:/opencode-desktop/GrassFlow/tools/webfetch.py (how it imports html2text)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/agent_integration.py (how MCP tools are initialized and registered)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (how MCP info is included in system prompt)\n\n' +
    'Check:\n' +
    '1. webfetch imports html2text - is it in .venv or global Python?\n' +
    '2. MCP servers are listed as "not started" - why aren\'t they started?\n' +
    '3. Are MCP tools registered in the tool registry?\n' +
    '4. Does the system prompt mention MCP tools?\n\n' +
    'Output: exact file:line, what\'s broken.',
    { label: 'diag-webfetch-mcp' }
  ),
  () => agent(
    'Diagnose why tab completion doesn\'t work.\n\n' +
    'Read:\n' +
    '- E:/opencode-desktop/GrassFlow/tui/slash_commands.py (SlashCommandCompleter class)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (how completer is passed to PromptSession)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/layout.py (key bindings, is Tab bound?)\n\n' +
    'Check:\n' +
    '1. Is the completer actually passed to PromptSession?\n' +
    '2. Is complete_while_typing=True set?\n' +
    '3. Is Tab key bound to completion in the key bindings?\n' +
    '4. Does the completer return correct completions for partial input like "/h"?\n\n' +
    'Output: exact file:line, what\'s missing.',
    { label: 'diag-tab' }
  ),
])

// ========================================
// Phase 3: Fix — 7 parallel agents
// ========================================
phase('Fix')

await parallel([
  () => agent(
    'Fix skill loading to include skill content in conversation.\n\n' +
    'When user types /hello-skill:\n' +
    '1. Load the SKILL.md content\n' +
    '2. Add it as a system message to _conversation_history:\n' +
    '   {"role": "system", "content": "Skill loaded: hello-skill\\n\\n<skill content>"}\n' +
    '3. Print: "✅ Skill loaded: hello-skill"\n' +
    '4. Trigger agent response with the skill context\n\n' +
    'The key issue: the skill content MUST be in _conversation_history so the LLM sees it.\n' +
    'Read tui/slash_commands.py _cmd_skill_load and tui/repl.py _conversation_history.',
    { label: 'fix-skill-prompt', isolation: 'worktree' }
  ),
  () => agent(
    'Fix ASK approval to actually show the inline prompt.\n\n' +
    'The test.log shows approval is auto-denied without showing the prompt.\n' +
    'Read tui/repl.py _setup_approval_callback and find the bug.\n\n' +
    'The callback should:\n' +
    '1. Check if tool is in _session_approvals → auto-approve\n' +
    '2. Check _permission_mode == "approve" → auto-approve\n' +
    '3. Otherwise, show inline prompt and wait for user input\n\n' +
    'The prompt format (hermes style):\n' +
    '  ⚠️  tool_name: args_preview\n' +
    '  [o]nce | [s]ession | [a]lways | [d]eny\n' +
    '  Choice [o/s/a/D]:\n\n' +
    'CRITICAL: Read the actual current code. The previous fix may have introduced a bug.',
    { label: 'fix-approval', isolation: 'worktree' }
  ),
  () => agent(
    'Fix webfetch to work in the venv environment.\n\n' +
    'The error is "html2text is not installed" but it IS installed in global Python.\n' +
    'The issue: webfetch.py uses importlib or try/except, and the .venv Python can\'t find html2text.\n\n' +
    'Fix options:\n' +
    '1. Add html2text to requirements.txt and install in .venv\n' +
    '2. Or make webfetch fall back to a simple HTML-to-text conversion without html2text\n' +
    '3. Or use requests + re to strip HTML tags as fallback\n\n' +
    'Read tools/webfetch.py to see how it imports html2text.',
    { label: 'fix-webfetch', isolation: 'worktree' }
  ),
  () => agent(
    'Fix MCP tools visibility - AI should know about MCP tools.\n\n' +
    'The MCP servers are "not started" and the AI can\'t find MCP tools.\n\n' +
    'Fix:\n' +
    '1. In tui/agent_integration.py, ensure MCP servers are started during init_agent_loop\n' +
    '2. After MCP tools are discovered, register them in the tool registry\n' +
    '3. In tui/repl.py _get_system_prompt(), add a section listing available MCP tools:\n' +
    '   "## Available MCP Tools\\n- tavily-search: search the web\\n- ..."\n' +
    '4. The AI should see MCP tools as available functions, not just in /mcp output\n\n' +
    'Read tui/agent_integration.py and tui/repl.py.',
    { label: 'fix-mcp-tools', isolation: 'worktree' }
  ),
  () => agent(
    'Add available skills and MCP info to system prompt.\n\n' +
    'The AI doesn\'t know what skills and MCP tools are available.\n' +
    'It should be told in the system prompt.\n\n' +
    'In tui/repl.py _get_system_prompt():\n' +
    '1. Add section "## Available Skills":\n' +
    '   List all discovered skills with name and description\n' +
    '   Tell the AI: "To use a skill, the user will type /skill-name"\n' +
    '2. Add section "## Available MCP Tools":\n' +
    '   List all connected MCP tools with name and description\n' +
    '   Tell the AI: "You can call these tools directly"\n\n' +
    'Read tui/repl.py _get_system_prompt() and tui/skills_system.py.',
    { label: 'fix-system-prompt', isolation: 'worktree' }
  ),
  () => agent(
    'Add MCP startup status to /mcp command.\n\n' +
    'Currently /mcp shows "MCP servers (from config, not started)" without status.\n\n' +
    'Fix tui/slash_commands.py _cmd_mcp():\n' +
    '1. Show each MCP server with its status:\n' +
    '   - ✅ connected (if started successfully)\n' +
    '   - ❌ failed (if startup failed, with error message)\n' +
    '   - ⏳ not started (if not yet started)\n' +
    '2. Get status from MCPManager (tui/mcp_integration.py)\n' +
    '   - MCPManager should track server status (started/failed/error)\n\n' +
    'Read tui/slash_commands.py and tui/mcp_integration.py.',
    { label: 'fix-mcp-status', isolation: 'worktree' }
  ),
  () => agent(
    'Fix tab completion for slash commands.\n\n' +
    'Tab completion should work: typing /h + Tab should complete to /help.\n\n' +
    'Read:\n' +
    '- tui/slash_commands.py SlashCommandCompleter\n' +
    '- tui/repl.py PromptSession creation\n' +
    '- tui/layout.py key bindings\n\n' +
    'The issue might be:\n' +
    '1. Completer not returning completions for partial input\n' +
    '2. Tab key not bound to completion\n' +
    '3. complete_while_typing not enabled\n' +
    '4. completer not passed to PromptSession\n\n' +
    'Fix whatever is broken. prompt_toolkit Tab completion should work out of the box if:\n' +
    '- PromptSession(completer=my_completer, complete_while_typing=True)\n' +
    '- The Completer.get_completions() yields Completion objects',
    { label: 'fix-tab', isolation: 'worktree' }
  ),
])

// ========================================
// Phase 4: Merge
// ========================================
phase('Merge')

await agent(
  'Merge all worktree branches into master.\n' +
  'Steps:\n' +
  '1. List worktree branches: ls .claude/worktrees/\n' +
  '2. For each with unique commits: git merge <branch> --no-edit\n' +
  '3. Resolve conflicts if any\n' +
  '4. Verify: python -c "from tui.repl import GrassFlowREPL; print(\'OK\')"\n' +
  '5. CRITICAL: Make sure ALL worktrees with changes are merged, even if "already up to date"',
  { label: 'merge-all' }
)
