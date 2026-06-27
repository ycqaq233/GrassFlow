export const meta = {
  name: 'fix-4phase',
  description: '4-phase workflow: Learn hermes → Diagnose GrassFlow → Validate against hermes → Fix',
  phases: [
    { title: 'Learn from Hermes', detail: 'Read hermes source, produce dev suggestions with code' },
    { title: 'Diagnose GrassFlow', detail: 'Read GrassFlow source, find bugs, propose fixes' },
    { title: 'Validate against Hermes', detail: 'Check fix proposals against hermes actual code' },
    { title: 'Fix', detail: 'Implement validated fixes' },
  ],
}

// ========================================
// Phase 1: Learn from Hermes
// Each agent reads hermes source and produces
// concrete suggestions with actual code snippets
// ========================================
phase('Learn from Hermes')

const learnResults = await parallel([
  () => agent(
    'Read hermes skills system and produce development suggestions for GrassFlow.\n\n' +
    'READ THESE FILES COMPLETELY (every line matters):\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/agent/skill_commands.py\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/agent/prompt_builder.py\n\n' +
    'For each file, extract:\n' +
    '1. The EXACT function signatures and their full implementation (with line numbers)\n' +
    '2. How skills are discovered and registered as /name commands\n' +
    '3. How skill content is injected into the agent context (system prompt? user message?)\n' +
    '4. How the system prompt lists available skills\n\n' +
    'Output format:\n' +
    '## skill_commands.py\n' +
    '```python\n' +
    '# line 348-415: scan_skill_commands()\n' +
    'def scan_skill_commands(...):\n' +
    '    <FULL CODE>\n' +
    '```\n\n' +
    '## Development suggestions for GrassFlow:\n' +
    '- Suggestion 1: <what to implement> (reference: hermes line XXX)\n' +
    '- Suggestion 2: ...',
    { label: 'learn-skills' }
  ),
  () => agent(
    'Read hermes MCP tool system and produce development suggestions.\n\n' +
    'READ THESE FILES COMPLETELY:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/tools/mcp_tool.py (search for register, system_prompt, tool_registry)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/agent/prompt_builder.py (search for mcp, available_tools)\n\n' +
    'Extract:\n' +
    '1. How MCP tools are registered in the tool registry (exact code)\n' +
    '2. How MCP tools are listed in the system prompt (exact code)\n' +
    '3. How MCP servers are started and tools discovered (exact code)\n\n' +
    'Output format: same as above — full code snippets with line numbers + suggestions.',
    { label: 'learn-mcp' }
  ),
  () => agent(
    'Read hermes approval system and produce development suggestions.\n\n' +
    'READ THESE FILES COMPLETELY:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/approval.py\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/agent/permission_manager.py\n\n' +
    'Extract:\n' +
    '1. The EXACT approval callback implementation (how it shows prompt, reads input, works under patch_stdout)\n' +
    '2. How permission modes work (manual/auto)\n' +
    '3. How session approvals and permanent approvals are tracked\n\n' +
    'Output format: full code snippets with line numbers + suggestions.',
    { label: 'learn-approval' }
  ),
  () => agent(
    'Read hermes tab completion system and produce development suggestions.\n\n' +
    'READ THESE FILES COMPLETELY:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/completers.py\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/repl.py (search for completer, PromptSession, Buffer)\n\n' +
    'Extract:\n' +
    '1. The EXACT completer class implementation\n' +
    '2. How the completer is registered with PromptSession/Buffer\n' +
    '3. How Tab key triggers completion\n\n' +
    'Output format: full code snippets with line numbers + suggestions.',
    { label: 'learn-tab' }
  ),
])

// ========================================
// Phase 2: Diagnose GrassFlow
// Each agent reads GrassFlow code and finds bugs
// ========================================
phase('Diagnose GrassFlow')

const diagResults = await parallel([
  () => agent(
    'Diagnose GrassFlow skills and MCP system.\n\n' +
    'READ THESE FILES COMPLETELY:\n' +
    '- E:/opencode-desktop/GrassFlow/tui/slash_commands.py (register_skill_commands, _cmd_skill_load)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (_get_system_prompt, _handle_slash_command)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/agent_integration.py (init_agent_loop, MCP section)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/mcp_integration.py (MCPManager.start_servers)\n\n' +
    'For each file, find:\n' +
    '1. What code exists for skills registration? Is it correct?\n' +
    '2. What code exists for MCP startup? Is it actually called?\n' +
    '3. What does _get_system_prompt() include? Does it list skills and MCP tools?\n\n' +
    'Output format:\n' +
    '## Bug 1: <description>\n' +
    '- File: <path>:<line>\n' +
    '- Current code: <code>\n' +
    '- Problem: <what\'s wrong>\n' +
    '- Proposed fix: <what to change>',
    { label: 'diag-skills-mcp' }
  ),
  () => agent(
    'Diagnose GrassFlow approval and tab completion.\n\n' +
    'READ THESE FILES COMPLETELY:\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (_setup_approval_callback, PromptSession creation, key bindings)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/slash_commands.py (SlashCommandCompleter class)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/layout.py (BufferControl, key bindings)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/permission_handler.py (PermissionHandler)\n\n' +
    'For each, find:\n' +
    '1. Approval: how is the callback implemented? Does it work under patch_stdout?\n' +
    '2. Tab: how is the completer registered? Is complete_while_typing=True?\n' +
    '3. What\'s the exact code that\'s broken?\n\n' +
    'Output format: same as above — bugs with file:line, current code, problem, proposed fix.',
    { label: 'diag-approval-tab' }
  ),
])

// ========================================
// Phase 3: Validate against Hermes
// Each agent takes diag proposals and checks them
// against hermes actual code to produce final plan
// ========================================
phase('Validate against Hermes')

const validateResults = await parallel([
  () => agent(
    'Validate skills/MCP fix proposals against hermes source code.\n\n' +
    'DIAGNOSIS REPORT:\n' +
    diagResults[0] + '\n\n' +
    'Now READ the actual hermes code to validate each proposed fix:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/agent/skill_commands.py\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/tools/mcp_tool.py\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/agent/prompt_builder.py\n\n' +
    'For each proposed fix:\n' +
    '1. Does hermes do it this way? If not, how does hermes do it?\n' +
    '2. Is the proposed fix technically correct?\n' +
    '3. What\'s the FINAL fix (incorporating hermes patterns)?\n\n' +
    'Output format:\n' +
    '## Final Fix 1: <description>\n' +
    '- File: <path>\n' +
    '- Change: <exact code change>\n' +
    '- Hermes reference: <hermes file:line>',
    { label: 'validate-skills-mcp' }
  ),
  () => agent(
    'Validate approval/tab fix proposals against hermes source code.\n\n' +
    'DIAGNOSIS REPORT:\n' +
    diagResults[1] + '\n\n' +
    'Now READ the actual hermes code to validate each proposed fix:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/approval.py\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/completers.py\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/repl.py\n\n' +
    'For each proposed fix:\n' +
    '1. Does hermes do it this way?\n' +
    '2. Is the proposed fix correct?\n' +
    '3. What\'s the FINAL fix?\n\n' +
    'Output format: same as above — final fixes with hermes references.',
    { label: 'validate-approval-tab' }
  ),
])

// ========================================
// Phase 4: Fix
// Each agent implements the validated fixes
// ========================================
phase('Fix')

await parallel([
  () => agent(
    'Implement the validated skills/MCP fixes.\n\n' +
    'FINAL FIX PLAN:\n' +
    validateResults[0] + '\n\n' +
    'Implement each fix exactly as specified.\n' +
    'Read the target file first, then apply the change.\n' +
    'After each file change: git add <file>\n' +
    'After all changes: git commit -m "fix: skills/MCP system"\n\n' +
    'CRITICAL: You MUST commit your changes. Do NOT leave uncommitted files in the worktree.',
    { label: 'fix-skills-mcp', isolation: 'worktree' }
  ),
  () => agent(
    'Implement the validated approval/tab fixes.\n\n' +
    'FINAL FIX PLAN:\n' +
    validateResults[1] + '\n\n' +
    'Implement each fix exactly as specified.\n' +
    'Read the target file first, then apply the change.\n' +
    'After each file change: git add <file>\n' +
    'After all changes: git commit -m "fix: approval and tab completion"\n\n' +
    'CRITICAL: You MUST commit your changes.',
    { label: 'fix-approval-tab', isolation: 'worktree' }
  ),
])

// ========================================
// Final: Merge
// ========================================
phase('Merge')

await agent(
  'Merge all worktree branches into master.\n\n' +
  'Steps:\n' +
  '1. List worktrees: ls .claude/worktrees/\n' +
  '2. For EACH worktree:\n' +
  '   a. Check for uncommitted: git -C <path> status --short\n' +
  '   b. If uncommitted: cd <path> && git add -A && git commit -m "fix: uncommitted"\n' +
  '   c. Check for unique commits: git -C <path> log --oneline master..HEAD\n' +
  '   d. If unique: git merge <branch> --no-edit\n' +
  '3. Verify: python -c "from tui.repl import GrassFlowREPL; print(\'OK\')"',
  { label: 'merge-all' }
)
