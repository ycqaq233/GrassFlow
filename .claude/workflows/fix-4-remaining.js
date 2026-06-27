export const meta = {
  name: 'fix-4-remaining',
  description: 'Fix 4 remaining: skill prompt, approval, mcp tools, tab completion',
  phases: [
    { title: 'Fix', detail: '4 agents fix each issue, MUST commit' },
    { title: 'Merge', detail: 'Merge all branches' },
  ],
}

phase('Fix')

await parallel([
  () => agent(
    'Fix skill loading to preserve user prompt text.\n\n' +
    'PROBLEM: When user types `/hello-skill 这个skill说了什么`, the system loads the skill but DROPS the user text "这个skill说了什么".\n\n' +
    'Read tui/slash_commands.py, find _cmd_skill_load function.\n' +
    'The function receives `args` which should be the user text after the skill name.\n\n' +
    'Fix:\n' +
    '1. When /hello-skill 这个skill说了什么 is called:\n' +
    '   - skill_name = "hello-skill"\n' +
    '   - user_text = "这个skill说了什么"\n' +
    '2. Load SKILL.md content\n' +
    '3. Add to _conversation_history:\n' +
    '   - system message: "Skill loaded: hello-skill\\n\\n<SKILL.md content>"\n' +
    '   - user message: user_text (if not empty)\n' +
    '4. If user_text is empty, just load the skill and print confirmation\n' +
    '5. If user_text is not empty, trigger agent response\n\n' +
    'CRITICAL: After making changes, you MUST run:\n' +
    '  git add -A && git commit -m "fix: skill loading preserves user prompt text"',
    { label: 'fix-skill-prompt', isolation: 'worktree' }
  ),
  () => agent(
    'Fix ASK approval to show inline prompt instead of auto-denying.\n\n' +
    'PROBLEM: When shell tool needs approval, it auto-denies without showing the [o]nce/[s]ession/[a]lways/[d]eny prompt.\n\n' +
    'Read tui/repl.py, find _setup_approval_callback.\n' +
    'The previous fix used input() inside run_in_terminal() under patch_stdout, which may not work.\n\n' +
    'Fix approach:\n' +
    '1. Use sys.__stdout__ instead of stdout (bypass patch_stdout)\n' +
    '2. Or use run_in_executor with a separate thread for input\n' +
    '3. The prompt must be visible to the user:\n' +
    '   "⚠️  tool_name: args_preview\\n"\n' +
    '   "  [o]nce | [s]ession | [a]lways | [d]eny\\n"\n' +
    '   "  Choice [o/s/a/D]: "\n' +
    '4. Read user input, return True/False\n\n' +
    'CRITICAL: After making changes, you MUST run:\n' +
    '  git add -A && git commit -m "fix: ASK approval shows inline prompt"',
    { label: 'fix-approval', isolation: 'worktree' }
  ),
  () => agent(
    'Fix MCP tools visibility - register MCP tools in agent tool registry.\n\n' +
    'PROBLEM: MCP servers are configured but AI can\'t see MCP tools. The tools aren\'t registered.\n\n' +
    'Read:\n' +
    '- tui/agent_integration.py (init_agent_loop, MCP initialization)\n' +
    '- tui/mcp_integration.py (MCPManager, how tools are discovered)\n' +
    '- core/tool_registry.py (how tools are registered)\n\n' +
    'Fix:\n' +
    '1. After MCP servers start, discover their tools\n' +
    '2. Register each MCP tool in the tool registry\n' +
    '3. The AI should see MCP tools as available functions\n' +
    '4. Ensure MCP tools are included in the tools list sent to the LLM\n\n' +
    'CRITICAL: After making changes, you MUST run:\n' +
    '  git add -A && git commit -m "fix: register MCP tools in agent tool registry"',
    { label: 'fix-mcp-tools', isolation: 'worktree' }
  ),
  () => agent(
    'Fix tab completion for slash commands.\n\n' +
    'PROBLEM: Typing /h + Tab doesn\'t complete to /help.\n\n' +
    'Read:\n' +
    '- tui/slash_commands.py SlashCommandCompleter (get_completions method)\n' +
    '- tui/repl.py (PromptSession, Buffer creation)\n' +
    '- tui/layout.py (key bindings, BufferControl)\n\n' +
    'The completer is registered but Tab doesn\'t trigger completion.\n' +
    'Possible causes:\n' +
    '1. BufferControl.complete_while_typing is False\n' +
    '2. Tab key not bound to completion\n' +
    '3. Completer.get_completions() not yielding results for partial input\n\n' +
    'Fix:\n' +
    '1. Ensure complete_while_typing=True on BufferControl\n' +
    '2. Ensure the completer handles partial input like "/h" -> ["/help", "/history"]\n' +
    '3. prompt_toolkit Tab completion should work if:\n' +
    '   - Buffer has completer set\n' +
    '   - complete_while_typing=True\n' +
    '   - The Completer yields Completion objects\n\n' +
    'CRITICAL: After making changes, you MUST run:\n' +
    '  git add -A && git commit -m "fix: tab completion for slash commands"',
    { label: 'fix-tab', isolation: 'worktree' }
  ),
])

phase('Merge')

await agent(
  'Merge all worktree branches into master.\n\n' +
  'Steps:\n' +
  '1. List worktrees: ls .claude/worktrees/\n' +
  '2. For EACH worktree, check if it has commits ahead of master:\n' +
  '   git -C .claude/worktrees/<name> log --oneline master..HEAD\n' +
  '3. If it has commits, merge: git merge <branch> --no-edit\n' +
  '4. If it has NO commits, check for uncommitted changes:\n' +
  '   git -C .claude/worktrees/<name> status --short\n' +
  '   If there are uncommitted changes, commit them first:\n' +
  '   cd .claude/worktrees/<name> && git add -A && git commit -m "fix: uncommitted changes"\n' +
  '   Then merge.\n' +
  '5. Verify: python -c "from tui.repl import GrassFlowREPL; print(\'OK\')"',
  { label: 'merge-all' }
)
