# TUI Import and Type Error Scan Results

Scan date: 2026-06-28

---

## CRITICAL: Import Errors (blocks module loading)

### 1. tui/monitor_panel.py — 4 broken imports from core.models

**ISSUE**: Line 26 imports `WorkflowV1`, `ExecutionRecord`, `AgentExecutionRecord`, `ExecutionStatus` from `core.models`. All four names do NOT exist in `core.models`.

- `WorkflowV1` does not exist in `core.models` (only `Workflow` exists)
- `ExecutionRecord` is in `core.execution`, not `core.models`
- `AgentExecutionRecord` is in `core.execution`, not `core.models`
- `ExecutionStatus` is in `core.execution`, not `core.models`

**LINE**: 26

**CURRENT**:
```python
from core.models import WorkflowV1 as Workflow, ExecutionRecord, AgentExecutionRecord, ExecutionStatus
```

**FIX**:
```python
from core.models import Workflow
from core.execution import ExecutionRecord, AgentExecutionRecord, ExecutionStatus
```

**IMPACT**: `tui.monitor_panel` cannot be imported at all. This breaks:
- `tui/cli.py` line 605: `from tui.monitor_panel import execute_with_monitor` (in `monitor_cmd` function)
- Any code path that uses the `--watch` flag in `grassflow monitor`

---

## Files with NO import/type errors (all 9 pass)

| File | Status |
|------|--------|
| tui/cli.py | OK — all imports resolve |
| tui/dsl_parser.py | OK |
| tui/dsl_parser_v2.py | OK |
| tui/templates.py | OK |
| tui/display.py | OK (uses `core.execution` correctly) |
| tui/editor.py | OK |
| tui/repl.py | OK |
| tui/agent_loop.py | OK |
| tui/agent_integration.py | OK |

---

## Detailed verification results

### tui/cli.py
- `from core.models import Workflow, AgentInstance, Component, ModelConfig` — OK
- `from core.context import WorkflowContext` — OK
- `from core.scheduler import Scheduler` — OK
- `from core.condition import ConditionAgent, make_condition_component` — OK
- `from core.llm_agent import LLMAgent` — OK
- `from core.storage import workflow_storage, _dataclass_to_dict` — OK
- `from core.db import execution_db` — OK
- `from core.monitor import monitor` — OK
- `from tui.dsl_parser import parse_file, parse_file_result` — OK
- `from tui.display import display, progress_display` — OK
- `from tui.error_handler import handle_cli_error, ErrorContext` — OK
- Agent creation logic (lines 154-190): `ConditionAgent(component, rules=rules)` and `LLMAgent(component=component)` match constructor signatures — OK
- `Scheduler(workflow, agents)` matches constructor — OK
- `scheduler.run(context)` returns `ExecutionRecord` — OK
- `execution_db.save_execution(result)` — OK
- `monitor.monitor(result)` — OK
- `_generate_dsl(workflow)` — OK, tested successfully

### tui/dsl_parser.py
- `from tui.dsl_parser_v2 import DSLv2Parser, DSLError` — OK
- `from core.models import Workflow, Component, ParseResult` — OK
- All functions (`parse_file`, `parse_file_result`, `parse_dsl`) — OK

### tui/dsl_parser_v2.py
- `from core.models import Port, MCPConfig, PermissionConfig, ModelConfig, Component, AgentInstance, Connection, Workflow, ParseResult` — OK
- All classes and methods — OK

### tui/templates.py
- `from core.models import Workflow, AgentInstance, Connection, Component, Port, ModelConfig` — OK
- `create_from_template()` creates `Connection` with keyword args matching constructor — OK

### tui/display.py
- `from core.execution import ExecutionRecord, AgentExecutionRecord, ExecutionStatus` — OK (correct module)
- Fallback stubs for when `core.execution` not available — OK
- `record.workflow_name`, `record.status.value`, `record.total_duration_ms`, `record.agent_records` — all exist on `ExecutionRecord` — OK

### tui/editor.py
- All textual imports — OK
- `from core.models import Workflow, AgentInstance, Connection, Component, Port, ModelConfig` — OK
- `from core.dag import DAG, DAGError` — OK

### tui/repl.py
- All prompt_toolkit imports — OK
- `from tui.config_integration import config_manager, get_theme_name` — OK
- `from tui.agent_integration import AgentIntegration` — OK
- `from tui.fallback import run_fallback_mode` — OK
- `from tui.permission_handler import get_permission_handler` — OK
- `from tui.layout import (...)` — all symbols exist — OK
- `from tui.session import SessionInfo, session_manager` — OK
- `from tui.slash_commands import SlashCommandCompleter, command_registry, register_skill_commands` — OK
- `save_config(updated, scope="global")` from `tui.config_integration` — OK

### tui/agent_loop.py
- All `core.llm_protocol` imports — OK
- All `core.tool_registry` imports — OK
- `from tui.permission_handler import get_permission_handler, PermissionHandler` — OK
- `DoomLoopDetector` import wrapped in try/except — OK

### tui/agent_integration.py
- All imports — OK
- `from tui.agent_loop import AgentLoop, create_agent_loop_from_config` — OK
- `from core.tool_registry import get_default_registry, register_builtin_tools` — OK
- `from tui.mcp_integration import MCPManager` — OK
- `from tui.skills_system import get_skills_manager` — OK
