export const meta = {
  name: 'test-with-run-command',
  description: 'Test MCP, skills, and native tools via grassflow run command, fix issues found',
  phases: [
    { title: 'Test', detail: 'Run test commands to verify MCP/skills/tools' },
    { title: 'Analyze', detail: 'Analyze test results and identify failures' },
    { title: 'Fix', detail: 'Fix all identified issues in parallel' },
    { title: 'Merge', detail: 'Merge fixes and re-test' },
  ],
}

// ========================================
// Phase 1: Test — Run test commands
// ========================================
phase('Test')

const testResults = await parallel([
  () => agent(
    'Test native tool support via grassflow run.\n\n' +
    'Run these commands and report results:\n' +
    '1. `cd E:/opencode-desktop/GrassFlow && .venv/Scripts/python -m tui.cli run "读取文件 CLAUDE.md 的前10行内容"`\n' +
    '   Expected: Agent uses read tool to read CLAUDE.md and outputs the content\n' +
    '2. `cd E:/opencode-desktop/GrassFlow && .venv/Scripts/python -m tui.cli run "列出当前目录下所有 .py 文件"`\n' +
    '   Expected: Agent uses glob or shell tool to list files\n' +
    '3. `cd E:/opencode-desktop/GrassFlow && .venv/Scripts/python -m tui.cli run "执行命令 echo hello world"`\n' +
    '   Expected: Agent uses shell tool to run echo\n\n' +
    'For each test:\n' +
    '- Run the command with 60s timeout\n' +
    '- Capture stdout and stderr\n' +
    '- Report: PASS if agent responded and used tools, FAIL if error or no tool use\n' +
    '- If FAIL, include the full error output\n\n' +
    'Output format per test:\n' +
    'TEST: <description>\n' +
    'STATUS: PASS/FAIL\n' +
    'OUTPUT: <first 500 chars of output>\n' +
    'ERROR: <if any>',
    { label: 'test-native-tools' }
  ),
  () => agent(
    'Test MCP integration via grassflow run.\n\n' +
    'First, check if MCP is configured:\n' +
    '1. Read C:/Users/25318/.Grass/config.json and look for mcp_servers\n' +
    '2. If MCP servers are configured, run: `cd E:/opencode-desktop/GrassFlow && .venv/Scripts/python -m tui.cli run "使用MCP工具列出可用的工具"`\n' +
    '3. If no MCP servers configured, check if there are any MCP config files in the project\n\n' +
    'Also test MCP connection handling:\n' +
    '4. Try: `cd E:/opencode-desktop/GrassFlow && .venv/Scripts/python -m tui.cli run "hello" 2>&1 | head -20`\n' +
    '   Check if MCP initialization logs appear and if there are any MCP errors\n\n' +
    'Output format:\n' +
    'MCP_CONFIG: configured/not configured\n' +
    'MCP_STATUS: connected/error/not applicable\n' +
    'ERRORS: <any MCP-related errors>',
    { label: 'test-mcp' }
  ),
  () => agent(
    'Test skills system via grassflow run.\n\n' +
    'First, check if skills are configured:\n' +
    '1. Look for SKILL.md files: find E:/opencode-desktop/GrassFlow -name "SKILL.md" 2>/dev/null\n' +
    '2. Look for skills in ~/.Grass/skills/ or project .grass/skills/\n' +
    '3. Read tui/skills_system.py to understand how skills are discovered\n\n' +
    'Then test skills loading:\n' +
    '4. Run: `cd E:/opencode-desktop/GrassFlow && .venv/Scripts/python -c "from tui.skills_system import SkillsManager; sm = SkillsManager(); print(sm.get_skills_summary())"`\n' +
    '5. If skills exist, test: `cd E:/opencode-desktop/GrassFlow && .venv/Scripts/python -m tui.cli run "列出可用的skills"`\n\n' +
    'Output format:\n' +
    'SKILLS_CONFIG: found/not found\n' +
    'SKILLS_COUNT: <number>\n' +
    'SKILLS_LIST: <names>\n' +
    'LOAD_STATUS: OK/error',
    { label: 'test-skills' }
  ),
])

// ========================================
// Phase 2: Analyze — Identify failures
// ========================================
phase('Analyze')

const analysis = await agent(
  'Analyze all test results and create a fix plan.\n\n' +
    'Test results:\n\n' +
    '=== Native Tools ===\n' +
    (typeof testResults[0] === 'string' ? testResults[0] : 'No result') + '\n\n' +
    '=== MCP ===\n' +
    (typeof testResults[1] === 'string' ? testResults[1] : 'No result') + '\n\n' +
    '=== Skills ===\n' +
    (typeof testResults[2] === 'string' ? testResults[2] : 'No result') + '\n\n' +
    'For each failure:\n' +
    '1. Identify the root cause\n' +
    '2. Identify the file(s) that need to be fixed\n' +
    '3. Propose a specific fix\n\n' +
    'Output format:\n' +
    'ISSUE 1: <description>\n' +
    'ROOT CAUSE: <explanation>\n' +
    'FILES: <files to fix>\n' +
    'FIX: <specific fix description>\n\n' +
    'If everything passes, output: ALL_TESTS_PASSED',
  { label: 'analyze-results' }
)

// ========================================
// Phase 3: Fix — Fix all issues in parallel
// ========================================
phase('Fix')

if (typeof analysis === 'string' && !analysis.includes('ALL_TESTS_PASSED')) {
  // Parse issues and fix them
  await parallel([
    () => agent(
      'Fix the following issues found during testing:\n\n' +
        analysis + '\n\n' +
        'For each issue:\n' +
        '1. Read the relevant file(s)\n' +
        '2. Apply the fix\n' +
        '3. Verify the fix compiles\n' +
        '4. Commit the fix\n\n' +
        'Focus on: tool registration, tool execution, permission handling.',
      { label: 'fix-tools', isolation: 'worktree' }
    ),
    () => agent(
      'Fix the following MCP-related issues:\n\n' +
        analysis + '\n\n' +
        'For each issue:\n' +
        '1. Read the relevant file(s)\n' +
        '2. Apply the fix\n' +
        '3. Verify the fix compiles\n' +
        '4. Commit the fix\n\n' +
        'Focus on: MCP initialization, MCP tool discovery, MCP connection handling.',
      { label: 'fix-mcp', isolation: 'worktree' }
    ),
    () => agent(
      'Fix the following skills-related issues:\n\n' +
        analysis + '\n\n' +
        'For each issue:\n' +
        '1. Read the relevant file(s)\n' +
        '2. Apply the fix\n' +
        '3. Verify the fix compiles\n' +
        '4. Commit the fix\n\n' +
        'Focus on: skills discovery, skills loading, skills prompt injection.',
      { label: 'fix-skills', isolation: 'worktree' }
    ),
  ])
} else {
  log('All tests passed — no fixes needed.')
}

// ========================================
// Phase 4: Merge and re-test
// ========================================
phase('Merge')

if (typeof analysis === 'string' && !analysis.includes('ALL_TESTS_PASSED')) {
  await agent(
    'Merge all fix branches into master.\n' +
      'Steps:\n' +
      '1. git merge <branch> --no-edit for each branch\n' +
      '2. Resolve conflicts if any\n' +
      '3. Run full test suite: .venv/Scripts/python -m pytest tests/ -v --tb=short\n' +
      '4. Report results',
    { label: 'merge-fixes' }
  )

  // Re-run the key tests
  await agent(
    'Re-test after fixes. Run these commands:\n' +
      '1. `cd E:/opencode-desktop/GrassFlow && .venv/Scripts/python -m tui.cli run "读取文件 CLAUDE.md 的前10行内容"`\n' +
      '2. `cd E:/opencode-desktop/GrassFlow && .venv/Scripts/python -m tui.cli run "执行命令 echo hello world"`\n\n' +
      'Report: PASS or FAIL for each test with output.',
    { label: 'retest' }
  )
}
