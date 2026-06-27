export const meta = {
  name: 'fix-remaining-5',
  description: 'Fix 5 remaining issues: token count, banner blank lines, permission display, permission popup, webfetch tool',
  phases: [
    { title: 'Diagnose', detail: 'Investigate token count and banner issues' },
    { title: 'Implement', detail: '5 parallel agents fix each issue' },
    { title: 'Merge', detail: 'Merge worktree branches' },
    { title: 'Verify', detail: 'Test all fixes' },
  ],
}

// ========================================
// Phase 1: Diagnose
// ========================================
phase('Diagnose')

await parallel([
  () => agent(
    'Diagnose why token count stays at 0 in the status bar.\n\n' +
    'Read these files:\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (search for token, usage, _total_tokens, status_bar)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/agent_loop.py (search for usage, token, USAGE event)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/status_bar.py (search for token field)\n\n' +
    'Find:\n' +
    '1. Where are tokens counted in the agent loop?\n' +
    '2. Is there a USAGE event that carries token counts?\n' +
    '3. Does the REPL receive and store token counts?\n' +
    '4. Does the status bar read token counts?\n\n' +
    'Output: exact file, line number, and the bug.',
    { label: 'diag-tokens' }
  ),
  () => agent(
    'Diagnose why banner blank lines still exist.\n\n' +
    'Read E:/opencode-desktop/GrassFlow/tui/repl.py\n' +
    'Find the BANNER string and where it is printed.\n' +
    'The BANNER has \\n characters that create blank lines.\n\n' +
    'Output: exact line number and the BANNER string content.',
    { label: 'diag-banner' }
  ),
])

// ========================================
// Phase 2: Implement — 5 parallel agents
// ========================================
phase('Implement')

await parallel([
  () => agent(
    'Fix token count tracking in GrassFlow REPL.\n\n' +
    'Based on diagnosis, the token count stays at 0.\n\n' +
    'Fix the chain: agent_loop extracts usage → yields USAGE event → repl receives → stores → status bar displays.\n\n' +
    'Ensure:\n' +
    '1. agent_loop.py: extract usage.total_tokens from LLM response and yield as USAGE event\n' +
    '2. repl.py: handle USAGE event, accumulate total tokens in self._total_tokens\n' +
    '3. status_bar.py: read self._total_tokens and display in status bar\n' +
    '4. Reset token count on new session\n\n' +
    'Read all three files first, then fix the broken link in the chain.',
    { label: 'fix-tokens', isolation: 'worktree' }
  ),
  () => agent(
    'Fix banner blank lines in GrassFlow REPL.\n\n' +
    'The BANNER string in tui/repl.py still has excessive \\n characters creating blank lines.\n\n' +
    'Fix:\n' +
    '1. Read tui/repl.py and find the BANNER constant\n' +
    '2. Remove all trailing \\n after the ASCII art\n' +
    '3. Keep only: ASCII art + 1 newline + "GrassFlow REPL" + help hint\n' +
    '4. Make sure there are NO blank lines between the ASCII art and the text below it',
    { label: 'fix-banner', isolation: 'worktree' }
  ),
  () => agent(
    'Add permission mode display and popup to GrassFlow REPL.\n\n' +
    'PROBLEMS:\n' +
    '1. Status bar shows permission mode but not prominently enough\n' +
    '2. When toggling permission (Ctrl+P), should show a popup asking user\n\n' +
    'IMPLEMENTATION:\n' +
    '1. In tui/repl.py, when Ctrl+P is pressed:\n' +
    '   - Show a prompt_toolkit popup/dialog asking: "Permission mode: [ask] [approve]"\n' +
    '   - Or simpler: show a bottom toolbar message "Permission mode changed to: approve"\n' +
    '   - Update self._permission_mode\n' +
    '2. In status_bar.py, make permission mode more visible:\n' +
    '   - Use color: ask=yellow, approve=green\n' +
    '   - Show as "[ASK]" or "[APPROVE]" with color\n' +
    '3. Add /perm command that shows current mode and allows changing:\n' +
    '   - /perm → show current mode\n' +
    '   - /perm ask → set to ask mode\n' +
    '   - /perm approve → set to approve mode\n\n' +
    'Read tui/repl.py and tui/slash_commands.py first.',
    { label: 'fix-perm-popup', isolation: 'worktree' }
  ),
  () => agent(
    'Add webfetch built-in tool to GrassFlow.\n\n' +
    'Create a new tool that fetches web content, similar to opencode WebFetch.\n\n' +
    'IMPLEMENTATION:\n' +
    '1. Create tools/webfetch.py:\n' +
    '   - Class WebFetchTool(Tool)\n' +
    '   - name = "webfetch"\n' +
    '   - description = "Fetch a URL and return its content as markdown"\n' +
    '   - Parameters: url (string), prompt (string, optional - what to extract)\n' +
    '   - Uses httpx or requests to fetch the URL\n' +
    '   - Converts HTML to markdown using markdownify or html2text\n' +
    '   - Returns the content (truncated to 10k chars)\n' +
    '   - Permission: ALLOW (safe read-only operation)\n' +
    '2. Register in tools/__init__.py:\n' +
    '   - Add WebFetchTool to the exports\n' +
    '3. Register in core/tool_registry.py:\n' +
    '   - Add WebFetchTool to register_builtin_tools()\n' +
    '4. Update tools/bridge.py if needed\n\n' +
    'Reference implementation:\n' +
    '- Check if httpx is installed: pip list | grep httpx\n' +
    '- Check if markdownify is installed: pip list | grep markdownify\n' +
    '- If not, add to requirements.txt',
    { label: 'add-webfetch', isolation: 'worktree' }
  ),
  () => agent(
    'Fix approval callback for shell tool in GrassFlow REPL.\n\n' +
    'PROBLEM: shell tool requires approval but no callback is set, so it always denies.\n\n' +
    'Read tui/repl.py and tui/approval.py to understand the current approval system.\n\n' +
    'FIX:\n' +
    '1. In tui/repl.py, when initializing the agent loop:\n' +
    '   - Set an approval callback that checks self._permission_mode\n' +
    '   - If mode is "approve": auto-approve all tools\n' +
    '   - If mode is "ask": prompt user in terminal (y/n)\n' +
    '2. The approval callback should be passed to agent_integration or agent_loop\n' +
    '3. For "ask" mode, use prompt_toolkit to show a confirmation:\n' +
    '   - "Approve tool: shell(command)? [y/N]"\n' +
    '   - Default is N (deny)\n' +
    '   - User types y to approve\n\n' +
    'Check how the tool execution pipeline works:\n' +
    'agent_loop → tool_executor → permission check → execute',
    { label: 'fix-approval', isolation: 'worktree' }
  ),
])

// ========================================
// Phase 3: Merge
// ========================================
phase('Merge')

await agent(
  'Merge all worktree branches into master.\n' +
  'Steps:\n' +
  '1. git merge <branch> --no-edit for each branch\n' +
  '2. Resolve conflicts if any\n' +
  '3. Verify imports: python -c "from tui.repl import GrassFlowREPL; from tools.webfetch import WebFetchTool; print(\'OK\')"',
  { label: 'merge-5' }
)

// ========================================
// Phase 4: Verify
// ========================================
phase('Verify')

await agent(
  'Verify all 5 fixes.\n\n' +
  'Run these checks:\n' +
  '1. python -c "from tools.webfetch import WebFetchTool; print(WebFetchTool().name)"\n' +
  '   Expected: "webfetch"\n' +
  '2. python -c "from tui.repl import GrassFlowREPL; print(\'OK\')"\n' +
  '   Expected: no import errors\n' +
  '3. Check BANNER in repl.py has no excessive blank lines\n' +
  '4. Check token tracking chain in agent_loop.py → repl.py → status_bar.py\n\n' +
  'If any check fails, fix and re-verify.',
  { label: 'verify-5' }
)
