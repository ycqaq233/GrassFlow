export const meta = {
  name: 'tui-rewrite',
  description: 'Study hermes TUI and rewrite GrassFlow CLI to match exactly',
  phases: [
    { title: 'Study', detail: 'Parallel agents study hermes TUI implementation' },
    { title: 'Design', detail: 'Synthesize findings into a rewrite plan' },
    { title: 'Rewrite', detail: 'Parallel agents rewrite each GrassFlow TUI file' },
    { title: 'Verify', detail: 'Verify mouse scroll and overall consistency' },
  ],
}

// ============ Phase 1: Study hermes TUI ============
phase('Study')

const HERMES = 'E:\\opencode-desktop\\hermes-agent-main\\hermes-agent-main'

const studyResults = await parallel([
  () => agent(
    'Read the hermes REPL/TUI main file. Search for it: look for repl.py, tui.py, main.py, cli.py in the hermes project. Read the ENTIRE file. Focus on: 1) How is the UI structured (output area, input area, status bar)? 2) What library is used (prompt_toolkit, Rich, curses)? 3) How is Application created? 4) What is the full_screen setting? 5) How is mouse_support configured? Return the complete code structure and all relevant excerpts.',
    { label: 'study-repl', phase: 'Study', schema: { type: 'object', properties: { library: { type: 'string' }, full_screen: { type: 'boolean' }, mouse_support: { type: 'string' }, layout_structure: { type: 'string' }, key_code_excerpts: { type: 'string' } }, required: ['library', 'layout_structure', 'key_code_excerpts'] } }
  ),
  () => agent(
    'Search hermes project for ALL mouse and scroll handling code. Search for: mouse, scroll, ScrollablePane, vertical_scroll, scroll_offset, wheel, PageUp, PageDown across ALL files. Read every matching file completely. Return: 1) How mouse scroll events are captured 2) How the output area scrolls 3) Whether it uses prompt_toolkit Window.vertical_scroll or something else 4) The exact key bindings for scroll. Include full code excerpts.',
    { label: 'study-scroll', phase: 'Study', schema: { type: 'object', properties: { scroll_mechanism: { type: 'string' }, mouse_bindings: { type: 'string' }, scroll_code: { type: 'string' }, output_window_config: { type: 'string' } }, required: ['scroll_mechanism', 'mouse_bindings', 'scroll_code'] } }
  ),
  () => agent(
    'Search hermes project for how streaming output is rendered. Look for: FormattedTextControl, BufferControl, print_tokens, add_output, write, stream, token, render. Read the relevant files. Focus on: 1) How text is added to the output area 2) How the output scrolls to bottom on new content 3) How the UI refreshes during streaming. Return complete code excerpts.',
    { label: 'study-render', phase: 'Study', schema: { type: 'object', properties: { output_mechanism: { type: 'string' }, auto_scroll: { type: 'string' }, refresh_mechanism: { type: 'string' }, render_code: { type: 'string' } }, required: ['output_mechanism', 'auto_scroll', 'render_code'] } }
  ),
  () => agent(
    'Search hermes project for layout creation code. Look for: build_layout, create_layout, HSplit, VSplit, Window, FloatContainer, Layout. Read all layout-related code. Focus on: 1) How the output window is created 2) What wrap/scrollable settings are used 3) How the input area is positioned 4) How the status bar is positioned 5) Whether ScrollablePane or ScrollbarMargin is used. Return complete code excerpts.',
    { label: 'study-layout', phase: 'Study', schema: { type: 'object', properties: { layout_code: { type: 'string' }, output_window_settings: { type: 'string' }, input_area_settings: { type: 'string' }, status_bar_settings: { type: 'string' } }, required: ['layout_code', 'output_window_settings'] } }
  ),
])

log('Study complete. Found: ' + studyResults.map(r => r ? 'OK' : 'FAIL').join(', '))

// ============ Phase 2: Design ============
phase('Design')

const designResult = await agent(
  'Based on the hermes TUI study results below, design the exact rewrite plan for GrassFlow TUI.\n\n' +
  'Study results:\n' + JSON.stringify(studyResults, null, 2) + '\n\n' +
  'GrassFlow current files to rewrite:\n' +
  '- tui/layout.py (layout, keybindings, styles)\n' +
  '- tui/repl.py (main REPL loop, output management, mouse handling)\n\n' +
  'Requirements:\n' +
  '1. Mouse scroll MUST work - this is the #1 priority\n' +
  '2. Layout must match hermes exactly\n' +
  '3. Output area must be scrollable with mouse wheel\n' +
  '4. Auto-scroll to bottom on new output (unless user scrolled up)\n' +
  '5. Keep all existing functionality (undo/redo, themes, slash commands, etc.)\n\n' +
  'Return a detailed rewrite plan with exact code structure for each file.',
  { label: 'design-plan', phase: 'Design', schema: { type: 'object', properties: { layout_py_plan: { type: 'string' }, repl_py_plan: { type: 'string' }, key_changes: { type: 'array', items: { type: 'string' } } }, required: ['layout_py_plan', 'repl_py_plan', 'key_changes'] } }
)

log('Design complete. Key changes: ' + (designResult?.key_changes?.length || 0))

// ============ Phase 3: Rewrite ============
phase('Rewrite')

const rewriteResults = await parallel([
  () => agent(
    'Rewrite tui/layout.py completely based on hermes TUI pattern.\n\n' +
    'Design plan:\n' + JSON.stringify(designResult, null, 2) + '\n\n' +
    'Study results:\n' + JSON.stringify(studyResults, null, 2) + '\n\n' +
    'CRITICAL REQUIREMENTS:\n' +
    '1. Mouse scroll MUST work - use the exact same approach as hermes\n' +
    '2. Read the current tui/layout.py FIRST to understand all existing functionality\n' +
    '3. Keep ALL existing features: themes, styles, header, status bar, keybindings\n' +
    '4. The output window MUST be scrollable with mouse wheel\n' +
    '5. Write the complete new file using the Write tool\n' +
    '6. After writing, verify syntax with: python -c "import tui.layout; print(\\"OK\\")"',
    { label: 'rewrite-layout', phase: 'Rewrite' }
  ),
  () => agent(
    'Rewrite tui/repl.py to match hermes TUI output/scroll pattern.\n\n' +
    'Design plan:\n' + JSON.stringify(designResult, null, 2) + '\n\n' +
    'Study results:\n' + JSON.stringify(studyResults, null, 2) + '\n\n' +
    'CRITICAL REQUIREMENTS:\n' +
    '1. Mouse scroll MUST work - coordinate with layout.py changes\n' +
    '2. Read the current tui/repl.py FIRST to understand all existing functionality\n' +
    '3. Keep ALL existing features: agent integration, undo/redo, shell commands, etc.\n' +
    '4. Output rendering must use the same approach as hermes\n' +
    '5. Write the complete new file using the Write tool\n' +
    '6. After writing, verify syntax with: python -c "import tui.repl; print(\\"OK\\")"',
    { label: 'rewrite-repl', phase: 'Rewrite' }
  ),
])

log('Rewrite complete: ' + rewriteResults.map(r => r ? 'OK' : 'FAIL').join(', '))

// ============ Phase 4: Verify ============
phase('Verify')

const verifyResult = await agent(
  'Verify the TUI rewrite is complete and correct.\n\n' +
  'Check these files:\n' +
  '- tui/layout.py\n' +
  '- tui/repl.py\n\n' +
  'Verification steps:\n' +
  '1. Read both files completely\n' +
  '2. Check syntax: python -c "import tui.layout; import tui.repl; print(\\"OK\\")" \n' +
  '3. Verify mouse scroll bindings exist and are correct\n' +
  '4. Verify output_window is created with correct scroll settings\n' +
  '5. Verify add_output scrolls to bottom correctly\n' +
  '6. Verify all imports are correct\n' +
  '7. Verify all existing features are preserved\n' +
  '8. Check for any missing callbacks or broken references\n\n' +
  'Return a pass/fail verdict with any remaining issues.',
  { label: 'verify-all', phase: 'Verify', schema: { type: 'object', properties: { status: { type: 'string' }, issues: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, description: { type: 'string' } }, required: ['file', 'description'] } } }, required: ['status'] } }
)

if (verifyResult?.status === 'fail') {
  log('VERIFICATION FAILED: ' + verifyResult.issues.length + ' issues')
  for (const issue of verifyResult.issues) {
    log('  - ' + issue.file + ': ' + issue.description)
  }
} else {
  log('VERIFICATION PASSED')
}

return {
  studyComplete: studyResults.filter(Boolean).length + '/4',
  designChanges: designResult?.key_changes?.length || 0,
  rewriteStatus: rewriteResults.map(r => r ? 'OK' : 'FAIL'),
  verifyStatus: verifyResult?.status || 'unknown',
}
