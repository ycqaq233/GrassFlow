export const meta = {
  name: 'add-run-command',
  description: 'Add grassflow run temporary CLI session command (like opencode run)',
  phases: [
    { title: 'Research', detail: 'Study opencode run command implementation' },
    { title: 'Implement', detail: 'Parallel agents implement run command' },
    { title: 'Merge', detail: 'Merge worktree branches' },
    { title: 'Verify', detail: 'Test run command works end-to-end' },
  ],
}

// ========================================
// Phase 1: Research — Study opencode run command
// ========================================
phase('Research')

const research = await parallel([
  () => agent(
    'Study how opencode implements the `run` command (one-shot CLI session).\n\n' +
    'Read these files:\n' +
    '- E:/opencode-desktop/opencode-dev/opencode-dev/packages/opencode/src/cli/ (find the CLI entry point, look for "run" subcommand)\n' +
    '- E:/opencode-desktop/opencode-dev/opencode-dev/packages/opencode/src/session/ (session creation for run mode)\n' +
    '- E:/opencode-desktop/opencode-dev/opencode-dev/packages/opencode/src/agent/ (agent loop for run mode)\n\n' +
    'Find:\n' +
    '1. How is the "run" subcommand registered in the CLI?\n' +
    '2. How does it create a temporary session (vs persistent interactive session)?\n' +
    '3. How does it invoke the agent loop for a single prompt?\n' +
    '4. How does it handle output (streaming vs final)?\n' +
    '5. Does it support tool calls, MCP, and skills in run mode?\n\n' +
    'Output a detailed technical report with exact file paths, line numbers, and code snippets.',
    { label: 'research-opencode-run' }
  ),
  () => agent(
    'Study the current GrassFlow CLI and REPL architecture.\n\n' +
    'Read these files:\n' +
    '- E:/opencode-desktop/GrassFlow/tui/cli.py (CLI entry point and command registration)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/repl.py (REPL session creation and agent loop invocation)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/agent_integration.py (agent loop integration)\n' +
    '- E:/opencode-desktop/GrassFlow/tui/agent_loop.py (agent main loop)\n\n' +
    'Find:\n' +
    '1. How is the CLI structured? (argparse? click? custom?)\n' +
    '2. How does the REPL create a session and invoke the agent?\n' +
    '3. What is the minimal path to: create session → send one prompt → get response → exit?\n' +
    '4. How are tools, MCP, and skills initialized?\n\n' +
    'Output a detailed technical report with exact file paths and line numbers.',
    { label: 'research-grassflow-cli' }
  ),
])

// ========================================
// Phase 2: Implement — Parallel agents in worktrees
// ========================================
phase('Implement')

const implResults = await parallel([
  () => agent(
    'Implement the `grassflow run` CLI command.\n\n' +
    'Add a new subcommand to the GrassFlow CLI that creates a temporary session, runs a single prompt, and outputs the result.\n\n' +
    'Based on research:\n' +
    '- GrassFlow CLI uses argparse in tui/cli.py\n' +
    '- The REPL in tui/repl.py creates sessions and invokes the agent loop\n' +
    '- Agent integration is in tui/agent_integration.py\n\n' +
    'Implementation:\n' +
    '1. In tui/cli.py, add a new subcommand `run`:\n' +
    '   - Usage: `grassflow run "<prompt>" [--model MODEL] [--no-tools]`\n' +
    '   - Parse the prompt string as a positional argument\n' +
    '   - Optional: --model to override the model\n' +
    '   - Optional: --no-tools to disable tool calls\n' +
    '2. Create a new file tui/run_session.py that:\n' +
    '   - Creates a temporary session (no SQLite persistence)\n' +
    '   - Initializes tools, MCP, and skills (reuse agent_integration)\n' +
    '   - Sends the prompt to the agent loop\n' +
    '   - Streams the response to stdout (plain text, no Rich formatting)\n' +
    '   - Exits after the response completes\n' +
    '3. The run session should:\n' +
    '   - Support tool calls (the agent can use tools to answer)\n' +
    '   - Support MCP if configured\n' +
    '   - Support skills if available\n' +
    '   - Print tool calls and results in a compact format\n' +
    '   - Exit with code 0 on success, 1 on error\n\n' +
    'Reference opencode pattern:\n' +
    '- opencode creates a temporary session for `run` that reuses the full agent loop\n' +
    '- It streams output directly to stdout\n' +
    '- It supports all features (tools, MCP, skills) in run mode\n\n' +
    'Read the existing files first, then implement.',
    { label: 'impl-run-cmd', isolation: 'worktree' }
  ),
  () => agent(
    'Implement the run session one-shot executor.\n\n' +
    'Create tui/run_session.py - a one-shot session that runs a single prompt and exits.\n\n' +
    'This module should:\n' +
    '1. Define a `RunSession` class that:\n' +
    '   - Takes a prompt string, optional model override\n' +
    '   - Initializes the LLM client (reuse core/config.py ConfigManager)\n' +
    '   - Initializes the tool registry (reuse core/tool_registry.py)\n' +
    '   - Initializes MCP manager (reuse tui/mcp_integration.py)\n' +
    '   - Initializes skills manager (reuse tui/skills_system.py)\n' +
    '   - Creates a minimal agent loop (reuse tui/agent_loop.py)\n' +
    '2. The execution flow:\n' +
    '   - Build system prompt (reuse from repl.py _get_system_prompt or similar)\n' +
    '   - Send user prompt as first message\n' +
    '   - Stream response to stdout using print() (no Rich, no patch_stdout)\n' +
    '   - Handle tool calls: print "🔧 tool_name" compact, execute, continue\n' +
    '   - On final response, print it and exit\n' +
    '3. Error handling:\n' +
    '   - LLM errors: print to stderr, exit 1\n' +
    '   - Tool errors: print error, let agent retry or give up\n' +
    '   - Timeout: configurable, default 120s\n' +
    '4. Cleanup:\n' +
    '   - Shut down MCP connections on exit\n' +
    '   - No session persistence (temporary)\n\n' +
    'Read tui/agent_integration.py and tui/agent_loop.py to understand how to reuse them.\n' +
    'Read tui/repl.py to understand system prompt construction.',
    { label: 'impl-run-session', isolation: 'worktree' }
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
  '3. Verify: python -c "from tui.run_session import RunSession; print(\'OK\')"',
  { label: 'merge-run' }
)

// ========================================
// Phase 4: Verify — Test the run command
// ========================================
phase('Verify')

const verifyResult = await agent(
  'Test the `grassflow run` command end-to-end.\n\n' +
    'Run these tests:\n' +
    '1. Basic test: `python -m tui.cli run "hello"` — should get a response\n' +
    '2. Tool test: `python -m tui.cli run "read the file CLAUDE.md and summarize it"` — should use the read tool\n' +
    '3. Error test: `python -m tui.cli run "hello" --model nonexistent` — should error gracefully\n\n' +
    'If any test fails, fix the issue and re-test.\n' +
    'Report: what works, what doesn\'t, what was fixed.',
  { label: 'verify-run' }
)

// If verification found issues, do one more fix round
if (verifyResult && typeof verifyResult === 'string' && verifyResult.includes('FAIL')) {
  await agent(
    'Fix the remaining issues with the run command based on the verification report:\n\n' +
    verifyResult + '\n\n' +
    'Fix and re-verify.',
    { label: 'fix-run-remaining', isolation: 'worktree' }
  )

  await agent(
    'Merge the fix branch into master and verify once more.',
    { label: 'merge-run-fix' }
  )
}
