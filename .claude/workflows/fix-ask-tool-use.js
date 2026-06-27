export const meta = {
  name: 'fix-ask-tool-use',
  description: 'Fix grassflow ask command not using tools - agent hallucinates instead of calling read/glob/shell',
  phases: [
    { title: 'Diagnose', detail: 'Find why ask mode agent does not use tools' },
    { title: 'Fix', detail: 'Fix tool registration and agent loop for ask mode' },
    { title: 'Verify', detail: 'Test ask command with tool-dependent prompts' },
  ],
}

// ========================================
// Phase 1: Diagnose
// ========================================
phase('Diagnose')

const diagnosis = await agent(
  'Diagnose why the `grassflow ask` command agent does not use tools.\n\n' +
    'The ask command was implemented in tui/run_session.py. When tested with "读取文件 CLAUDE.md 的前10行内容",\n' +
    'the agent hallucinated content instead of using the read tool.\n\n' +
    'Read these files to find the root cause:\n' +
    '1. tui/run_session.py - How does it initialize tools? How does it build the system prompt?\n' +
    '2. tui/agent_integration.py - How does init_agent_loop register tools?\n' +
    '3. tui/agent_loop.py - How does process_streaming handle tool calls?\n' +
    '4. core/tool_registry.py - How are tools registered and discovered?\n' +
    '5. tools/bridge.py - How does LegacyToolAdapter bridge old tools to new registry?\n\n' +
    'Possible causes:\n' +
    '- Tools not registered in the agent loop for ask mode\n' +
    '- System prompt does not mention available tools\n' +
    '- Tool registry not passed to the LLM client\n' +
    '- Agent loop does not enter tool-call mode\n' +
    '- LLM not receiving tool definitions in the API call\n\n' +
    'Output:\n' +
    'ROOT CAUSE: <exact explanation>\n' +
    'FILE: <file path>\n' +
    'LINE: <line number>\n' +
    'FIX: <specific fix>',
  { label: 'diagnose-ask-tools' }
)

// ========================================
// Phase 2: Fix
// ========================================
phase('Fix')

await agent(
  'Fix the grassflow ask command so the agent uses tools.\n\n' +
    'Diagnosis:\n' +
    (typeof diagnosis === 'string' ? diagnosis : 'See diagnosis above') + '\n\n' +
    'The fix should ensure:\n' +
    '1. Tools are registered in the agent loop for ask mode (same as REPL mode)\n' +
    '2. System prompt mentions available tools and when to use them\n' +
    '3. Tool definitions are sent to the LLM in the API call\n' +
    '4. Agent loop processes tool_call events and executes tools\n' +
    '5. Tool results are fed back to the LLM for the next iteration\n\n' +
    'Read the relevant files first, then apply the minimal fix.\n' +
    'Verify: from tui.run_session import run_single_prompt should still work.',
  { label: 'fix-ask-tools', isolation: 'worktree' }
)

// ========================================
// Phase 3: Verify
// ========================================
phase('Verify')

await agent(
  'Merge the fix and test the ask command.\n\n' +
    'Steps:\n' +
    '1. git merge worktree-branch --no-edit\n' +
    '2. Run: cd E:/opencode-desktop/GrassFlow && .venv/Scripts/python -m tui.cli ask "读取文件 CLAUDE.md 的前10行内容"\n' +
    '   Expected: Agent uses read tool, outputs actual file content (not hallucinated)\n' +
    '3. Run: cd E:/opencode-desktop/GrassFlow && .venv/Scripts/python -m tui.cli ask "执行命令 echo hello world"\n' +
    '   Expected: Agent uses shell tool, outputs "hello world"\n\n' +
    'If tests fail, diagnose and fix again.\n' +
    'Report: PASS/FAIL for each test with actual output.',
  { label: 'verify-ask-tools' }
)
