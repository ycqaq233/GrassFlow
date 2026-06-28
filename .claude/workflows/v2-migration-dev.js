export const meta = {
  name: 'v2-migration-dev',
  description: 'DSL v2 类型系统迁移 + DAG 集成 + REPL 智能编排设计',
  phases: [
    { title: 'Analyze', detail: '3 agents 并行分析 core/tui/tests' },
    { title: 'Migrate', detail: '10 agents 并行迁移，每个专注 1-2 个文件' },
    { title: 'Merge', detail: '合并 worktree 分支，解决冲突' },
    { title: 'Integrate', detail: 'DAG 集成验证 + REPL 智能编排设计' },
  ],
}

// ============================================================
// Phase 1: 并行分析（3 agents）
// ============================================================
phase('Analyze')
log('Phase 1: 3 agents 并行分析项目架构...')

const analysisResults = await parallel([
  () => agent(
    `分析 GrassFlow 的 core/ 类型系统模块。读取以下文件并输出结构化报告：

文件清单：
- core/models.py（旧类型系统）
- core/dsl_v2_ast.py（新类型系统）
- core/agent.py（Agent 基类 + AgentConfig）
- core/llm_agent.py（LLMAgent）
- core/condition.py（ConditionAgent）

对每个文件，输出：
1. 完整的类/函数签名
2. import 依赖
3. 与其他文件的耦合关系
4. 迁移时需要注意的问题

最后输出类型映射表：旧类型 → 新类型的对应关系。

将报告写入 .claude/plans/analysis-types.md`,
    { label: 'analyze-types', phase: 'Analyze', effort: 'high' }
  ),

  () => agent(
    `分析 GrassFlow 的 core/ 引擎模块。读取以下文件并输出结构化报告：

文件清单：
- core/dag.py（DAG 引擎）
- core/scheduler.py（调度器）
- core/context.py（上下文）
- core/storage.py（存储）
- core/monitor.py（监控）
- core/db.py（数据库）
- core/component_registry.py（组件注册）

对每个文件，输出：
1. 完整的类/函数签名
2. import 依赖（特别是对 core.models 的依赖）
3. 需要修改的具体行和内容
4. 迁移风险

将报告写入 .claude/plans/analysis-engine.md`,
    { label: 'analyze-engine', phase: 'Analyze', effort: 'high' }
  ),

  () => agent(
    `分析 GrassFlow 的 tui/ 模块和测试文件。读取以下文件并输出结构化报告：

TUI 文件：
- tui/cli.py（CLI 入口，重点分析 agent 创建逻辑）
- tui/dsl_parser.py（v1 解析器，将被删除）
- tui/dsl_parser_v2.py（v2 解析器）
- tui/templates.py（模板系统）
- tui/display.py（显示层）
- tui/monitor_panel.py（监控面板）

测试文件（列出每个测试对 core.models 和 core.dsl_v2_ast 的 import）：
- tests/test_dag.py
- tests/test_scheduler.py
- tests/test_dsl_parser.py
- tests/test_dsl_parser_v2.py
- tests/test_core.py
- tests/test_condition.py
- tests/test_storage.py
- tests/test_llm_agent.py
- tests/test_monitor.py
- tests/test_db.py
- tests/test_agent_component.py
- tests/test_component_registry.py

输出：
1. 每个文件的变更类型（删除/重写/import更新）
2. 测试文件的 import 变更表
3. cli.py 中需要重写的函数清单

将报告写入 .claude/plans/analysis-tui-tests.md`,
    { label: 'analyze-tui', phase: 'Analyze', effort: 'high' }
  ),
])

log('Phase 1 完成。')

// ============================================================
// Phase 2: 并行迁移（10 agents，worktree 隔离）
// ============================================================
phase('Migrate')
log('Phase 2: 10 agents 并行迁移...')

const migrateResults = await parallel([
  // Agent 1: 创建 core/execution.py
  () => agent(
    `创建 core/execution.py — 从旧 core/models.py 提取运行时类型。

读取 core/models.py，提取以下类到新文件 core/execution.py：
- ExecutionStatus (str, Enum) — PENDING/RUNNING/COMPLETED/FAILED/SKIPPED
- AgentExecutionRecord (Pydantic BaseModel) — agent_name, status, started_at, completed_at, duration_ms, input_data, output_data, error
- ExecutionRecord (Pydantic BaseModel) — workflow_name, status, started_at, completed_at, duration_ms, agent_records, error + start()/complete()/fail() 方法

使用 Pydantic BaseModel，保持与旧代码完全兼容。

同时更新以下文件的 import（ExecutionRecord/AgentExecutionRecord/ExecutionStatus 从 core.models 改为 core.execution）：
- core/db.py
- core/monitor.py
- tui/display.py
- tui/monitor_panel.py

git add -A && git commit -m "refactor: 创建 execution.py，提取运行时类型"`,
    { label: 'm-execution', phase: 'Migrate', isolation: 'worktree' }
  ),

  // Agent 2: 重写 core/models.py
  () => agent(
    `重写 core/models.py — 用 dsl_v2_ast.py 的内容替换旧文件。

步骤：
1. 读取 core/dsl_v2_ast.py 的完整内容
2. 将所有 @dataclass 改为 Pydantic BaseModel
3. field(default_factory=...) 改为 Field(default_factory=...)
4. 写入 core/models.py（完全替换旧内容）
5. 删除 core/dsl_v2_ast.py
6. 更新 tui/dsl_parser_v2.py 的 import（from core.dsl_v2_ast → from core.models）

新的 core/models.py 应包含：
- Port(BaseModel)
- MCPConfig(BaseModel)
- PermissionConfig(BaseModel)
- ModelConfig(BaseModel)
- Component(BaseModel)
- AgentInstance(BaseModel)
- Connection(BaseModel)
- Workflow(BaseModel)
- ParseResult(BaseModel)

git add -A && git commit -m "refactor: dsl_v2_ast.py → models.py，v2 类型为唯一类型系统"`,
    { label: 'm-models', phase: 'Migrate', isolation: 'worktree' }
  ),

  // Agent 3: 重写 core/agent.py
  () => agent(
    `重写 core/agent.py — 删除 AgentConfig，Agent 接受 Component。

读取 core/agent.py 和 core/dsl_v2_ast.py（Component 定义）。

新 core/agent.py：
- 删除 AgentConfig 类
- Agent.__init__ 接受 Component（从 core.models 导入，如果还没迁移则从 core.dsl_v2_ast 导入）
- 从 Component.ports 推导 input_schema / output_schema
- 保留 validate_input/validate_output/execute 的模板方法逻辑
- 保留 to_dict()

\`\`\`python
from abc import ABC, abstractmethod
from typing import Any, Dict
import jsonschema

# 优先从 core.models 导入，如果不存在则从 core.dsl_v2_ast 导入
try:
    from core.models import Component
except ImportError:
    from core.dsl_v2_ast import Component

class Agent(ABC):
    def __init__(self, component: Component):
        self.component = component
        self.name = component.name
        self.on_fail = component.on_fail
        self.retry_count = component.retry_count

    def _ports_to_schema(self, direction: str) -> Dict[str, Any]:
        properties = {}
        for port in self.component.ports:
            if port.direction == direction:
                properties[port.name] = {"type": port.type}
        return {"type": "object", "properties": properties} if properties else {}

    @property
    def input_schema(self):
        return self._ports_to_schema("input")

    @property
    def output_schema(self):
        return self._ports_to_schema("output")

    def validate_input(self, data): ...
    def validate_output(self, data): ...
    async def execute(self, input_data): ...
    @abstractmethod
    async def run(self, input_data): ...
    def to_dict(self): ...
\`\`\`

git add -A && git commit -m "refactor: agent.py 删除 AgentConfig，Agent 接受 Component"`,
    { label: 'm-agent', phase: 'Migrate', isolation: 'worktree' }
  ),

  // Agent 4: 重写 core/llm_agent.py
  () => agent(
    `重写 core/llm_agent.py — LLMAgent 从 Component 构造。

读取 core/llm_agent.py 和 core/dsl_v2_ast.py。

关键变更：
- LLMAgent.__init__ 接受 Component 而非分散参数
- 从 component.model.default 获取模型名
- 从 component.system_prompt 获取系统提示词
- 从 component.model.temperature/max_tokens 获取参数
- 删除所有 AgentConfig 引用
- 更新 LLMAgentFactory.create() 接受 Component

保留 _resolve_model、_format_prompt、_parse_response 原有逻辑。

import 处理：
\`\`\`python
try:
    from core.models import Component
except ImportError:
    from core.dsl_v2_ast import Component
\`\`\`

git add -A && git commit -m "refactor: llm_agent.py 从 Component 构造 LLMAgent"`,
    { label: 'm-llm-agent', phase: 'Migrate', isolation: 'worktree' }
  ),

  // Agent 5: 重写 core/condition.py
  () => agent(
    `重写 core/condition.py — ConditionAgent 从 Component 构造。

读取 core/condition.py 和 core/dsl_v2_ast.py。

关键变更：
- ConditionAgent.__init__ 接受 Component + rules 列表
- SimpleConditionAgent.__init__ 接受 Component + field + mapping + default
- 删除旧 AgentConfig 引用
- 保留原有 run() 逻辑

import 处理：
\`\`\`python
try:
    from core.agent import Agent
    from core.models import Component
except ImportError:
    from core.dsl_v2_ast import Component
\`\`\`

git add -A && git commit -m "refactor: condition.py 从 Component 构造"`,
    { label: 'm-condition', phase: 'Migrate', isolation: 'worktree' }
  ),

  // Agent 6: 重写 core/dag.py
  () => agent(
    `重写 core/dag.py — 用 v2 类型替代旧类型。

读取 core/dag.py 和 core/dsl_v2_ast.py。

关键变更：
- import 从 core.models 改为：
  \`\`\`python
  try:
      from core.models import Workflow, Connection
  except ImportError:
      from core.dsl_v2_ast import Workflow, Connection
  \`\`\`
- 删除 Edge 和 InteractionType 引用
- DAG.__init__ 从 workflow.connections 构建邻接表（替代 workflow.edges）
- 节点从 workflow.agents（AgentInstance 列表）获取
- 新增 get_incoming_connections(node) 方法
- 新增 get_condition_connections(node) 方法
- 保留 topological_sort、get_parallel_groups、is_ready 等核心方法

\`\`\`python
for conn in workflow.connections:
    for target in conn.target_agents:
        self._adjacency[conn.source_agent].append(target)
        self._reverse_adjacency[target].append(conn.source_agent)
        self._connections[conn.source_agent].append(conn)
\`\`\`

git add -A && git commit -m "refactor: dag.py 迁移到 v2 Connection 类型"`,
    { label: 'm-dag', phase: 'Migrate', isolation: 'worktree' }
  ),

  // Agent 7: 重写 core/scheduler.py
  () => agent(
    `重写 core/scheduler.py — 用 v2 类型 + port-aware 输入。

读取 core/scheduler.py 和 core/dsl_v2_ast.py。

关键变更：
- import：
  \`\`\`python
  try:
      from core.models import Workflow, AgentInstance
  except ImportError:
      from core.dsl_v2_ast import Workflow, AgentInstance
  from core.execution import ExecutionRecord, AgentExecutionRecord, ExecutionStatus
  from core.agent import Agent
  from core.dag import DAG
  from core.context import WorkflowContext
  \`\`\`
- agents 类型改为 Dict[str, Agent]
- _prepare_input 支持 port 映射：
  \`\`\`python
  def _prepare_input(self, agent_name, context):
      incoming = self.dag.get_incoming_connections(agent_name)
      port_inputs = {}
      deps = {}
      for conn in incoming:
          source_output = context.get(conn.source_agent)
          deps[conn.source_agent] = source_output
          if conn.source_port and conn.target_ports:
              for tp in conn.target_ports:
                  if conn.source_port in source_output:
                      port_inputs[tp] = source_output[conn.source_port]
          else:
              if isinstance(source_output, dict):
                  port_inputs.update(source_output)
      result = port_inputs if port_inputs else {}
      result["_deps"] = deps
      return result
  \`\`\`
- agent.run() 改为 agent.execute()
- 删除 InteractionType 引用
- _should_execute 基于 Connection 判断

git add -A && git commit -m "refactor: scheduler.py 迁移到 v2 类型 + port-aware"`,
    { label: 'm-scheduler', phase: 'Migrate', isolation: 'worktree' }
  ),

  // Agent 8: 更新 core/ 辅助模块 imports
  () => agent(
    `更新 core/ 辅助模块的 import 语句。

以下文件只需要更新 import，不需要修改逻辑：

1. core/context.py — 无 core.models 依赖，检查是否有其他需要更新的
2. core/storage.py — from core.models import Workflow → 更新为新路径
3. core/component_registry.py — from core.dsl_v2_ast import Component, ParseResult → from core.models import
4. core/workflow_generator.py — 检查并更新 import
5. core/agent_component.py — 检查并更新 import

import 模式：
\`\`\`python
# 对于 v2 类型（Component, Workflow 等）
try:
    from core.models import Component, Workflow, ParseResult
except ImportError:
    from core.dsl_v2_ast import Component, Workflow, ParseResult

# 对于运行时类型
from core.execution import ExecutionRecord, ExecutionStatus
\`\`\`

git add -A && git commit -m "refactor: 更新 core/ 辅助模块 imports"`,
    { label: 'm-core-imports', phase: 'Migrate', isolation: 'worktree' }
  ),

  // Agent 9: 重写 tui/cli.py + templates.py + 删除 v1
  () => agent(
    `重写 tui/cli.py 的 agent 创建逻辑，重写 templates.py，删除 v1 解析器。

## 任务 1: tui/cli.py

读取 tui/cli.py，执行以下修改：

1. 更新 import：
\`\`\`python
# 删除
from core.models import Workflow
from tui.dsl_parser import parse_file

# 添加
try:
    from core.models import Workflow, Component, AgentInstance, Connection, ParseResult
except ImportError:
    from core.dsl_v2_ast import Workflow, Component, AgentInstance, Connection, ParseResult
from core.execution import ExecutionRecord, ExecutionStatus
from tui.dsl_parser_v2 import DSLv2Parser
\`\`\`

2. 添加共享 agent 创建函数：
\`\`\`python
def _create_agents_from_workflow(workflow, components_dict):
    from core.llm_agent import LLMAgent
    from core.condition import ConditionAgent
    import copy

    agents = {}
    for agent_inst in workflow.agents:
        if agent_inst.component:
            comp = components_dict.get(agent_inst.component)
            if not comp:
                raise ValueError(f"Component '{agent_inst.component}' not found")
            comp = copy.deepcopy(comp)
            for k, v in agent_inst.overrides.items():
                if k == "model" and isinstance(v, dict):
                    for mk, mv in v.items():
                        setattr(comp.model, mk, mv)
                elif hasattr(comp, k):
                    setattr(comp, k, v)
        else:
            comp = Component(name=agent_inst.name)

        agent = LLMAgent(component=comp)
        agents[agent_inst.name] = agent
    return agents

def _parse_workflow_file(workflow_file):
    parser = DSLv2Parser()
    with open(workflow_file, 'r', encoding='utf-8') as f:
        content = f.read()
    result = parser.parse(content)
    if result.errors:
        raise ValueError(f"Parse errors: {result.errors}")
    if not result.workflows:
        raise ValueError("No workflow found in file")
    components_dict = {c.name: c for c in result.components}
    return result.workflows[0], components_dict, result
\`\`\`

3. 更新 run 命令使用新函数

## 任务 2: tui/templates.py

将模板改为 v2 格式。读取当前文件，将 TEMPLATES 中的 dict 改为 Component + Workflow 结构。

## 任务 3: 删除 v1

删除 tui/dsl_parser.py

git add -A && git commit -m "refactor: CLI + 模板迁移到 v2，删除 v1 解析器"`,
    { label: 'm-cli', phase: 'Migrate', isolation: 'worktree' }
  ),

  // Agent 10: 更新所有测试文件
  () => agent(
    `更新所有测试文件的 import 和 fixtures 以使用 v2 类型。

需要更新的测试文件：
- tests/test_dag.py — 用 v2 Workflow/AgentInstance/Connection 重写 fixtures
- tests/test_scheduler.py — 用 v2 类型 + Component 构造 Agent
- tests/test_dsl_parser.py — 删除（v1 测试）
- tests/test_dsl_parser_v2.py — import 从 core.dsl_v2_ast 改为 core.models
- tests/test_core.py — 更新 Agent 构造方式
- tests/test_condition.py — 从 Component 构造
- tests/test_storage.py — 用 v2 Workflow
- tests/test_llm_agent.py — 从 Component 构造
- tests/test_monitor.py — import 更新
- tests/test_db.py — import 更新
- tests/test_agent_component.py — import 更新
- tests/test_component_registry.py — import 更新

import 模式：
\`\`\`python
try:
    from core.models import Component, Workflow, AgentInstance, Connection, Port, ModelConfig
except ImportError:
    from core.dsl_v2_ast import Component, Workflow, AgentInstance, Connection, Port, ModelConfig
from core.execution import ExecutionRecord, AgentExecutionRecord, ExecutionStatus
\`\`\`

对于需要 Agent 实例的测试，使用：
\`\`\`python
component = Component(name="test", model=ModelConfig(default="gpt-4"))
# 或 mock Agent
\`\`\`

git add -A && git commit -m "refactor: 更新测试文件以使用 v2 类型"`,
    { label: 'm-tests', phase: 'Migrate', isolation: 'worktree' }
  ),
])

log(`Phase 2 完成。${migrateResults.filter(Boolean).length}/10 agents 成功。`)

// ============================================================
// Phase 3: 集成 + 设计（2 agents 并行）
// ============================================================
phase('Integrate')
log('Phase 3: DAG 集成 + REPL 智能编排设计...')

const integrateResults = await parallel([
  () => agent(
    `你是集成工程师。迁移已完成，现在验证 DAG 引擎端到端工作。

## 验证步骤

### 1. 类型系统验证
\`\`\`bash
cd E:/opencode-desktop/GrassFlow
.venv/Scripts/python -c "
from core.models import Component, Workflow, Connection, AgentInstance, Port, ModelConfig, ParseResult
from core.execution import ExecutionRecord, ExecutionStatus
print('Type system OK')
"
\`\`\`

### 2. DAG 引擎验证
\`\`\`python
from core.models import Workflow, AgentInstance, Connection
from core.dag import DAG

wf = Workflow(
    name='test',
    agents=[
        AgentInstance(name='A', component='comp_a'),
        AgentInstance(name='B', component='comp_b'),
        AgentInstance(name='C', component='comp_c'),
    ],
    connections=[
        Connection(source_agent='A', target_agents=['B']),
        Connection(source_agent='B', target_agents=['C']),
    ]
)
dag = DAG(wf)
print('Topo sort:', dag.topological_sort())
print('Groups:', dag.get_parallel_groups())
\`\`\`

### 3. 修复发现的问题
如果有导入错误、类型不匹配、缺少文件等问题，直接修复。

### 4. 运行测试
\`\`\`bash
.venv/Scripts/python -m pytest tests/test_dag.py tests/test_scheduler.py -q
\`\`\`

git add -A && git commit -m "fix: 修复迁移后的集成问题"`,
    { label: 'integrate-verify', phase: 'Integrate', effort: 'high' }
  ),

  () => agent(
    `你是系统架构师。设计 REPL 智能编排系统。

## 背景
GrassFlow 的 REPL 是 LLM 聊天界面。需要让 AI 能主动识别多步骤任务，自动生成 DSL 并执行工作流。

## 读取代码
读取 tui/repl.py、tui/agent_loop.py、tui/slash_commands.py、tui/tool_executor.py 了解当前架构。

## 设计输出

写入 .claude/plans/repl-orchestration-design.md，包含：

### 1. WorkflowExecuteTool 设计
- 工具定义（name, description, parameters schema）
- execute 方法的实现逻辑
- 与 Scheduler 的集成方式

### 2. 系统提示词注入
- 教导 AI 何时使用工作流
- DSL 语法速查
- 示例编排

### 3. /run 命令设计
- /run <file.gf> — 执行文件
- /run <dsl> — 执行内联 DSL
- /run — 显示运行中的工作流
- /run stop — 取消

### 4. 状态栏集成
- 显示运行中的工作流名称和进度

### 5. 实现文件清单
列出需要修改/创建的文件和具体变更`,
    { label: 'design-repl', phase: 'Integrate', effort: 'high' }
  ),
])

log('Phase 3 完成。')
log('工作流全部完成！')

return {
  phase1: `${analysisResults.filter(Boolean).length}/3 分析完成`,
  phase2: `${migrateResults.filter(Boolean).length}/10 迁移完成`,
  phase3: `${integrateResults.filter(Boolean).length}/3 集成完成`,
}
