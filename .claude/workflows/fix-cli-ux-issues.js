export const meta = {
  name: 'fix-cli-ux-issues',
  description: 'Fix 8 CLI UX issues: banner, permission toggle, history, skills, status bar, folding, thinking indicator, md rendering',
  phases: [
    { title: 'Research', detail: 'Study hermes permission/history/statusbar/markdown rendering' },
    { title: 'Implement', detail: '8 parallel agents fix each issue' },
    { title: 'Merge', detail: 'Merge worktree branches' },
    { title: 'Verify', detail: 'Test all fixes end-to-end' },
  ],
}

// ========================================
// Phase 1: Research
// ========================================
phase('Research')

await parallel([
  () => agent(
    'Study hermes permission system and approval flow.\n\n' +
    'Read these files:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/agent/permission_manager.py (permission modes: plan/edit/build)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/approval.py (approval callback, user prompt)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/repl.py (permission toggle shortcut key)\n\n' +
    'Find:\n' +
    '1. What are the permission modes? (plan=readonly, edit=editable, build=auto-approve?)\n' +
    '2. How does the approval callback work? (how does user approve/deny a tool call?)\n' +
    '3. Is there a keyboard shortcut to toggle permission mode?\n' +
    '4. How is the current permission mode displayed in the status bar?\n\n' +
    'Output: technical report with file paths, line numbers, code snippets.',
    { label: 'research-permission' }
  ),
  () => agent(
    'Study hermes status bar, history navigation, and markdown rendering.\n\n' +
    'Read these files:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/status_bar.py (status bar content: model, tokens, context)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/repl.py (history navigation, up arrow key)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/display.py (markdown rendering in terminal)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/markdown_renderer.py (if exists, terminal md rendering)\n\n' +
    'Find:\n' +
    '1. What does the status bar show? (model name, token count, context length, etc.)\n' +
    '2. How does up-arrow history navigation work in prompt_toolkit?\n' +
    '3. How does hermes render markdown in the terminal? (colors for ###, **bold**, code blocks)\n' +
    '4. How is token usage tracked and displayed?\n\n' +
    'Output: technical report with file paths, line numbers, code snippets.',
    { label: 'research-statusbar-md' }
  ),
  () => agent(
    'Study hermes skills loading by name.\n\n' +
    'Read these files:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/tools/skills_tool.py (how skills are invoked)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/slash_commands.py (how /skill-name works)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/slash_commands.py (current slash command system)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/skills_system.py (skills discovery and loading)\n\n' +
    'Find:\n' +
    '1. In hermes, how does typing /skill-name load a skill?\n' +
    '2. How does the slash command system dynamically register skill commands?\n' +
    '3. How is the skill content injected into the conversation?\n\n' +
    'Output: technical report with file paths, line numbers.',
    { label: 'research-skills-load' }
  ),
])

// ========================================
// Phase 2: Implement — 8 parallel agents
// ========================================
phase('Implement')

await parallel([
  () => agent(
    'Fix banner blank lines in GrassFlow REPL.\n\n' +
    'PROBLEM: The ASCII art banner has too many blank lines below it, pushing content off screen.\n\n' +
    'Read tui/repl.py and find where the BANNER is printed.\n' +
    'Fix: Remove excessive blank lines after the banner. Keep at most 1 blank line.\n' +
    'The banner should be: ASCII art + 1 blank line + "GrassFlow REPL" + help hint.',
    { label: 'fix-banner', isolation: 'worktree' }
  ),
  () => agent(
    'Add permission mode toggle to GrassFlow REPL.\n\n' +
    'PROBLEM: No way to switch permission modes. shell tool requires approval but no callback.\n\n' +
    'IMPLEMENTATION:\n' +
    '1. In tui/repl.py, add permission mode state: _permission_mode = "ask" (ask/approve/deny)\n' +
    '2. Add Ctrl+P keyboard shortcut to cycle through modes: ask → approve → ask\n' +
    '3. In approval callback (tui/approval.py or where tools are executed):\n' +
    '   - ask mode: prompt user for approval (y/n) in terminal\n' +
    '   - approve mode: auto-approve all tools\n' +
    '   - deny mode: deny all tools\n' +
    '4. Show current permission mode in status bar\n' +
    '5. Add /perm command to toggle permission mode\n\n' +
    'Reference hermes: permission modes are plan(readonly)/edit(can write)/build(auto-approve)\n' +
    'For GrassFlow: use ask(approval needed)/approve(auto)/deny(none) initially.',
    { label: 'fix-permission', isolation: 'worktree' }
  ),
  () => agent(
    'Fix up-arrow history navigation in GrassFlow REPL.\n\n' +
    'PROBLEM: Pressing up arrow does not load previous command.\n\n' +
    'Read tui/layout.py and tui/repl.py to understand the prompt_toolkit setup.\n' +
    'FIX: prompt_toolkit should have FileHistory for persistent command history.\n' +
    'Ensure:\n' +
    '1. prompt_toolkit History object is passed to PromptSession\n' +
    '2. Up/Down arrows navigate history\n' +
    '3. History is persisted to ~/.Grass/history or similar\n\n' +
    'prompt_toolkit FileHistory: from prompt_toolkit.history import FileHistory',
    { label: 'fix-history', isolation: 'worktree' }
  ),
  () => agent(
    'Add skill loading by name to GrassFlow REPL.\n\n' +
    'PROBLEM: /hello-skill does not work. User should be able to type /skill-name to load a skill.\n\n' +
    'IMPLEMENTATION:\n' +
    '1. In tui/slash_commands.py, dynamically register slash commands for each discovered skill\n' +
    '2. When user types /skill-name:\n' +
    '   a. Load the skill content from SKILL.md\n' +
    '   b. Inject the skill instructions into the conversation as a system message\n' +
    '   c. Print a confirmation: "✅ Skill loaded: skill-name"\n' +
    '3. Skills should be auto-discovered from:\n' +
    '   - .grass/skills/*/SKILL.md (project)\n' +
    '   - ~/.Grass/skills/*/SKILL.md (global)\n\n' +
    'Read tui/slash_commands.py to understand the command registration system.\n' +
    'Read tui/skills_system.py to understand skill discovery.',
    { label: 'fix-skills-load', isolation: 'worktree' }
  ),
  () => agent(
    'Enhance status bar in GrassFlow REPL.\n\n' +
    'PROBLEM: Status bar is too basic. Should show: model name, project dir, context length, thinking depth, token usage.\n\n' +
    'Read tui/status_bar.py to understand current implementation.\n\n' +
    'IMPLEMENTATION:\n' +
    '1. Show these fields in the status bar:\n' +
    '   - Model name (from session metadata)\n' +
    '   - Project directory (current working dir, abbreviated)\n' +
    '   - Context length (number of messages in _conversation_history)\n' +
    '   - Thinking depth (current reasoning_effort: off/low/medium/high)\n' +
    '   - Token usage (input + output tokens from agent loop)\n' +
    '   - Permission mode (ask/approve)\n' +
    '2. Update status bar on each agent loop iteration\n' +
    '3. Token count should be extracted from LLM response (usage.total_tokens)\n\n' +
    'Read tui/repl.py to find where token usage is tracked.',
    { label: 'fix-statusbar', isolation: 'worktree' }
  ),
  () => agent(
    'Make thinking and tool calls default to hidden/collapsed with click-to-expand.\n\n' +
    'PROBLEM: Thinking and tool calls are always visible. Should default hidden, clickable to expand.\n\n' +
    'Read tui/repl.py to find thinking display and tool call display code.\n\n' +
    'IMPLEMENTATION:\n' +
    '1. Thinking: default display mode is "collapsed" (show summary line only)\n' +
    '   - Summary: "💭 Thought for Xs (Y tokens)"\n' +
    '   - /think full shows all thinking content\n' +
    '   - /think collapsed hides it\n' +
    '2. Tool calls: default to compact mode\n' +
    '   - Show: "🔧 tool_name" on one line\n' +
    '   - /tools verbose shows full details\n' +
    '   - /tools compact hides details\n' +
    '3. Show thinking mode indicator in output:\n' +
    '   - When thinking mode is ON: show "💭 Thinking: ON (medium)" at start of response\n' +
    '   - When thinking mode is OFF: no indicator\n\n' +
    'Check if the previous workflow already implemented this. If so, verify it works correctly.',
    { label: 'fix-thinking-tools', isolation: 'worktree' }
  ),
  () => agent(
    'Add terminal markdown rendering to GrassFlow REPL.\n\n' +
    'PROBLEM: Terminal shows raw markdown (###, **bold**, etc.) without rendering.\n\n' +
    'IMPLEMENTATION:\n' +
    '1. Create tui/md_renderer.py that converts markdown to colored terminal output:\n' +
    '   - ### headers → bold + different color (e.g., cyan)\n' +
    '   - **bold** → bold text\n' +
    '   - *italic* → italic text\n' +
    '   - `code` → highlighted background\n' +
    '   - ```code blocks``` → boxed with different color\n' +
    '   - - list items → bullet with indent\n' +
    '   - > blockquotes → left border + dim text\n' +
    '   - [links](url) → underlined + URL shown\n' +
    '2. Use Rich library for formatting (already installed)\n' +
    '3. Apply renderer to assistant responses before printing\n' +
    '4. Keep raw markdown in _conversation_history (for LLM context)\n\n' +
    'Check if Rich has a built-in Markdown renderer:\n' +
    'from rich.markdown import Markdown\n' +
    'from rich.console import Console\n' +
    'console = Console()\n' +
    'console.print(Markdown(text))',
    { label: 'fix-md-render', isolation: 'worktree' }
  ),
  () => agent(
    'Fix token usage tracking in GrassFlow REPL.\n\n' +
    'PROBLEM: Token count in status bar stays at 0. Need to track actual token usage.\n\n' +
    'Read tui/repl.py, tui/agent_loop.py, and tui/agent_integration.py.\n\n' +
    'IMPLEMENTATION:\n' +
    '1. In agent_loop.py, extract token usage from LLM response:\n' +
    '   - response.usage.prompt_tokens → input tokens\n' +
    '   - response.usage.completion_tokens → output tokens\n' +
    '   - Accumulate total across all turns\n' +
    '2. Store token counts in session metadata or REPL state\n' +
    '3. Pass token counts to status bar for display\n' +
    '4. Track per-turn and cumulative totals\n\n' +
    'Check how the LLM response exposes usage data in tui/stream_handler.py.',
    { label: 'fix-tokens', isolation: 'worktree' }
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
  '3. Verify: python -c "from tui.repl import GrassFlowREPL; print(\'OK\')"',
  { label: 'merge-ux' }
)

// ========================================
// Phase 4: Verify
// ========================================
phase('Verify')

await agent(
  'Verify all 8 UX fixes work correctly.\n\n' +
  'Run these checks:\n' +
  '1. python -c "from tui.repl import GrassFlowREPL; r = GrassFlowREPL(); print(r._permission_mode)"\n' +
  '   Expected: "ask" (default permission mode)\n' +
  '2. python -c "from tui.md_renderer import render_md; print(render_md(\'### Hello **world**\'))"\n' +
  '   Expected: colored output\n' +
  '3. python -c "from tui.slash_commands import SlashCommandRegistry; print(\'OK\')"\n' +
  '   Expected: no import errors\n' +
  '4. python -c "from tui.status_bar import StatusBar; print(\'OK\')"\n' +
  '   Expected: no import errors\n\n' +
  'If any check fails, fix and re-verify.\n' +
  'Report: PASS/FAIL for each check.',
  { label: 'verify-ux' }
)
