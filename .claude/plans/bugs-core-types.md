# Core 类型不匹配 Bug 扫描报告

**扫描时间**: 2026-06-28
**扫描范围**: `core/` 目录下 7 个 Python 文件
**扫描目标**: 查找旧类型 (AgentConfig, InteractionType, Edge) 和旧 API (workflow.edges, workflow.get_agent, WorkflowV1) 的残留引用

---

## 扫描总结

### Grep 搜索结果

| 模式 | 匹配数 | 说明 |
|------|--------|------|
| `AgentConfig` | 0 (实际) | 仅 `llm_agent.py` 注释中提到，无实际使用 |
| `InteractionType` | 0 | 完全无引用 |
| `Edge` (作为类型) | 0 | 完全无引用 |
| `workflow.edges` | 0 | 完全无引用 |
| `workflow.get_agent` | 0 | 完全无引用 |
| `WorkflowV1` | 0 | 完全无引用 |

**结论**: 所有 7 个目标文件已完全迁移到 v2 类型系统，未发现旧类型残留。

---

## 逐文件分析

### 1. `core/dag.py` -- 无类型 Bug

- **导入**: `Workflow`, `Connection` (v2)
- **使用**: `workflow.connections`, `workflow.agents`, `conn.source_agent`, `conn.target_agents` -- 全部正确
- **状态**: 干净

### 2. `core/scheduler.py` -- 无类型 Bug

- **导入**: `Workflow`, `AgentInstance` (v2), `ExecutionRecord`, `AgentExecutionRecord`, `ExecutionStatus` (Pydantic v2)
- **使用**: `workflow.agents`, `agent_instance.overrides`, `agent_instance.name` -- 全部正确
- **状态**: 干净

### 3. `core/context.py` -- 1 个代码质量问题

- **导入**: `Agent` (v2 基类，从 Component 构造)
- **状态**: 类型正确，但有死参数

```
FILE: core/context.py
ISSUE: get_dependency_data() 的 agent 参数从未被使用（死代码）
LINE: 42
CURRENT: def get_dependency_data(self, agent: Agent, dependencies: List[str]) -> Dict[str, Any]:
FIX:     def get_dependency_data(self, dependencies: List[str]) -> Dict[str, Any]:
```

### 4. `core/storage.py` -- 无类型 Bug

- **导入**: `Workflow`, `AgentInstance`, `Connection`, `Port`, `ModelConfig`, `MCPConfig`, `PermissionConfig` (全部 v2)
- **使用**: `_dict_to_workflow()` 正确重建 v2 dataclass，字段匹配 (`component`, `overrides`, `inline_ports`, `inline_system_prompt`, `routing_rules`)
- **状态**: 干净

### 5. `core/monitor.py` -- 无类型 Bug

- **导入**: `ExecutionRecord`, `AgentExecutionRecord`, `ExecutionStatus` (Pydantic v2)
- **使用**: `record.agent_records`, `record.status.value`, `record.total_duration_ms` -- 全部正确
- **注意**: `self.check_quality` (bool 属性) 与 `self.check_quality_for_agent()` (方法) 命名相近，易混淆，但不是类型 bug
- **状态**: 干净

### 6. `core/agent_component.py` -- 无类型 Bug

- **导入**: `Component`, `Workflow`, `AgentInstance`, `Connection`, `MCPConfig`, `ModelConfig`, `PermissionConfig`, `Port` (全部 v2)
- **使用**: `ComponentAgent.__init__` 接受 `Component` (v2), `ComponentFactory.create` 接受 `AgentInstance` (v2), `WorkflowInstantiator.instantiate` 接受 `Workflow` (v2) -- 全部正确
- **状态**: 干净

### 7. `core/workflow_generator.py` -- 1 个命名不一致

- **导入**: `LLMClient`, `LLMError` (正确)
- **注意**: 该文件不直接使用 Workflow/Connection 等 v2 类型，仅生成 DSL 文本

```
FILE: core/workflow_generator.py
ISSUE: GenerationResult.edge_count 使用 v1 术语 "edge"，v2 中应为 "connection"
LINE: 176
CURRENT: edge_count: int
FIX:     connection_count: int
```

对应的 `_count_edges()` 方法 (line 413) 和 `generate_workflow()` 中的赋值 (line 284) 也需同步重命名。

---

## 结论

**核心类型系统迁移状态: 完成。**

7 个目标文件中没有发现任何对旧类型 (AgentConfig, InteractionType, Edge, WorkflowV1) 或旧 API (workflow.edges, workflow.get_agent) 的引用。所有文件已统一使用 v2 类型:

- `Workflow` (dataclass) -- 替代 WorkflowV1
- `Connection` (dataclass) -- 替代 Edge
- `AgentInstance` (dataclass) -- 替代 AgentConfig
- `Component` (dataclass) -- 新增的组件系统
- `ExecutionRecord` / `AgentExecutionRecord` (Pydantic v2) -- 运行时记录

发现的 2 个问题均为代码质量/命名问题，不影响运行时正确性:
1. `context.py`: 死参数 `agent` 在 `get_dependency_data()` 中未使用
2. `workflow_generator.py`: `edge_count` 命名与 v2 术语不一致
