export const meta = {
  name: 'fix-6-issues-v3',
  description: 'Fix 6 issues with hermes reference: skills, MCP, encoding, approval, tab, system prompt',
  phases: [
    { title: 'Study Hermes', detail: 'Read hermes source for each subsystem' },
    { title: 'Diagnose', detail: 'Read GrassFlow code, compare with hermes, find root causes' },
    { title: 'Fix', detail: '6 parallel agents fix each issue' },
    { title: 'Merge', detail: 'Merge and verify' },
  ],
}

// ========================================
// Phase 1: Study Hermes
// ========================================
phase('Study Hermes')

await parallel([
  () => agent(
    'Study hermes: how skills become slash commands and how skill content is injected.\n\n' +
    'Read these files COMPLETELY (not just grep):\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/agent/skill_commands.py\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/slash_commands.py (search for skill, /skill)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/agent/prompt_builder.py (search for skill, system prompt)\n\n' +
    'I need to understand:\n' +
    '1. scan_skill_commands() - how does it scan and register skills as /name commands?\n' +
    '2. When user types /skill-name args, how is the skill content + args sent to the agent?\n' +
    '3. How does the system prompt tell the agent about available skills?\n' +
    '4. How are MCP tools listed in the system prompt?\n\n' +
    'Output the EXACT code (with line numbers) for each of these. Do not summarize.',
    { label: 'study-hermes-skills-prompt' }
  ),
  () => agent(
    'Study hermes: approval callback and tab completion.\n\n' +
    'Read these files COMPLETELY:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/approval.py\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/completers.py\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/hermes_cli/repl.py (search for completer, approval, run_in_terminal)\n\n' +
    'I need to understand:\n' +
    '1. How does the approval callback work under patch_stdout? How does it show the prompt and read input?\n' +
    '2. How does the completer work? What class, how registered, how Tab triggers completion?\n' +
    '3. How does hermes handle terminal encoding for Chinese characters?\n\n' +
    'Output the EXACT code (with line numbers) for each. Do not summarize.',
    { label: 'study-hermes-approval-tab' }
  ),
  () => agent(
    'Study hermes: how MCP tools are exposed to the agent.\n\n' +
    'Read these files:\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/tools/mcp_tool.py (search for register, tool_registry, system_prompt)\n' +
    '- E:/opencode-desktop/hermes-agent-main/hermes-agent-main/agent/prompt_builder.py (search for mcp, tool)\n\n' +
    'I need to understand:\n' +
    '1. How are MCP tools registered so the agent can call them?\n' +
    '2. How does the system prompt tell the agent about available MCP tools?\n' +
    '3. When the agent calls an MCP tool, how is it executed?\n\n' +
    'Output the EXACT code (with line numbers). Do not summarize.',
    { label: 'study-hermes-mcp' }
  ),
])

// ========================================
// Phase 2: Diagnose — Read GrassFlow code
// ========================================
phase('Diagnose')

await parallel([
  () => agent(
    'Diagnose GrassFlow: compare skills system with hermes.\n\n' +
    'Read:\n' +
    '- E:/opencode-desktop/GrassFlow/tui/slash_commands.py (_cmd_skill_load, register_skill_commands)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/skills_system.py (SkillsManager)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (_get_system_prompt, _handle_slash_command)\n\n' +
    'Compare with hermes:\n' +
    '1. Does GrassFlow register skills as /name commands like hermes does?\n' +
    '2. Does the system prompt list available skills like hermes does?\n' +
    '3. When user types /skill-name args, is args preserved?\n\n' +
    'Output: what exists, what\'s missing, exact file:line.',
    { label: 'diag-skills' }
  ),
  () => agent(
    'Diagnose GrassFlow: compare MCP with hermes.\n\n' +
    'Read:\n' +
    '- E:/opencode-desktop/GrassFlow/tui/agent_integration.py (MCP initialization, tool registration)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/mcp_integration.py (MCPManager, start_servers, get_tools)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (_get_system_prompt)\n\n' +
    'Compare with hermes:\n' +
    '1. Are MCP tools registered in the tool registry?\n' +
    '2. Does the system prompt list MCP tools?\n' +
    '3. Can the agent call MCP tools as functions?\n\n' +
    'Output: what exists, what\'s missing, exact file:line.',
    { label: 'diag-mcp' }
  ),
  () => agent(
    'Diagnose GrassFlow: approval, tab, and encoding.\n\n' +
    'Read:\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (_setup_approval_callback, PromptSession creation)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/slash_commands.py (SlashCommandCompleter)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/layout.py (key bindings, BufferControl)\n\n' +
    'Check:\n' +
    '1. Approval: does _setup_approval_callback use sys.__stdout__ or input()? Does it work under patch_stdout?\n' +
    '2. Tab: is complete_while_typing=True on BufferControl? Does completer return results for "/h"?\n' +
    '3. Encoding: is stdout encoding set to utf-8? Any chcp 65001 calls?\n\n' +
    'Output: exact bugs found, file:line.',
    { label: 'diag-approval-tab-enc' }
  ),
])

// ========================================
// Phase 3: Fix — 6 parallel agents
// ========================================
phase('Fix')

await parallel([
  () => agent(
    'Fix skills system: register as /name commands + inject into system prompt.\n\n' +
    'Based on hermes pattern:\n' +
    '1. In tui/slash_commands.py register_skill_commands():\n' +
    '   - Register each skill as a /skill-name command\n' +
    '   - When called with args, preserve args as user prompt\n' +
    '   - Inject skill content as system message in _conversation_history\n' +
    '2. In tui/repl.py _get_system_prompt():\n' +
    '   - Add "## Available Skills" section listing all discovered skills\n' +
    '   - Format: "- /skill-name: description"\n' +
    '   - Tell agent: "User can type /skill-name to load a skill"\n\n' +
    'CRITICAL: Read the actual current code first. Fix what\'s broken.\n' +
    'After fix: git add -A && git commit -m "fix: skills as slash commands + system prompt injection"',
    { label: 'fix-skills', isolation: 'worktree' }
  ),
  () => agent(
    'Fix MCP: register tools + expose in system prompt.\n\n' +
    'Based on hermes pattern:\n' +
    '1. In tui/agent_integration.py init_agent_loop():\n' +
    '   - After MCP servers start, call register_tools_to_registry()\n' +
    '   - Ensure MCP tools appear in the tool list sent to LLM\n' +
    '2. In tui/repl.py _get_system_prompt():\n' +
    '   - Add "## Available MCP Tools" section\n' +
    '   - List each MCP tool with name and description\n' +
    '   - Tell agent: "You can call these tools directly"\n' +
    '3. In tui/mcp_integration.py:\n' +
    '   - Ensure MCPManager.start_servers() actually starts servers\n' +
    '   - Ensure tools are discovered after server starts\n\n' +
    'CRITICAL: Read the actual current code first.\n' +
    'After fix: git add -A && git commit -m "fix: MCP tools registered and exposed in system prompt"',
    { label: 'fix-mcp', isolation: 'worktree' }
  ),
  () => agent(
    'Fix approval callback to work under patch_stdout.\n\n' +
    'Based on hermes pattern:\n' +
    '1. Read tui/repl.py _setup_approval_callback\n' +
    '2. The problem: patch_stdout() replaces sys.stdout/sys.stdin\n' +
    '   - input() reads from patched stdin (a pipe) → gets EOF → auto-denies\n' +
    '3. Fix: use sys.__stdout__ and sys.__stdin__ (original file descriptors)\n' +
    '   - sys.__stdout__.write(prompt_text)\n' +
    '   - sys.__stdout__.flush()\n' +
    '   - response = sys.__stdin__.readline().strip()\n' +
    '4. Also ensure the prompt is visible:\n' +
    '   - Print to sys.__stdout__, not stdout\n' +
    '   - Format: "⚠️  tool_name: args\\n  [o]nce | [s]ession | [a]lways | [d]eny\\n  Choice: "\n\n' +
    'CRITICAL: Read the actual current code first.\n' +
    'After fix: git add -A && git commit -m "fix: approval callback uses sys.__stdout__ under patch_stdout"',
    { label: 'fix-approval', isolation: 'worktree' }
  ),
  () => agent(
    'Fix tab completion.\n\n' +
    'Based on hermes pattern:\n' +
    '1. Read tui/slash_commands.py SlashCommandCompleter.get_completions()\n' +
    '   - Does it yield Completion objects for partial input like "/h"?\n' +
    '2. Read tui/layout.py BufferControl creation\n' +
    '   - Is complete_while_typing=True?\n' +
    '3. Read tui/repl.py PromptSession\n' +
    '   - Is completer passed?\n' +
    '4. Fix whatever is broken\n\n' +
    'prompt_toolkit Tab completion needs:\n' +
    '- Buffer(completer=my_completer, complete_while_typing=True)\n' +
    '- BufferControl(buffer=buffer, complete_while_typing=True)\n' +
    '- Completer.get_completions() yields Completion objects\n\n' +
    'CRITICAL: Read the actual current code first.\n' +
    'After fix: git add -A && git commit -m "fix: tab completion for slash commands"',
    { label: 'fix-tab', isolation: 'worktree' }
  ),
  () => agent(
    'Fix terminal encoding for Chinese characters.\n\n' +
    'PROBLEM: Chinese characters are garbled in terminal output.\n\n' +
    'Fix:\n' +
    '1. In tui/cli.py, at the very beginning of main():\n' +
    '   - Set PYTHONIOENCODING=utf-8\n' +
    '   - On Windows: os.system("chcp 65001") or set console code page\n' +
    '   - Set sys.stdout.reconfigure(encoding="utf-8")\n' +
    '2. In tui/repl.py, when printing output:\n' +
    '   - Ensure all cprint/print calls use utf-8\n' +
    '3. In tui/layout.py, ensure prompt_toolkit output is utf-8\n\n' +
    'CRITICAL: Read the actual current code first.\n' +
    'After fix: git add -A && git commit -m "fix: terminal encoding utf-8 for Chinese characters"',
    { label: 'fix-encoding', isolation: 'worktree' }
  ),
  () => agent(
    'Fix system prompt to include all available capabilities.\n\n' +
    'The AI should know what it can do without scanning files.\n\n' +
    'In tui/repl.py _get_system_prompt(), add these sections:\n' +
    '1. "## Available Tools": list all registered tools (shell, read, write, glob, grep, webfetch)\n' +
    '2. "## Available Skills": list all discovered skills with descriptions\n' +
    '3. "## Available MCP Tools": list all connected MCP tools with descriptions\n' +
    '4. "## Available MCP Servers": list MCP servers with status (connected/failed)\n\n' +
    'This way the agent knows:\n' +
    '- "I have shell, read, write, glob, grep, webfetch tools"\n' +
    '- "I have hello-skill available, user can type /hello-skill"\n' +
    '- "I have tavily-search MCP tool, I can call it directly"\n\n' +
    'CRITICAL: Read the actual current code first.\n' +
    'After fix: git add -A && git commit -m "fix: system prompt includes all available capabilities"',
    { label: 'fix-sysprompt', isolation: 'worktree' }
  ),
])

// ========================================
// Phase 4: Merge
// ========================================
phase('Merge')

await agent(
  'Merge all worktree branches into master.\n\n' +
  'Steps:\n' +
  '1. List worktrees: ls .claude/worktrees/\n' +
  '2. For EACH worktree:\n' +
  '   a. Check for uncommitted changes: git -C <path> status --short\n' +
  '   b. If uncommitted, commit them: cd <path> && git add -A && git commit -m "fix: uncommitted"\n' +
  '   c. Check for unique commits: git -C <path> log --oneline master..HEAD\n' +
  '   d. If unique commits exist: git merge <branch> --no-edit\n' +
  '3. Resolve conflicts if any\n' +
  '4. Verify: python -c "from tui.repl import GrassFlowREPL; print(\'OK\')"',
  { label: 'merge-all' }
)
