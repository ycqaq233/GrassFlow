export const meta = {
  name: 'deep-fix-4-issues',
  description: 'Deep investigation and fix: approval, skills, banner, thinking expand/collapse',
  phases: [
    { title: 'Deep Investigate', detail: 'Read actual code, find real root causes' },
    { title: 'Study Hermes', detail: 'Read hermes implementations for reference' },
    { title: 'Fix', detail: '4 parallel agents fix each issue' },
    { title: 'Merge & Test', detail: 'Merge and run actual REPL test' },
  ],
}

// ========================================
// Phase 1: Deep Investigate — Read actual code
// ========================================
phase('Deep Investigate')

await parallel([
  () => agent(
    'DEEP INVESTIGATION: Why does inline approval not work?\n\n' +
    'Read the ACTUAL current code in these files (not worktrees, the master branch):\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (find _setup_approval_callback, _approval_callback, _permission_mode)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/approval.py (PermissionHandler, resolve_approval)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/tool_executor.py (how tools are executed, where approval is checked)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/agent_loop.py (how tool calls are processed)\n\n' +
    'Trace the FULL path from "agent wants to call shell" to "approval is checked" to "tool executes or is denied":\n' +
    '1. Where does agent_loop receive a tool_call event?\n' +
    '2. Where does it call tool_executor?\n' +
    '3. Where does tool_executor check permissions?\n' +
    '4. Where does it call the approval callback?\n' +
    '5. Is the callback actually set? Is it reachable?\n\n' +
    'Output: exact file:line for each step, and where the chain breaks.',
    { label: 'investigate-approval' }
  ),
  () => agent(
    'DEEP INVESTIGATION: Why can\'t skills be loaded by name?\n\n' +
    'Read the ACTUAL current code:\n' +
    '- E:/opencode-desktop/GrassFlow/tui/slash_commands.py (find how commands are registered, is there dynamic skill registration?)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/skills_system.py (SkillsManager, get_skills_summary, skill discovery)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (how slash commands are dispatched)\n\n' +
    'Check:\n' +
    '1. Is there code that dynamically registers /skill-name commands?\n' +
    '2. When user types /hello-skill, what happens? Does it reach the skills system?\n' +
    '3. How does the slash command dispatch work? Does it have a fallback for unknown commands?\n\n' +
    'Output: exact file:line, what code exists, what\'s missing.',
    { label: 'investigate-skills' }
  ),
  () => agent(
    'DEEP INVESTIGATION: Why are banner blank lines still there?\n\n' +
    'Read E:/opencode-desktop/GrassFlow/tui/repl.py\n' +
    'Find the BANNER constant. Show me the EXACT content of the BANNER string (with escaped newlines).\n' +
    'Also find where it is printed (cprint, print, etc.).\n\n' +
    'Output: exact line number, the BANNER string content, and the print call.',
    { label: 'investigate-banner' }
  ),
  () => agent(
    'DEEP INVESTIGATION: Can thinking be made expandable/collapsible in prompt_toolkit?\n\n' +
    'Read:\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (how thinking is currently displayed - _thinking_buf, _close_thinking_block)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/layout.py (prompt_toolkit layout, is there a way to add clickable regions?)\n\n' +
    'Research prompt_toolkit capabilities:\n' +
    '1. Does prompt_toolkit support clickable text or foldable regions?\n' +
    '2. Can we use mouse events in prompt_toolkit?\n' +
    '3. What about using key bindings to toggle thinking display?\n' +
    '4. Is there a way to show/hide content in the output area?\n\n' +
    'If prompt_toolkit doesn\'t support click-to-expand, what\'s the best alternative?\n' +
    '- Key binding (e.g., Ctrl+T to toggle thinking display)\n' +
    '- Command (/think full / /think collapsed)\n' +
    '- Both\n\n' +
    'Output: what prompt_toolkit can and cannot do, and the best approach.',
    { label: 'investigate-thinking' }
  ),
])

// ========================================
// Phase 2: Study Hermes — Read reference implementations
// ========================================
phase('Study Hermes')

await parallel([
  () => agent(
    'Study hermes approval callback implementation.\n\n' +
    'Read:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/approval.py (full file)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/agent/permission_manager.py (full file)\n\n' +
    'Find:\n' +
    '1. How does hermes set up the approval callback?\n' +
    '2. How does the inline prompt work? (the [o]nce/[s]ession/[a]lways/[d]eny prompt)\n' +
    '3. How does it handle async approval in the REPL event loop?\n' +
    '4. How are session approvals and permanent approvals tracked?\n\n' +
    'Output: complete code of the approval callback function and permission manager.',
    { label: 'study-hermes-approval' }
  ),
  () => agent(
    'Study hermes skills loading by name.\n\n' +
    'Read:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/agent/skill_commands.py (how skills become slash commands)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/slash_commands.py (command dispatch with skill fallback)\n\n' +
    'Find:\n' +
    '1. How does hermes scan skills and register them as /skill-name commands?\n' +
    '2. When user types /skill-name, how does it load and inject the skill?\n' +
    '3. How is the skill content sent to the agent?\n\n' +
    'Output: complete code of skill registration and dispatch.',
    { label: 'study-hermes-skills' }
  ),
])

// ========================================
// Phase 3: Fix — 4 parallel agents
// ========================================
phase('Fix')

await parallel([
  () => agent(
    'Fix inline approval to actually work.\n\n' +
    'Based on investigation, the approval chain is broken. Fix it by following the hermes pattern.\n\n' +
    'The approval flow should be:\n' +
    '1. Agent calls a tool (e.g., shell)\n' +
    '2. tool_executor checks permission → tool needs approval\n' +
    '3. tool_executor calls the approval callback with tool name + args\n' +
    '4. Callback shows inline prompt: ⚠️ shell: <args> / [o]nce [s]ession [a]lways [d]eny\n' +
    '5. User chooses → callback returns True/False\n' +
    '6. Tool executes or is denied\n\n' +
    'CRITICAL: Read the actual code first. Don\'t assume what\'s there.\n' +
    'Fix the broken link in the chain. Make sure the callback is set AND reachable.\n\n' +
    'Files to modify: tui/repl.py, possibly tui/approval.py or tui/tool_executor.py',
    { label: 'fix-approval', isolation: 'worktree' }
  ),
  () => agent(
    'Fix skills loading by name.\n\n' +
    'Based on investigation, dynamic skill command registration may be missing.\n\n' +
    'Implement:\n' +
    '1. In tui/slash_commands.py or tui/repl.py:\n' +
    '   - After skills are discovered, dynamically register /skill-name commands\n' +
    '   - Each skill command loads the SKILL.md content and injects it into the conversation\n' +
    '2. When user types /hello-skill:\n' +
    '   - Find the skill in SkillsManager\n' +
    '   - Read the SKILL.md content\n' +
    '   - Add it as a system message to _conversation_history\n' +
    '   - Print: "✅ Skill loaded: hello-skill"\n' +
    '   - Trigger agent response with the skill context\n\n' +
    'Read the actual code first. Fix what\'s missing.',
    { label: 'fix-skills', isolation: 'worktree' }
  ),
  () => agent(
    'Fix banner blank lines.\n\n' +
    'Read E:/opencode-desktop/GrassFlow/tui/repl.py and find the BANNER.\n' +
    'The BANNER string has \\n characters that create blank lines.\n' +
    'Fix: remove ALL blank lines from the BANNER. Keep only the ASCII art and the text below it.\n' +
    'The BANNER should be printed with cprint and have NO empty lines between the art and the help text.',
    { label: 'fix-banner', isolation: 'worktree' }
  ),
  () => agent(
    'Implement thinking expand/collapse with key binding.\n\n' +
    'prompt_toolkit does NOT support clickable text. Use key bindings instead.\n\n' +
    'Implementation:\n' +
    '1. Add Ctrl+T key binding to toggle thinking display:\n' +
    '   - When thinking is collapsed: Ctrl+T expands it (shows full thinking content)\n' +
    '   - When thinking is expanded: Ctrl+T collapses it (shows summary only)\n' +
    '2. In tui/repl.py:\n' +
    '   - Add self._thinking_expanded: bool = False\n' +
    '   - Store thinking content in self._last_thinking_content: str\n' +
    '   - On Ctrl+T: if expanded, re-print collapsed summary; if collapsed, re-print full content\n' +
    '3. Also ensure /think full and /think collapsed work:\n' +
    '   - /think full → sets display mode to "full" for FUTURE thinking\n' +
    '   - /think collapsed → sets display mode to "collapsed" for FUTURE thinking\n' +
    '   - Ctrl+T → toggles the CURRENT thinking block visibility\n\n' +
    'Read tui/repl.py and tui/layout.py to understand the key binding system.',
    { label: 'fix-thinking', isolation: 'worktree' }
  ),
])

// ========================================
// Phase 4: Merge & Test
// ========================================
phase('Merge & Test')

await agent(
  'Merge all worktree branches into master and test.\n\n' +
  'Steps:\n' +
  '1. git merge <branch> --no-edit for each branch\n' +
  '2. Resolve conflicts\n' +
  '3. Run: python -c "from tui.repl import GrassFlowREPL; print(\'OK\')"\n' +
  '4. Run: python -c "from tui.slash_commands import SlashCommandRegistry; print(\'OK\')"\n' +
  '5. Check BANNER has no blank lines\n' +
  '6. Report results',
  { label: 'merge-test' }
)
