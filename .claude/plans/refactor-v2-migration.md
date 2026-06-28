# 重构计划：全面迁移到 DSL v2 类型系统

> 创建时间：2026-06-28
> 预估工作量：5-7 天（工作流编排执行）

---

## 决策记录

| # | 决策 | 理由 |
|---|------|------|
| 1 | 废除 v1 解析器，全面使用 v2 | v1 不支持 component/port/permission，设计过时 |
| 2 | v2 AST 为唯一类型系统 | 消除 AgentConfig 二义性 |
| 3 | Component → Agent 实例化 | 保留 Agent 基类的运行时语义 |
| 4 | 所有 agent 必须有 Component | 统一模型，inline agent 也声明为 Component |
| 5 | dsl_v2_ast.py 重命名为 core/models.py | 唯一数据模型来源 |
| 6 | 运行时记录类型移到 core/execution.py | 分离 DSL 定义和运行时状态 |
| 7 | Port 在 Scheduler 中处理 | _prepare_input 按 port 组装输入 |

---

## 影响范围

### 文件删除（2 个）
- `core/dsl_v2_ast.py` → 重命名为 `core/models.py`（替换旧文件）
- `tui/dsl_parser.py` → 删除（v1 解析器）

### 文件重写（4 个）
- `core/models.py` ← `dsl_v2_ast.py` 内容 + imports 更新
- `core/agent.py` ← 删除 AgentConfig，Agent 接受 Component
- `core/dag.py` ← 用 v2 Workflow/Connection 重写
- `core/scheduler.py` ← 用 v2 类型重写，port-aware 输入

### 文件新建（1 个）
- `core/execution.py` ← ExecutionRecord, AgentExecutionRecord, ExecutionStatus

### 文件大改（3 个）
- `core/llm_agent.py` ← LLMAgent 从 Component 构造，删除 AgentConfig 依赖
- `core/condition.py` ← 从 Component 构造，删除旧 AgentConfig
- `tui/cli.py` ← 全面重写 agent 创建逻辑，删除 v1 引用

### 文件小改（import 更新，~12 个）
- `core/storage.py`
- `core/context.py`
- `core/monitor.py`
- `core/db.py`
- `core/component_registry.py`
- `core/workflow_generator.py`
- `core/agent_component.py`
- `tui/display.py`
- `tui/monitor_panel.py`
- `tui/editor.py`
- `tui/templates.py`
- `tui/dsl_parser_v2.py`

### 测试文件（~12 个需要更新）
- `tests/test_dag.py`
- `tests/test_scheduler.py`
- `tests/test_dsl_parser.py` → 删除或改写为 v2
- `tests/test_core.py`
- `tests/test_condition.py`
- `tests/test_storage.py`
- `tests/test_db.py`
- `tests/test_monitor.py`
- `tests/test_llm_agent.py`
- `tests/test_dsl_parser_v2.py`
- `tests/test_agent_component.py`
- `tests/test_component_registry.py`

---

## 阶段拆分

### 阶段 1：类型系统迁移（Day 1）

**目标**：建立新的类型基础，不改变运行时行为。

#### 1.1 创建 `core/execution.py`

从旧 `core/models.py` 提取运行时类型：

```python
# core/execution.py
from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field

class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

class AgentExecutionRecord(BaseModel):
    agent_name: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class ExecutionRecord(BaseModel):
    workflow_name: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    agent_records: Dict[str, AgentExecutionRecord] = Field(default_factory=dict)
    error: Optional[str] = None

    def start(self):
        self.status = ExecutionStatus.RUNNING
        self.started_at = datetime.now()

    def complete(self):
        self.status = ExecutionStatus.COMPLETED
        self.completed_at = datetime.now()
        if self.started_at:
            self.duration_ms = int((self.completed_at - self.started_at).total_seconds() * 1000)

    def fail(self, error: str):
        self.status = ExecutionStatus.FAILED
        self.error = error
        self.completed_at = datetime.now()
        if self.started_at:
            self.duration_ms = int((self.completed_at - self.started_at).total_seconds() * 1000)
```

#### 1.2 重命名 `dsl_v2_ast.py` → `core/models.py`

- 删除旧 `core/models.py`
- 复制 `core/dsl_v2_ast.py` 为 `core/models.py`
- 将 `dataclass` 改为 `pydantic.BaseModel`（与旧 models.py 一致，支持序列化/校验）
- 添加 `__all__` 导出列表

#### 1.3 更新所有 imports

| 文件 | 旧 import | 新 import |
|------|----------|----------|
| `core/dag.py` | `from core.models import Workflow, Edge, InteractionType` | `from core.models import Workflow, Connection` |
| `core/scheduler.py` | `from core.models import Workflow, AgentConfig, Edge, ...` | `from core.models import Workflow, AgentInstance` + `from core.execution import ...` |
| `core/storage.py` | `from core.models import Workflow` | `from core.models import Workflow`（不变） |
| `core/monitor.py` | `from core.models import ExecutionRecord, ...` | `from core.execution import ExecutionRecord, ...` |
| `core/db.py` | `from core.models import ExecutionRecord, ...` | `from core.execution import ExecutionRecord, ...` |
| `core/component_registry.py` | `from core.dsl_v2_ast import Component, ParseResult` | `from core.models import Component, ParseResult` |
| `tui/dsl_parser_v2.py` | `from core.dsl_v2_ast import ...` | `from core.models import ...` |
| `tui/cli.py` | `from core.models import Workflow` | `from core.models import Workflow, Component, AgentInstance` |
| `tui/display.py` | `from core.models import ExecutionRecord, ...` | `from core.execution import ExecutionRecord, ...` |
| `tui/monitor_panel.py` | `from core.models import Workflow, ExecutionRecord, ...` | `from core.models import Workflow` + `from core.execution import ...` |
| `tui/editor.py` | `from core.models import ...` | `from core.models import ...` + `from core.execution import ...` |
| `tui/templates.py` | `from core.models import Workflow, AgentConfig, Edge, ...` | 全面重写（阶段 3） |

#### 1.4 删除旧文件

- 删除 `core/dsl_v2_ast.py`（内容已移到 `core/models.py`）
- 删除 `tui/dsl_parser.py`（v1 解析器）

**验证**：所有 import 正确，`python -c "from core.models import *; from core.execution import *"` 成功。

---

### 阶段 2：Agent 基类重构（Day 2）

**目标**：Agent 从 Component 构造，删除旧 AgentConfig。

#### 2.1 重写 `core/agent.py`

```python
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import jsonschema
from core.models import Component

class Agent(ABC):
    """所有 Agent 的运行时基类"""

    def __init__(self, component: Component):
        self.component = component
        self.name = component.name
        self.on_fail = component.on_fail
        self.retry_count = component.retry_count
        # 从 ports 提取 schemas
        self.input_schema = self._ports_to_schema(component.ports, "input")
        self.output_schema = self._ports_to_schema(component.ports, "output")

    def _ports_to_schema(self, ports, direction: str) -> Dict[str, Any]:
        """将 port 定义转换为 JSON Schema"""
        properties = {}
        for port in ports:
            if port.direction == direction:
                properties[port.name] = {"type": port.type}
        if not properties:
            return {}
        return {"type": "object", "properties": properties}

    def validate_input(self, data: Dict[str, Any]) -> bool: ...
    def validate_output(self, data: Dict[str, Any]) -> bool: ...

    @abstractmethod
    async def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        # 保持原有模板方法逻辑
        ...
```

关键变更：
- 删除 `AgentConfig` 类
- `__init__` 接受 `Component` 而非 `AgentConfig`
- 从 `Component.ports` 自动推导 `input_schema` / `output_schema`

#### 2.2 重写 `core/llm_agent.py`

```python
from core.agent import Agent
from core.models import Component, ModelConfig

class LLMAgent(Agent):
    def __init__(self, component: Component):
        super().__init__(component)
        self.system_prompt = component.system_prompt
        self.temperature = component.model.temperature or 0.7
        self.max_tokens = component.model.max_tokens
        self.model_name = _resolve_model(component.model.default or "default")
        self._client = ...  # 从 LLM manager 获取
```

删除 `AgentConfig` 的所有引用，LLMAgent 直接从 Component 读取配置。

#### 2.3 重写 `core/condition.py`

```python
from core.agent import Agent
from core.models import Component

class ConditionAgent(Agent):
    def __init__(self, component: Component, rules: list):
        super().__init__(component)
        self.rules = rules
        self.route_field = "route"
```

**验证**：`LLMAgent(component)` 和 `ConditionAgent(component, rules)` 正常构造。

---

### 阶段 3：DAG + Scheduler 重构（Day 3-4）

**目标**：DAG 和 Scheduler 使用 v2 类型，支持 port-aware 数据流。

#### 3.1 重写 `core/dag.py`

输入从 `core.models.Workflow`（旧）改为 v2 `Workflow`：

```python
from core.models import Workflow, Connection

class DAG:
    def __init__(self, workflow: Workflow):
        self.workflow = workflow
        self._adjacency: Dict[str, List[str]] = defaultdict(list)
        self._reverse_adjacency: Dict[str, List[str]] = defaultdict(list)
        self._connections: Dict[str, List[Connection]] = defaultdict(list)

        # 从 v2 connections 构建邻接表
        for conn in workflow.connections:
            for target in conn.target_agents:
                self._adjacency[conn.source_agent].append(target)
                self._reverse_adjacency[target].append(conn.source_agent)
                self._connections[conn.source_agent].append(conn)

        # 节点从 workflow.agents (AgentInstance) 获取
        nodes = {agent.name for agent in workflow.agents}
        if self._has_cycle(nodes):
            raise DAGError("Cycle detected")
```

关键变更：
- `workflow.edges` → `workflow.connections`
- `Edge` → `Connection`
- 节点从 `workflow.agents`（`AgentInstance` 列表）获取
- `get_condition_connections()` 替代 `get_condition_edges()`

#### 3.2 重写 `core/scheduler.py`

```python
from core.models import Workflow, AgentInstance, Connection
from core.execution import ExecutionRecord, AgentExecutionRecord, ExecutionStatus
from core.agent import Agent

class Scheduler:
    def __init__(self, workflow: Workflow, agents: Dict[str, Agent]):
        self.workflow = workflow
        self.agents = agents
        self.dag = DAG(workflow)
        self.execution_record = ExecutionRecord(workflow_name=workflow.name)

    def _prepare_input(self, agent_name: str, context: WorkflowContext) -> Dict[str, Any]:
        """Port-aware 输入组装"""
        # 找到该 agent 的所有入连接
        incoming = self._get_incoming_connections(agent_name)

        port_inputs = {}
        deps = {}
        for conn in incoming:
            source_output = context.get(conn.source_agent)
            deps[conn.source_agent] = source_output

            # 按 port 映射数据
            if conn.source_port and conn.target_ports:
                # 有明确 port 映射：A.x -> B.y
                for target_port in conn.target_ports:
                    if conn.source_port in source_output:
                        port_inputs[target_port] = source_output[conn.source_port]
            else:
                # 默认端口：整个输出传递
                port_inputs.update(source_output)

        # 合并 port 输入和依赖信息
        result = port_inputs if port_inputs else {}
        result["_deps"] = deps
        return result

    def _should_execute(self, agent_name: str, context: WorkflowContext) -> bool:
        """基于 v2 Connection 的条件判断"""
        incoming = self._get_incoming_connections(agent_name)
        if not incoming:
            return True

        # 条件分支：检查 source agent 的 route 输出
        # v2 没有显式 InteractionType.CONDITION，通过 Connection 语义判断
        for conn in incoming:
            source_output = context.get(conn.source_agent)
            if not source_output:
                return False
            # 如果 source 有 route 字段且 conn 有条件条件
            route = source_output.get("route")
            if route and conn.source_port == f"[{route}]":
                return True

        # 普通顺序：检查所有依赖完成
        return self.dag.is_ready(agent_name, set(context._data.keys()))
```

关键变更：
- `agents` 类型从 `Dict[str, Any]` 改为 `Dict[str, Agent]`
- `_prepare_input` 按 port 组装输入
- `_should_execute` 基于 Connection 判断
- 删除 `InteractionType` 引用
- `agent.run()` 改为 `agent.execute()`（启用 schema 校验）

#### 3.3 更新 `core/context.py`

```python
class WorkflowContext:
    """工作流上下文 — 支持 port 级数据访问"""

    def set_port(self, agent_id: str, port_name: str, data: Any):
        """写入指定 port 的数据"""
        if agent_id not in self._data:
            self._data[agent_id] = {}
        self._data[agent_id][port_name] = data

    def get_port(self, agent_id: str, port_name: str) -> Any:
        """读取指定 port 的数据"""
        return self._data.get(agent_id, {}).get(port_name)
```

**验证**：用示例 `.gf` 文件端到端测试 DAG 构建 → Scheduler 执行。

---

### 阶段 4：CLI + 模板重写（Day 5）

**目标**：CLI 使用 v2 类型，删除所有 v1 残留。

#### 4.1 重写 `tui/cli.py` 的 agent 创建逻辑

```python
def _create_agents_from_workflow(workflow, parse_result) -> Dict[str, Agent]:
    """从 v2 Workflow + Components 创建 Agent 实例"""
    agents = {}
    component_map = {c.name: c for c in parse_result.components}

    for agent_inst in workflow.agents:
        # 查找 Component
        if agent_inst.component:
            component = component_map.get(agent_inst.component)
            if not component:
                raise ValueError(f"Component '{agent_inst.component}' not found")
            # 应用 overrides
            component = _apply_overrides(component, agent_inst.overrides)
        else:
            # inline agent → 自动生成 Component
            component = _inline_to_component(agent_inst)

        # 实例化 Agent
        agent = _instantiate_agent(component)
        agents[agent_inst.name] = agent

    return agents

def _instantiate_agent(component: Component) -> Agent:
    """根据 Component 类型创建 Agent 实例"""
    # condition 类型
    if component.name.endswith("_condition") or any(
        p.name == "route" for p in component.ports if p.direction == "output"
    ):
        return ConditionAgent(component, rules=...)
    # 默认 LLM
    return LLMAgent(component)
```

#### 4.2 重写 `tui/templates.py`

模板改为 v2 Component + Workflow 格式：

```python
TEMPLATES = {
    "ticket_processing": {
        "components": [
            Component(name="classifier", model=ModelConfig(default="default"),
                     system_prompt="分类工单: {input}", ports=[...]),
            Component(name="router", ...),
            Component(name="human_handler", ...),
            Component(name="bot_handler", ...),
        ],
        "workflow": Workflow(name="ticket_processing", agents=[...], connections=[...]),
    },
}
```

#### 4.3 CLI 命令 `run` 重写

```python
@main.command()
@click.argument("workflow_file")
def run(workflow_file):
    # 1. 解析 .gf 文件
    parse_result = parse_file(workflow_file)  # 用 v2 parser
    workflow = parse_result.workflows[0]

    # 2. 创建 Agent 实例
    agents = _create_agents_from_workflow(workflow, parse_result)

    # 3. 构建 DAG + Scheduler
    scheduler = Scheduler(workflow, agents)
    context = WorkflowContext()

    # 4. 执行
    record = asyncio.run(scheduler.run(context))

    # 5. 保存 + 显示
    execution_db.save_execution(record)
    display.print_execution_result(record)
```

**验证**：`grassflow run examples/ticket_processing.gf` 端到端成功。

---

### 阶段 5：测试迁移 + 清理（Day 6-7）

#### 5.1 测试文件更新

| 测试文件 | 变更 |
|---------|------|
| `test_dag.py` | 用 v2 Workflow/Connection 重写 fixtures |
| `test_scheduler.py` | 用 v2 类型 + Component 构造 Agent |
| `test_dsl_parser.py` | 删除或改写为 v2 parser 测试 |
| `test_core.py` | 更新 Agent 构造方式 |
| `test_condition.py` | 从 Component 构造 ConditionAgent |
| `test_storage.py` | 用 v2 Workflow 测试序列化 |
| `test_db.py` | import 更新（core.execution） |
| `test_monitor.py` | import 更新（core.execution） |
| `test_llm_agent.py` | 从 Component 构造 LLMAgent |
| `test_dsl_parser_v2.py` | import 路径更新 |
| `test_agent_component.py` | import 路径更新 |
| `test_component_registry.py` | import 路径更新 |

#### 5.2 清理

- 删除 `core/dsl_v2_ast.py`（已迁移）
- 删除 `tui/dsl_parser.py`（v1 解析器）
- 删除 `tests/test_dsl_parser.py`（v1 测试）
- 更新 `CLAUDE.md` 中的文件结构
- 更新 `项目制作计划.md`

#### 5.3 全量测试

```bash
.venv\Scripts\python -m pytest tests/ -q
```

---

## 风险和缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| v2 parser 输出与新 types 不兼容 | 高 | 阶段 1 先验证 parser 输出 |
| Condition agent 的 rules 在 Component 中无直接对应 | 中 | Component 可加扩展字段，或在 AgentInstance.overrides 中传递 |
| 现有 .af 文件全部作废 | 中 | 提供迁移脚本或文档 |
| 测试大量失败 | 高 | 按阶段逐步迁移，每阶段验证 |
| port-aware 数据流增加复杂度 | 中 | 先实现默认端口（无 port 映射），再支持显式 port |

---

## 验收标准

1. `from core.models import Component, Workflow, Connection, ParseResult` 成功
2. `from core.execution import ExecutionRecord, ExecutionStatus` 成功
3. `core/agent.py` 中无 `AgentConfig` 类
4. `Agent.__init__` 接受 `Component`
5. `DAG(workflow)` 接受 v2 `Workflow`，无环检测正常
6. `Scheduler(workflow, agents).run(context)` 端到端执行成功
7. `grassflow run examples/ticket_processing.gf` 成功
8. `pytest tests/ -q` 全部通过
9. `tui/dsl_parser.py` 已删除
10. `core/dsl_v2_ast.py` 已删除
