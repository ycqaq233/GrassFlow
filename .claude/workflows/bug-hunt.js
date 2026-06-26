export const meta = {
  name: 'bug-hunt',
  description: 'Multi-agent bug hunt: scan, compare with hermes, fix all bugs',
  phases: [
    { title: 'Scan', detail: 'Parallel agents scan all TUI files for bugs' },
    { title: 'Compare', detail: 'Each bug compared with hermes implementation' },
    { title: 'Fix', detail: 'Each agent applies precise fixes based on analysis' },
    { title: 'Verify', detail: 'Verify all fixes are consistent and correct' },
  ],
}

// ============ Phase 1: Parallel Scan ============
phase('Scan')

const SCAN_TARGETS = [
  { label: 'scroll-mouse', files: 'tui/layout.py tui/repl.py', prompt: 'Focus on mouse scroll and wheel handling. Check: 1) Are <scroll-up>/<scroll-down> bindings correct? 2) Does mouse_support=True work with full_screen=False? 3) Does vertical_scroll assignment actually work or is the output_window read-only? 4) Is SCROLL_TO_BOTTOM=10**6 correct or should it use content_height? 5) Does _user_scrolled flag reset correctly? 6) Does add_output() auto-scroll work? Read both files completely, check every line related to scroll/mouse/wheel/vertical_scroll.' },
  { label: 'stream-handler', files: 'tui/stream_handler.py', prompt: 'Read the entire file. Check: 1) Does ThinkingParser handle all edge cases? 2) Does ToolCallParser handle partial JSON correctly? 3) Does MarkdownSegmenter handle unclosed code blocks? 4) Is flush() implemented and called correctly? 5) Does _handle_tool_call support both object and dict formats? 6) Any race conditions in streaming?' },
  { label: 'agent-loop', files: 'tui/agent_loop.py', prompt: 'Read the entire file. Check: 1) Is tool_call.id used correctly (not tool_call.name)? 2) Does non-streaming path populate tool_calls? 3) Is message flattening correct (preserving tool_call_id, name)? 4) Is TOOL_CALL_END yielded at the right time? 5) Does retry logic work? 6) Any issues with the thinking effort parameter?' },
  { label: 'repl-core', files: 'tui/repl.py', prompt: 'Read the entire file. Check: 1) Does _process_user_input handle all command types? 2) Is _retry_last flag working? 3) Does _execute_shell run in background thread? 4) Is _api_start_time tracked correctly? 5) Does tool_result check is_error? 6) Does clear_output clear undo/redo stacks? 7) Any issues with _should_exit and app.exit() timing?' },
  { label: 'slash-cmds', files: 'tui/slash_commands.py', prompt: 'Read the entire file. Check: 1) Does undo skip system messages correctly? 2) Does redo not pollute with feedback? 3) Are all 33 commands registered? 4) Does /think parse effort correctly? 5) Does SlashCommandCompleter handle all commands? 6) Any missing parameter completions?' },
  { label: 'mcp-integration', files: 'tui/mcp_integration.py', prompt: 'Read the entire file. Check: 1) Does JSON-RPC framing use Content-Length correctly? 2) Does stdio transport handle process lifecycle? 3) Does _read_line handle partial reads and timeouts? 4) Does auto-reconnect with exponential backoff work? 5) Does tool discovery parse response correctly? 6) Any resource leaks (processes not killed)?' },
  { label: 'skills-system', files: 'tui/skills_system.py', prompt: 'Read the entire file. Check: 1) Does YAML frontmatter parser handle all types (strings, lists, ints, booleans)? 2) Does platform filtering work on Windows? 3) Does find_skill_files search correctly? 4) Does build_skills_prompt format correctly? 5) Any issues with negative integer parsing?' },
  { label: 'agents-md', files: 'tui/agents_md_loader.py', prompt: 'Read the entire file. Check: 1) Does find_context_file search up to git root? 2) Does head/tail truncation work correctly? 3) Does get_git_root handle both .git dir walk and git rev-parse? 4) Is caching correct (no double calls)? 5) Does platform mapping work?' },
  { label: 'config-core', files: 'core/config.py', prompt: 'Read the entire file. Check: 1) Does deep_merge handle nested dicts correctly? 2) Does list_configs handle None from load_project_config? 3) Does env var override work? 4) Is mcp_servers field included? 5) Any issues with config path resolution?' },
  { label: 'display-error', files: 'tui/display.py tui/error_handler.py', prompt: 'Read both files. Check: 1) Does Rich display handle all output types? 2) Does error handler catch and format errors correctly? 3) Any unhandled exception paths? 4) Does theme switching work?' },
  { label: 'context-compress', files: 'tui/context_compressor.py', prompt: 'Read the entire file. Check: 1) Does AutoCompactingContext avoid double compression? 2) Does truncation go in the right direction? 3) Does token estimation work? 4) Any issues with message selection for compaction?' },
  { label: 'session-integration', files: 'tui/session.py tui/config_integration.py tui/permission_handler.py tui/tool_executor.py', prompt: 'Read all files. Check: 1) Does session persistence work? 2) Does config integration load correctly? 3) Does permission handler support all modes? 4) Does tool executor dispatch correctly? 5) Any cross-module integration issues?' },
]

const scanResults = await parallel(
  SCAN_TARGETS.map(t => () =>
    agent(
      'Read these files COMPLETELY and find ALL bugs, issues, and problems:\n\n' + t.files + '\n\n' + t.prompt + '\n\nReturn a JSON object with an array of findings. Each finding has: file (string), line (number), severity (critical/high/medium/low), description (string), hermes_ref (string - what to search for in hermes to find the reference implementation). Return empty array if no bugs found.',
      { label: t.label, phase: 'Scan', schema: { type: 'object', properties: { findings: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, line: { type: 'number' }, severity: { type: 'string' }, description: { type: 'string' }, hermes_ref: { type: 'string' } }, required: ['file', 'description', 'severity'] } } }, required: ['findings'] } }
    )
  )
)

// Collect all findings
const allFindings = scanResults.filter(Boolean).flatMap(r => r.findings)
log('Scan complete: ' + allFindings.length + ' findings')

// ============ Phase 2: Compare with hermes ============
phase('Compare')

// Group findings by file for efficient comparison
const byFile = {}
for (const f of allFindings) {
  const key = f.file
  if (!byFile[key]) byFile[key] = []
  byFile[key].push(f)
}

const fileKeys = Object.keys(byFile)
log('Comparing ' + fileKeys.length + ' files with hermes reference')

const comparisons = await parallel(
  fileKeys.map(file => () => {
    const findings = byFile[file]
    const descriptions = findings.map((f, i) => (i+1) + '. ' + f.description + ' (hermes_ref: ' + (f.hermes_ref || 'N/A') + ')').join('\n')
    return agent(
      'You are comparing GrassFlow bugs with hermes reference implementations.\n\n' +
      'File: ' + file + '\n' +
      'Findings:\n' + descriptions + '\n\n' +
      'For each finding:\n' +
      '1. Search in E:\\opencode-desktop\\hermes-agent-main\\hermes-agent-main for similar code patterns\n' +
      '2. Compare the program structure\n' +
      '3. Provide a PRECISE fix recommendation with exact code changes\n\n' +
      'Return a JSON object with fixes array. Each fix has: file (string), finding_index (number - 1-based), root_cause (string), hermes_pattern (string - what hermes does differently), fix_description (string), exact_changes (string - the exact code to add/remove/change).',
      { label: 'compare-' + file.replace(/[\/\\]/g, '-'), phase: 'Compare', schema: { type: 'object', properties: { fixes: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, finding_index: { type: 'number' }, root_cause: { type: 'string' }, hermes_pattern: { type: 'string' }, fix_description: { type: 'string' }, exact_changes: { type: 'string' } }, required: ['file', 'finding_index', 'root_cause', 'fix_description', 'exact_changes'] } } }, required: ['fixes'] } }
    )
  })
)

const allFixes = comparisons.filter(Boolean).flatMap(r => r.fixes)
log('Comparison complete: ' + allFixes.length + ' fixes recommended')

// ============ Phase 3: Apply Fixes ============
phase('Fix')

// Group fixes by file
const fixesByFile = {}
for (const f of allFixes) {
  const key = f.file
  if (!fixesByFile[key]) fixesByFile[key] = []
  fixesByFile[key].push(f)
}

const fixFileKeys = Object.keys(fixesByFile)
log('Applying fixes to ' + fixFileKeys.length + ' files')

const fixResults = await parallel(
  fixFileKeys.map(file => () => {
    const fixes = fixesByFile[file]
    const fixList = fixes.map((f, i) =>
      'Fix #' + (i+1) + ' (finding #' + f.finding_index + '):\n' +
      '  Root cause: ' + f.root_cause + '\n' +
      '  Fix: ' + f.fix_description + '\n' +
      '  Exact changes: ' + f.exact_changes
    ).join('\n\n')
    return agent(
      'Apply ALL the following fixes to ' + file + '.\n\n' +
      'IMPORTANT:\n' +
      '- Read the file FIRST before making any changes\n' +
      '- Apply each fix using the Edit tool with exact old_string/new_string\n' +
      '- After all edits, read the file again to verify no syntax errors\n' +
      '- If a fix conflicts with another fix, apply them in order and adjust\n\n' +
      'Fixes to apply:\n' + fixList,
      { label: 'fix-' + file.replace(/[\/\\]/g, '-'), phase: 'Fix' }
    )
  })
)

log('Fixes applied to ' + fixFileKeys.length + ' files')

// ============ Phase 4: Verify ============
phase('Verify')

const verifyResult = await agent(
  'Verify ALL fixes across these files are consistent and correct:\n' +
  fixFileKeys.join(', ') + '\n\n' +
  'Steps:\n' +
  '1. Read each file\n' +
  '2. Check for syntax errors\n' +
  '3. Check cross-file consistency (callbacks, imports, function signatures)\n' +
  '4. Specifically verify mouse scroll works: <scroll-up>/<scroll-down> bindings exist, vertical_scroll is assigned, mouse_support=True is set, output_window is accessible\n' +
  '5. Report any remaining issues\n\n' +
  'Return a JSON object with: status (pass/fail), issues (array of remaining issues).',
  { label: 'verify-all', phase: 'Verify', schema: { type: 'object', properties: { status: { type: 'string' }, issues: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, description: { type: 'string' } }, required: ['file', 'description'] } } }, required: ['status'] } }
)

if (verifyResult && verifyResult.status === 'fail') {
  log('VERIFICATION FAILED: ' + verifyResult.issues.length + ' issues remain')
  for (const issue of verifyResult.issues) {
    log('  - ' + issue.file + ': ' + issue.description)
  }
} else {
  log('VERIFICATION PASSED: All fixes applied correctly')
}

return {
  scanFindings: allFindings.length,
  fixCount: allFixes.length,
  filesModified: fixFileKeys.length,
  verifyStatus: verifyResult?.status || 'unknown',
  remainingIssues: verifyResult?.issues || [],
}
