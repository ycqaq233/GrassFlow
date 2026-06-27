export const meta = {
  name: 'model-discovery',
  description: 'Add model discovery via provider API and update DeepSeek to V4',
  phases: [
    { title: 'Study', detail: '3 agents study opencode model discovery and GrassFlow config' },
    { title: 'Implement', detail: '3 agents implement model discovery and update defaults' },
    { title: 'Verify', detail: 'Verify all changes' },
  ],
}

phase('Study')

const [opencodeReport, configReport, deepseekReport] = await parallel([
  () => agent(
    'Study how opencode discovers models from providers. Search in E:\\opencode-desktop\\opencode-dev for: 1) model list/discovery code, GET /v1/models endpoint, 2) how model configs (context window, max tokens) are stored, 3) how /model command lists models. Report exact API endpoints and data storage.',
    { label: 'study:opencode-models', phase: 'Study' }
  ),
  () => agent(
    'Study GrassFlow model config. Read: 1) tui/layout.py (DEFAULT_MODEL), 2) core/config.py (LLMConfig, provider models), 3) core/llm.py (LLMManager), 4) tui/slash_commands.py (/model /models commands), 5) tui/config_integration.py (config loading). Report current defaults, model config structure, what needs changing.',
    { label: 'study:grassflow-config', phase: 'Study' }
  ),
  () => agent(
    'Research DeepSeek API model listing. Search in E:\\opencode-desktop\\hermes-agent-main and E:\\opencode-desktop\\opencode-dev for: 1) how they list DeepSeek models, 2) does https://api.deepseek.com/v1/models work, 3) current DeepSeek model names (deepseek-chat vs deepseek-v4 etc), 4) does deepseek-reasoner support tool calls. Report endpoint and model names.',
    { label: 'study:deepseek-api', phase: 'Study' }
  ),
])

log('Study phase complete')

phase('Implement')

const implResults = await parallel([
  () => agent(
    'Create core/model_discovery.py for GrassFlow. REFERENCE:\n' + opencodeReport + '\n\nCURRENT CONFIG:\n' + configReport + '\n\nTask: 1) Create discover_models(provider, api_key, base_url) that calls GET /v1/models, 2) ModelInfo dataclass with id, name, context_window, max_tokens, 3) Cache results, 4) Support deepseek/openai/anthropic/ollama, 5) Read core/config.py and core/llm_protocol.py first.',
    { label: 'impl:discovery', phase: 'Implement', isolation: 'worktree' }
  ),
  () => agent(
    'Update /models command to use model discovery. Task: 1) Read tui/slash_commands.py for /models handler, 2) Read tui/layout.py for DEFAULT_MODEL, 3) Update /models to discover models from provider API, 4) Fall back to hardcoded if discovery fails, 5) Show model capabilities. Read files first.',
    { label: 'impl:models-cmd', phase: 'Implement', isolation: 'worktree' }
  ),
  () => agent(
    'Update DeepSeek config for current models. DEEPSEEK INFO:\n' + deepseekReport + '\n\nTask: 1) Read C:\\Users\\25318\\.Grass\\config.json, 2) Read core/config.py, 3) Read tui/layout.py, 4) Update DeepSeek model list with current models, 5) If model name changed update DEFAULT_MODEL, 6) Do NOT change API key.',
    { label: 'impl:deepseek-v4', phase: 'Implement', isolation: 'worktree' }
  ),
])

log('Implementation phase complete')

phase('Verify')

const summary = implResults.map(function(r, i) { return '--- Agent ' + (i+1) + ' ---\n' + r }).join('\n\n')

const verifyReport = await agent(
  'Verify model discovery changes.\n\nChanges:\n' + summary + '\n\nTask: 1) Read core/model_discovery.py, tui/slash_commands.py, tui/layout.py, 2) Verify API endpoints correct, 3) Run: cd E:\\opencode-desktop\\GrassFlow && .venv\\Scripts\\python -m pytest tests/test_repl.py tests/test_config.py -q --tb=short, 4) Report issues.',
  { label: 'verify:all', phase: 'Verify' }
)

return { opencodeReport, configReport, deepseekReport, implResults, verifyReport }
