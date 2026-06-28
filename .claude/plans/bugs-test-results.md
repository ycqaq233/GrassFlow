# Test Failure Analysis

**Run**: `pytest tests/ -q --tb=short`
**Result**: 35 failed, 1134 passed, 195 warnings in 42.53s

---

## Group 1: ComponentAgent — `agent.config` AttributeError (18 tests)

**Affected tests**:
- `test_agent_component.py::TestComponentAgent::test_create_from_component`
- `test_agent_component.py::TestRuntimeOverrides::test_override_model`
- `test_agent_component.py::TestRuntimeOverrides::test_override_on_fail`
- `test_agent_component.py::TestRuntimeOverrides::test_override_retry_count`
- `test_agent_component.py::TestRuntimeOverrides::test_override_multiple`
- `test_agent_component.py::TestRuntimeOverrides::test_override_preserves_system_prompt`
- `test_agent_component.py::TestRuntimeOverrides::test_no_override_uses_component_defaults`
- `test_agent_component.py::TestComponentFactory::test_create_with_overrides`
- `test_agent_component.py::TestComponentFactory::test_create_inline_agent`
- `test_agent_component.py::TestComponentFactory::test_create_inline_with_default_model`
- `test_agent_component.py::TestComponentFactory::test_create_with_explicit_component`
- `test_agent_component.py::TestWorkflowInstantiator::test_instantiate_with_inline_agent`
- `test_agent_component.py::TestWorkflowInstantiator::test_instantiate_with_overrides`
- `test_agent_component.py::TestInlineMerge::test_merge_inline_system_prompt`
- `test_agent_component.py::TestInlineMerge::test_create_inline_merges_ports`
- `test_agent_component.py::TestIntegration::test_full_workflow_instantiation`
- `test_agent_component.py::TestEdgeCases::test_component_with_no_model`
- `test_agent_component.py::TestEdgeCases::test_override_unknown_key_ignored`

**ERROR**: `AttributeError: 'ComponentAgent' object has no attribute 'config'`

**CAUSE**: Tests access `agent.config.model`, `agent.config.on_fail`, `agent.config.retry_count`, `agent.config.prompt` etc. The `Agent` base class stores the component as `self._component` and exposes it via `@property component`. There is no `config` attribute or property. The Component's model is at `component.model.default`, not `config.model`.

**FIX**: Either:
1. Add a `config` property to `Agent` or `ComponentAgent` that returns a proxy object with `.model`, `.on_fail`, `.retry_count`, `.prompt` attributes mapping to the Component's fields, OR
2. Update all 18 tests to use the correct attribute path: `agent.component.model.default` instead of `agent.config.model`, `agent.component.on_fail` instead of `agent.config.on_fail`, etc.

---

## Group 2: ComponentAgent — `agent.name` vs `agent.agent_name` (3 tests)

**Affected tests**:
- `test_agent_component.py::TestComponentAgent::test_create_with_agent_name`
- `test_agent_component.py::TestComponentFactory::test_create_from_registry`
- `test_agent_component.py::TestComponentFactory::test_create_with_explicit_component` (also in Group 1)

**ERROR**: `AssertionError: assert 'code-reviewer' == 'my-reviewer'`

**CAUSE**: `ComponentAgent.__init__` sets `self._agent_name = agent_name or component.name`, but `Agent.__init__` sets `self.name = component.name`. The tests expect `agent.name` to reflect the override, but `agent.name` always returns the component's original name. Only `agent.agent_name` returns the overridden name.

**FIX**: Either:
1. In `ComponentAgent.__init__`, after `super().__init__(effective)`, set `self.name = agent_name or component.name` to override the base class value, OR
2. Update tests to assert `agent.agent_name == "my-reviewer"` instead of `agent.name == "my-reviewer"`.

Note: The factory (`ComponentFactory.create`) passes `agent_name=agent_instance.name`, so this likely needs the implementation fix (option 1) since DSL instances should have their instance name as `agent.name`.

---

## Group 3: Context Compressor — Token Overhead Mismatch (8 tests)

**Affected tests**:
- `test_context_compressor.py::TestTokenEstimation::test_estimate_messages_tokens_single`
- `test_context_compressor.py::TestTokenEstimation::test_estimate_messages_tokens_multiple`
- `test_context_compressor.py::TestTokenEstimation::test_estimate_messages_tokens_with_name`
- `test_context_compressor.py::TestMessageSelection::test_select_multiple_turns`
- `test_context_compressor.py::TestMessageSelection::test_select_preserves_system_at_start`
- `test_context_compressor.py::TestMessageSelection::test_select_custom_tail_turns`
- `test_context_compressor.py::TestOverflowDetection::test_is_overflow_exact_limit`
- `test_context_compressor.py::TestContextCompressor::test_should_compact_above_threshold_and_near_limit`
- `test_context_compressor.py::TestContextCompressor::test_compact_and_rebuild`
- `test_context_compressor.py::TestContextCompressor::test_compact_llm_error`
- `test_context_compressor.py::TestContextCompressor::test_compact_empty_llm_response`

**ERROR**: `assert 11 == (1 + 4)` — tests expect 4 tokens overhead per message, actual is 10.

**CAUSE**: `estimate_messages_tokens()` in `context_compressor.py` adds 10 tokens per message as role/overhead (line 220: `total += 10`), aligned with hermes. Tests were written expecting 4 tokens overhead. The constant `CHARS_PER_TOKEN = 4` means `estimate_tokens("hello")` = `round(5/4)` = 1. So per-message total is `1 + 10 = 11`, but tests expect `1 + 4 = 5`.

**FIX**: Either:
1. Update all 8+ tests to use `content_tokens + 10` instead of `content_tokens + 4`, adjusting downstream assertions accordingly, OR
2. Change the implementation to use 4 tokens overhead (not recommended — 10 is more accurate for OpenAI-style message formatting).

---

## Group 4: LLMClient — Default Model Name (1 test)

**Affected test**:
- `test_llm.py::TestLLMClient::test_llm_client_default_values`

**ERROR**: `assert 'default' == 'gpt-4'`

**CAUSE**: `LLMClient.__init__` has `model: str = "default"` (line 34), but the test expects `"gpt-4"`. The default was likely changed to `"default"` to support config-based model resolution.

**FIX**: Either:
1. Update the test to expect `"default"`, OR
2. Change `LLMClient.__init__` default back to `"gpt-4"` if the config resolution happens elsewhere.

---

## Group 5: Session — `message_count` Not Updated in Cache (1 test)

**Affected test**:
- `test_session.py::TestEdgeCases::test_session_message_count_accuracy`

**ERROR**: `assert 0 == 4`

**CAUSE**: `SessionManager.get_session()` caches the `SessionInfo` object in `self._active_sessions` on first access (line 720-721). When `create_session` is called, the `SessionInfo` with `message_count=0` is cached. Subsequent `add_message` calls update `message_count` in the SQLite database, but the cached `SessionInfo` object is never refreshed. When `get_session` is called again, it returns the stale cached object with `message_count=0`.

**FIX**: In `SessionManager.add_message()`, after calling `self._db.add_message(message)`, update the cached `SessionInfo`:
```python
with self._lock:
    if session_id in self._active_sessions:
        self._active_sessions[session_id].message_count += 1
        self._active_sessions[session_id].updated_at = datetime.now()
```

---

## Group 6: MCPToolAdapter — ID Separator (2 tests)

**Affected tests**:
- `test_tool_registry.py::TestMCPToolAdapter::test_to_tool_def_format`
- `test_tool_registry.py::TestMCPToolAdapter::test_register_mcp_tools`

**ERROR**: `assert 'mcp_github_create_issue' == 'mcp_github.create_issue'`

**CAUSE**: `MCPToolAdapter.__init__` constructs `_full_id` as `f"mcp_{server_name}_{tool_id}"` using underscore separator (line 520). Tests expect dot separator: `"mcp_github.create_issue"`. This is likely because dots are problematic in some contexts (JSON paths, dict keys with dot notation).

**FIX**: Either:
1. Change `_full_id` construction to use dot: `f"mcp_{server_name}.{tool_id}"`, OR
2. Update tests to expect underscore format: `"mcp_github_create_issue"`.

Note: The dot format is more readable and matches MCP convention. Consider changing the implementation to use dots, but verify no downstream code depends on underscores.

---

## Summary Table

| Group | Tests | Root Cause | Category |
|-------|-------|-----------|----------|
| 1 | 18 | Missing `config` property on ComponentAgent | API mismatch |
| 2 | 3 | `agent.name` not set to `agent_name` override | Logic bug |
| 3 | 8+ | Token overhead constant 10 vs test expecting 4 | Test/impl mismatch |
| 4 | 1 | Default model "default" vs "gpt-4" | Config change |
| 5 | 1 | Session cache not invalidated on add_message | Cache bug |
| 6 | 2 | MCP tool ID uses `_` separator, test expects `.` | Separator choice |

**Total unique root causes**: 6
**Recommended fix order**: Group 5 (cache bug) > Group 2 (logic bug) > Group 1 (API design) > Group 3 (test update) > Group 6 (convention) > Group 4 (config)
