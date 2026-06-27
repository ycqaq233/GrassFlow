export const meta = {
  name: 'fix-thinking',
  description: 'Fix thinking mode: default medium, collapsible UI, fix newline-per-word rendering',
  phases: [
    { title: 'Study', detail: '3 agents study hermes/opencode thinking rendering + GrassFlow current state' },
    { title: 'Implement', detail: '4 agents fix default, UI rendering, collapsible blocks, integration' },
    { title: 'Verify', detail: 'Verify rendering and tests pass' },
  ],
}

// Phase 1: Study
phase('Study')

const [hermesReport, opencodeReport, currentReport] = await parallel([
  () => agent(
    'Study how hermes renders thinking blocks. Search in E:\\opencode-desktop\\hermes-agent-main for: 1) ThinkingParser or think_scrubber or StreamingThinkScrubber — how thinking text is accumulated and rendered, 2) How thinking blocks are displayed in the TUI (collapsed? expanded? spinner?), 3) How thinking delta events are handled in stream_handler or display. Report the exact rendering approach: does it show word-by-word? Does it collapse? What Rich/prompt_toolkit components are used?',
    { label: 'study:hermes-thinking', phase: 'Study' }
  ),
  () => agent(
    'Study how opencode renders thinking blocks. Search in E:\\opencode-desktop\\opencode-dev for: 1) thinking or reasoning rendering in TUI components, 2) How thinking text is displayed (collapsed? expanded? markdown rendered?), 3) What UI framework is used for thinking display. Report the exact approach.',
    { label: 'study:opencode-thinking', phase: 'Study' }
  ),
  () => agent(
    'Read these GrassFlow files and report the current thinking implementation: 1) tui/stream_handler.py — find ThinkingParser class, how thinking_delta events are handled, how text is accumulated, 2) tui/repl.py — find _apply_event_type and how thinking_delta is rendered (look for cprint calls), 3) tui/slash_commands.py — find /think handler and default value, 4) tui/repl.py — find session metadata initialization where thinking default is set. Report: current rendering approach, where the newline-per-word bug is, what the default thinking setting is.',
    { label: 'study:current-thinking', phase: 'Study' }
  ),
])

log('Study phase complete')

// Phase 2: Design
phase('Design')

const designReport = await agent(
  `Based on these study reports, design the fix for thinking mode.

HERMES APPROACH:
${hermesReport}

OPENCODE APPROACH:
${opencodeReport}

CURRENT GRASSFLOW:
${currentReport}

Design fixes for:
1. Default thinking: where to set default to "medium" when session starts (in repl.py __init__ or session creation)
2. Newline-per-word bug: find the exact cause in stream_handler.py or repl.py where thinking_delta tokens get printed with newlines
3. Collapsible thinking UI: design a collapsible thinking block using prompt_toolkit or Rich. Options:
   - Use a collapsing region in prompt_toolkit (if possible)
   - Show a summary line "Thinking... (N tokens)" that expands on click/key
   - Use ANSI escape codes to create a foldable section
   - Use Rich Console with collapse groups

For each fix specify: exact file, function, line numbers, what to change. Be very specific about the rendering approach — include the actual code structure.`,
  { label: 'design:thinking', phase: 'Design' }
)

log('Design phase complete')

// Phase 3: Implement
phase('Implement')

const implResults = await parallel([
  // Agent 1: Fix default thinking + /think handler
  () => agent(
    `Fix thinking mode default to "medium" in GrassFlow.

DESIGN:
${designReport}

Task:
1. Read tui/repl.py — find where session is created or metadata initialized
2. Set default thinking to {"enabled": true, "effort": "medium"} in session metadata
3. Read tui/slash_commands.py — find /think handler
4. Make /think with no args show current status and toggle
5. Make /think off disable thinking, /think on enable with medium, /think high set high effort
6. The default should be: thinking ENABLED with medium effort

Do not break existing functionality. Read files first.`,
    { label: 'fix:default', phase: 'Implement', isolation: 'worktree' }
  ),

  // Agent 2: Fix newline-per-word bug in thinking rendering
  () => agent(
    `Fix the thinking mode newline-per-word rendering bug.

DESIGN:
${designReport}

Task:
1. Read tui/stream_handler.py fully — find ThinkingParser class
2. Read tui/repl.py — find where thinking_delta events are rendered (search for thinking_delta in _apply_event_type)
3. The bug: each thinking token/word appears on a new line. Find WHY:
   - Is cprint() adding a newline after each token?
   - Is the thinking text being split by newlines and each line printed separately?
   - Is there a missing end="" parameter?
4. Fix: thinking tokens should accumulate and display inline (like text_delta), not one-per-line
5. The thinking output should be styled differently (dim/italic) to distinguish from regular output

Read all relevant files before making changes.`,
    { label: 'fix:newline', phase: 'Implement', isolation: 'worktree' }
  ),

  // Agent 3: Add collapsible thinking blocks
  () => agent(
    `Implement collapsible thinking blocks in the TUI.

DESIGN:
${designReport}

Task:
1. Read tui/repl.py — understand the hermes-mode output approach (cprint to terminal scrollback)
2. Read tui/stream_handler.py — understand how thinking text is accumulated
3. Since GrassFlow uses hermes mode (cprint to terminal scrollback, not prompt_toolkit Window), the collapsible approach should be:
   - When thinking starts: print a dim header like "  💭 Thinking..."
   - While thinking: accumulate text, print it in dim/italic (not word-by-word newlines)
   - When thinking ends: print a dim footer like "  💭 Done thinking (N tokens)"
   - Optionally: support a /compact-think command that collapses previous thinking blocks
4. The key insight: in terminal scrollback mode, we cannot truly "collapse" text. Instead:
   - Use ANSI dim/italic for thinking text to make it visually distinct
   - Print thinking in a condensed way (paragraphs, not line-per-word)
   - Show a summary count at the end

Focus on making thinking readable and visually distinct, not on true collapse (which is impossible in scrollback).`,
    { label: 'fix:collapsible', phase: 'Implement', isolation: 'worktree' }
  ),

  // Agent 4: Wire thinking into agent_integration properly
  () => agent(
    `Ensure thinking mode is properly wired through the entire chain.

Task:
1. Read tui/agent_integration.py — check if reasoning_effort is passed in ALL code paths (process_streaming, process_in_background, _background_agent_loop, process_streaming_sync)
2. Read tui/agent_loop.py — check if reasoning_effort is passed to stream_chat
3. Read core/llm_protocol.py — check if reasoning_effort is in GenerationOptions and encoded in request body
4. Read tui/repl.py — check if reasoning_effort is extracted from session metadata in ALL message paths
5. Fix any broken links in the chain
6. Also check: does the LLM response include thinking events? If so, verify stream_handler processes them correctly.

Be thorough — trace every path from user input to API call.`,
    { label: 'fix:wire', phase: 'Implement', isolation: 'worktree' }
  ),
])

log('Implementation phase complete')

// Phase 4: Verify
phase('Verify')

const verifyReport = await agent(
  `Verify all thinking mode changes.

Changes made:
${implResults.map((r, i) => `--- Agent ${i+1} ---\n${r}`).join('\n\n')}

Task:
1. Read all modified files: tui/repl.py, tui/slash_commands.py, tui/stream_handler.py, tui/agent_integration.py, tui/agent_loop.py, core/llm_protocol.py
2. Verify: default thinking is "medium" when session starts
3. Verify: thinking_delta rendering does NOT add newlines per word
4. Verify: reasoning_effort is passed through ALL code paths
5. Run: cd E:\\opencode-desktop\\GrassFlow && .venv\\Scripts\\python -m pytest tests/test_repl.py tests/test_stream_handler.py tests/test_llm_protocol.py -q --tb=short
6. Report any issues with file:line references.`,
  { label: 'verify:all', phase: 'Verify' }
)

return { hermesReport, opencodeReport, currentReport, designReport, implResults, verifyReport }
