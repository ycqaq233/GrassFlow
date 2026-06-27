export const meta = {
  name: 'system-integration',
  description: 'Wire 5 disconnected systems into REPL: tools, session, MCP, skills, thinking mode',
  phases: [
    { title: 'Study', detail: '5 agents read source files in parallel' },
    { title: 'Design', detail: 'Design integration plan for each system' },
    { title: 'Implement', detail: '6 agents write integration code in parallel' },
    { title: 'Verify', detail: 'Run tests and verify compilation' },
  ],
}

// Phase 1: Study
phase('Study')

const [toolsReport, sessionReport, mcpSkillsReport, thinkingReport, hermesReport] = await parallel([
  () => agent(
    'Read these files and report: 1) tools/tool.py (Tool base class, execute signature, ToolResult), 2) tools/__init__.py (how tools register), 3) core/tool_registry.py (BaseTool, run signature), 4) tui/agent_loop.py lines 895-920 (_gather_tool_definitions), 5) tui/agent_integration.py lines 75-110 (init_agent_loop). Report: differences between Tool and BaseTool, what _gather_tool_definitions returns, what init_agent_loop does, what needs changing.',
    { label: 'study:tools', phase: 'Study' }
  ),
  () => agent(
    'Read these files and report: 1) tui/session.py (Session class: add_user_message, add_assistant_message, get_messages signatures), 2) tui/repl.py lines 280-345 (_handle_agent_message and _run_agent_loop_async), 3) tui/repl.py lines 100-130 (__init__ where session created). Report: where user messages sent, where assistant responses received, where to insert persistence calls, any existing session usage.',
    { label: 'study:session', phase: 'Study' }
  ),
  () => agent(
    'Read these files and report: 1) tui/mcp_integration.py (MCPManager: constructor, start_all, get_tools, shutdown_all), 2) tui/skills_system.py (SkillsManager: constructor, get_skills_summary, build_skills_prompt), 3) tui/slash_commands.py lines 465-485 (_cmd_skills and _cmd_mcp), 4) tui/repl.py lines 405-430 (_get_system_prompt), 5) tui/agent_integration.py full file. Report: MCPManager API, SkillsManager API, is _cmd_skills a stub, where skills prompt should go in system prompt.',
    { label: 'study:mcp-skills', phase: 'Study' }
  ),
  () => agent(
    'Read these files and diagnose thinking mode: 1) tui/slash_commands.py -- find /think command handler, 2) tui/repl.py -- find where thinking_mode is used, 3) tui/stream_handler.py -- find ThinkingParser and how thinking events handled, 4) core/llm.py -- find where thinking/reasoning_effort passed to API, 5) core/llm_protocol.py -- find if thinking tokens supported. Report: full chain from /think command to LLM API call, where it breaks.',
    { label: 'study:thinking', phase: 'Study' }
  ),
  () => agent(
    'Read these hermes reference files for integration patterns: 1) Find in E:\\opencode-desktop\\hermes-agent-main how hermes registers builtin tools (search for register_builtin or tool registration), 2) Find how hermes starts MCP servers (search for mcp start or MCPManager), 3) Find how hermes injects skills into system prompt (search for build_skills_prompt or skills_prompt). Report the exact patterns used.',
    { label: 'study:hermes', phase: 'Study' }
  ),
])

log('Study phase complete')

// Phase 2: Design
phase('Design')

const designReport = await agent(
  `Based on these study reports, design the integration plan for all 5 systems.

TOOLS REPORT:
${toolsReport}

SESSION REPORT:
${sessionReport}

MCP+SKILLS REPORT:
${mcpSkillsReport}

THINKING REPORT:
${thinkingReport}

HERMES PATTERNS:
${hermesReport}

Design a concrete plan with:
1. Tool bridge: how to convert tools.tool.Tool to core.tool_registry.BaseTool (or vice versa), exact code changes needed
2. Session persistence: exact line numbers in repl.py where to add add_user_message/add_assistant_message calls
3. MCP integration: how to instantiate MCPManager in init_agent_loop, where to call start_all
4. Skills integration: where to call build_skills_prompt in _get_system_prompt, how to wire /skills command
5. Thinking mode: what is broken and how to fix it

For each change specify: file path, function name, what to add/modify. Be very specific about function signatures and import paths.`,
  { label: 'design:integration', phase: 'Design' }
)

log('Design phase complete')

// Phase 3: Implement
phase('Implement')

const implResults = await parallel([
  () => agent(
    `Create a bridge adapter between tools/ and core/tool_registry.py.

DESIGN:
${designReport}

Task: Create file tools/registry_bridge.py that:
1. Imports Tool from tools.tool and BaseTool, ToolResult from core.tool_registry
2. Creates ToolAdapter(BaseTool) that wraps a tools.tool.Tool instance
3. Maps Tool.execute(params, ctx) to BaseTool.run(args, ctx) and vice versa for ToolResult
4. Provides register_all_builtin_tools(registry) that registers shell, read, write, glob, grep into a BaseTool registry
5. Also update tools/__init__.py to export the new bridge

Read all files in tools/ and core/tool_registry.py first.`,
    { label: 'impl:tool-bridge', phase: 'Implement', isolation: 'worktree' }
  ),

  () => agent(
    `Modify tui/agent_integration.py to register tools and wire everything into init_agent_loop().

DESIGN:
${designReport}

Task:
1. Read tui/agent_integration.py fully
2. Read tui/agent_loop.py to understand how tools are stored (look for tool_registry, tools dict, _gather_tool_definitions)
3. In init_agent_loop(), after creating AgentLoop:
   - Import register_all_builtin_tools and call it to populate the agent loop tool registry
   - Also wire MCP: create MCPManager, call start_all, register MCP tools
   - Also wire Skills: create SkillsManager, store reference
4. Fix _gather_tool_definitions() in agent_loop.py if it returns empty list -- make it return registered tools
5. Store mcp_manager and skills_manager references so slash commands can access them

Read all relevant files first before making changes.`,
    { label: 'impl:integration', phase: 'Implement', isolation: 'worktree' }
  ),

  () => agent(
    `Add session message persistence to tui/repl.py.

DESIGN:
${designReport}

Task:
1. Read tui/repl.py fully
2. Read tui/session.py to confirm add_user_message and add_assistant_message signatures
3. Find where user input is sent to agent (likely in _handle_agent_message or similar)
4. Add self.session.add_user_message(content) call
5. Find where assistant response is collected (likely in _run_agent_loop_async)
6. Add self.session.add_assistant_message(content) call after response
7. Handle edge cases: empty messages, tool-only responses, errors
8. Also fix _get_system_prompt() to include skills prompt -- read tui/skills_system.py for build_skills_prompt()`,
    { label: 'impl:session-skills', phase: 'Implement', isolation: 'worktree' }
  ),

  () => agent(
    `Fix /skills and /mcp slash commands in tui/slash_commands.py.

DESIGN:
${designReport}

Task:
1. Read tui/slash_commands.py fully
2. Find _cmd_skills() -- if it is a stub, implement it to call SkillsManager.get_skills_summary()
3. Find _cmd_mcp() -- implement it to show MCP server status
4. The MCPManager and SkillsManager instances should be accessible -- check if they are stored on a global, on self, or need to be imported from agent_integration
5. If they are not yet stored anywhere, add a module-level reference in agent_integration.py that slash_commands.py can import

Read the actual file first, do not assume.`,
    { label: 'impl:slash-commands', phase: 'Implement', isolation: 'worktree' }
  ),

  () => agent(
    `Diagnose and fix the /think command so thinking mode works end-to-end.

DESIGN:
${designReport}

Task:
1. Read tui/slash_commands.py -- find /think handler, see what variable it sets
2. Read tui/repl.py -- find where that variable is read and passed to agent
3. Read tui/agent_loop.py -- find where thinking/reasoning_effort is passed to LLM calls
4. Read core/llm.py -- find the actual API call, check if reasoning_effort param is sent
5. Read core/llm_protocol.py -- check if thinking is in the protocol
6. Trace FULL chain: /think sets X -> repl reads X -> passes to agent_loop Y -> passes to llm Z -> API param W
7. Fix every break in the chain
8. Common issues: variable not passed through, provider-specific param name (openai uses different param than anthropic), stream_handler not rendering thinking blocks`,
    { label: 'impl:thinking', phase: 'Implement', isolation: 'worktree' }
  ),
])

log('Implementation phase complete, starting verification')

// Phase 4: Verify
phase('Verify')

const verifyReport = await agent(
  `Verify all integration changes. Read every modified file and check correctness.

Modified files to check:
- tools/registry_bridge.py (new)
- tools/__init__.py
- tui/agent_integration.py
- tui/agent_loop.py
- tui/repl.py
- tui/slash_commands.py

For each file check:
1. Imports -- no circular imports, no missing modules
2. Function signatures match between callers and callees
3. Error handling -- what if MCP fails, skills dir missing, tool registration fails
4. No syntax errors

Then run: cd E:\\opencode-desktop\\GrassFlow && .venv\\Scripts\\python -c "import tui.cli" to verify imports work.
Then run: cd E:\\opencode-desktop\\GrassFlow && .venv\\Scripts\\python -m pytest tests/ -q --tb=short

Report ALL issues found with file:line references.`,
  { label: 'verify:all', phase: 'Verify' }
)

return { designReport, implResults, verifyReport }
