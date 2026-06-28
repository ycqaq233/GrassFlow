export const meta = {
  name: 'scan-and-fix-bugs',
  description: '扫描并修复 v2 迁移后的残留 bug',
  phases: [
    { title: 'Scan', detail: '6 agents 并行扫描 core/tui/tests' },
    { title: 'Fix', detail: '6 agents 并行修复发现的 bug' },
  ],
}

// ============================================================
// Phase 1: 并行扫描（6 agents）
// ============================================================
phase('Scan')
log('Phase 1: 6 agents 并行扫描...')

const scanResults = await parallel([
  // Agent 1: 扫描 core/ 模块的 import 错误
  () => agent(
    `扫描 core/ 目录下所有 Python 文件，找出所有 import 错误。

重点关注：
1. 引用不存在的类型（如 WorkflowV1, Edge, InteractionType, AgentConfig from core.models）
2. 引用已删除的模块（如 core.dsl_v2_ast）
3. import 路径错误
4. 循环导入

扫描文件：
- core/__init__.py
- core/models.py
- core/agent.py
- core/llm_agent.py
- core/condition.py
- core/dag.py
- core/scheduler.py
- core/context.py
- core/storage.py
- core/monitor.py
- core/db.py
- core/component_registry.py
- core/agent_component.py
- core/workflow_generator.py
- core/execution.py

对每个文件，运行 python -c "import <module>" 验证是否可导入。

输出格式：
\`\`\`
FILE: core/xxx.py
ISSUE: <描述>
LINE: <行号>
FIX: <建议修复>
\`\`\`

将结果写入 .claude/plans/bugs-core-imports.md`,
    { label: 'scan-core-imports', phase: 'Scan', effort: 'high' }
  ),

  // Agent 2: 扫描 core/ 模块的类型不匹配
  () => agent(
    `扫描 core/ 目录下所有 Python 文件，找出类型不匹配的 bug。

重点检查：
1. 函数签名是否使用了旧类型（AgentConfig, Edge, InteractionType）
2. 变量类型注解是否引用旧类型
3. 方法调用是否使用了旧 API（如 workflow.edges, workflow.get_agent()）
4. Pydantic model 字段是否兼容 v2 类型

扫描文件：
- core/dag.py
- core/scheduler.py
- core/context.py
- core/storage.py
- core/monitor.py
- core/agent_component.py
- core/workflow_generator.py

对每个文件，grep 搜索：
- AgentConfig
- InteractionType
- Edge (作为类型)
- workflow.edges
- workflow.get_agent
- WorkflowV1

输出格式：
\`\`\`
FILE: core/xxx.py
ISSUE: <描述>
LINE: <行号>
CURRENT: <当前代码>
FIX: <修复后的代码>
\`\`\`

将结果写入 .claude/plans/bugs-core-types.md`,
    { label: 'scan-core-types', phase: 'Scan', effort: 'high' }
  ),

  // Agent 3: 扫描 tui/ 模块
  () => agent(
    `扫描 tui/ 目录下所有 Python 文件，找出 import 和类型错误。

重点检查：
1. 引用不存在的类型
2. 引用已删除的模块（core.dsl_v2_ast, 旧 core.models 类型）
3. 函数调用参数不匹配
4. cli.py 中的 agent 创建逻辑是否正确

扫描文件：
- tui/cli.py
- tui/dsl_parser.py
- tui/dsl_parser_v2.py
- tui/templates.py
- tui/display.py
- tui/monitor_panel.py
- tui/editor.py
- tui/repl.py
- tui/agent_loop.py
- tui/agent_integration.py

对每个文件，运行 python -c "from tui.xxx import *" 验证。

输出格式：
\`\`\`
FILE: tui/xxx.py
ISSUE: <描述>
LINE: <行号>
FIX: <建议修复>
\`\`\`

将结果写入 .claude/plans/bugs-tui.md`,
    { label: 'scan-tui', phase: 'Scan', effort: 'high' }
  ),

  // Agent 4: 扫描测试文件
  () => agent(
    `扫描 tests/ 目录下所有测试文件，找出 import 和类型错误。

重点检查：
1. 引用不存在的类型（WorkflowV1, Edge, InteractionType, AgentConfig from core.models）
2. 引用已删除的模块（core.dsl_v2_ast）
3. 测试 fixtures 是否使用 v2 类型
4. Agent 构造方式是否正确

扫描所有 tests/test_*.py 文件。

对每个文件，运行 python -c "import tests.test_xxx" 验证是否可导入。

输出格式：
\`\`\`
FILE: tests/test_xxx.py
ISSUE: <描述>
LINE: <行号>
FIX: <建议修复>
\`\`\`

将结果写入 .claude/plans/bugs-tests.md`,
    { label: 'scan-tests', phase: 'Scan', effort: 'high' }
  ),

  // Agent 5: 运行现有测试
  () => agent(
    `运行项目的所有测试，找出失败的测试。

运行命令：
\`\`\`bash
cd E:/opencode-desktop/GrassFlow
.venv/Scripts/python -m pytest tests/ -q --tb=short 2>&1
\`\`\`

分析失败的测试：
1. 哪些测试失败了
2. 失败原因（import 错误、类型错误、断言失败等）
3. 需要怎么修复

输出格式：
\`\`\`
FAILED: tests/test_xxx.py::test_name
ERROR: <错误信息>
CAUSE: <原因分析>
FIX: <建议修复>
\`\`\`

将结果写入 .claude/plans/bugs-test-results.md`,
    { label: 'scan-test-run', phase: 'Scan', effort: 'high' }
  ),

  // Agent 6: 端到端验证
  () => agent(
    `运行端到端验证，检查 CLI 命令是否正常工作。

运行以下命令并记录结果：

\`\`\`bash
cd E:/opencode-desktop/GrassFlow

# 1. 基础 import 验证
.venv/Scripts/python -c "from core.models import Component, Workflow, Connection; print('models OK')"
.venv/Scripts/python -c "from core.execution import ExecutionRecord, ExecutionStatus; print('execution OK')"
.venv/Scripts/python -c "from core.dag import DAG; print('dag OK')"
.venv/Scripts/python -c "from core.scheduler import Scheduler; print('scheduler OK')"
.venv/Scripts/python -c "from core.agent import Agent; print('agent OK')"
.venv/Scripts/python -c "from core.llm_agent import LLMAgent; print('llm_agent OK')"
.venv/Scripts/python -c "from core.condition import ConditionAgent; print('condition OK')"

# 2. CLI 验证
.venv/Scripts/python -m tui.cli validate examples/code_review_pipeline.gf
.venv/Scripts/python -m tui.cli templates
.venv/Scripts/python -m tui.cli list

# 3. DAG 端到端
.venv/Scripts/python -c "
from core.models import Workflow, AgentInstance, Connection
from core.dag import DAG
wf = Workflow(name='test', agents=[AgentInstance(name='A'), AgentInstance(name='B')], connections=[Connection(source_agent='A', target_agents=['B'])])
dag = DAG(wf)
print('DAG OK:', dag.topological_sort())
"
\`\`\`

记录所有失败的命令和错误信息。

将结果写入 .claude/plans/bugs-e2e.md`,
    { label: 'scan-e2e', phase: 'Scan', effort: 'high' }
  ),
])

log('Phase 1 完成。')

// ============================================================
// Phase 2: 并行修复（6 agents）
// ============================================================
phase('Fix')
log('Phase 2: 6 agents 并行修复...')

const fixResults = await parallel([
  // Agent 7: 修复 core/ import 错误
  () => agent(
    `修复 core/ 目录下所有 import 错误。

读取 .claude/plans/bugs-core-imports.md 和 .claude/plans/bugs-core-types.md 获取需要修复的问题。

修复规则：
1. 删除所有对 core.models 中旧类型的引用（AgentConfig, Edge, InteractionType, AgentType, WorkflowV1）
2. 删除所有对 core.dsl_v2_ast 的引用，改为 core.models
3. 运行时类型（ExecutionRecord 等）从 core.execution 导入
4. 如果某个文件需要旧类型但已被删除，重写该逻辑使用 v2 类型

需要特别注意的文件：
- core/__init__.py — 确保不导出已删除的类型
- core/agent_component.py — 可能有大量旧类型引用
- core/workflow_generator.py — 可能引用旧类型

修复后运行验证：
\`\`\`bash
.venv/Scripts/python -c "import core; print('core import OK')"
\`\`\`

git add -A && git commit -m "fix: 修复 core/ import 和类型错误"`,
    { label: 'fix-core', phase: 'Fix', isolation: 'worktree' }
  ),

  // Agent 8: 修复 core/dag.py 和 core/scheduler.py
  () => agent(
    `修复 core/dag.py 和 core/scheduler.py 的类型错误。

读取这两个文件，检查是否还有旧类型引用。

修复 core/dag.py：
- 确保 import from core.models import Workflow, Connection
- 确保不引用 Edge, InteractionType
- 确保从 workflow.agents 获取节点，从 workflow.connections 获取边
- 确保 get_incoming_connections 方法存在

修复 core/scheduler.py：
- 确保 import from core.models import Workflow, AgentInstance
- 确保 import from core.execution import ExecutionRecord, AgentExecutionRecord, ExecutionStatus
- 确保 agents 类型为 Dict[str, Agent]
- 确保 _prepare_input 使用 Connection
- 确保 agent.run() 改为 agent.execute()

修复后运行验证：
\`\`\`bash
.venv/Scripts/python -c "from core.dag import DAG; from core.scheduler import Scheduler; print('OK')"
\`\`\`

git add -A && git commit -m "fix: 修复 dag.py 和 scheduler.py 类型错误"`,
    { label: 'fix-dag-sched', phase: 'Fix', isolation: 'worktree' }
  ),

  // Agent 9: 修复 core/agent.py 和 core/llm_agent.py
  () => agent(
    `修复 core/agent.py 和 core/llm_agent.py。

读取这两个文件，确保：

core/agent.py：
- 不引用 AgentConfig
- Agent.__init__ 接受 Component
- 从 Component.ports 推导 schema
- import from core.models import Component

core/llm_agent.py：
- 不引用 AgentConfig
- LLMAgent.__init__ 接受 Component
- 从 component.model 获取模型配置
- 从 component.system_prompt 获取系统提示词
- 删除 _build_agent_config 函数（如果存在）
- 删除 create_from_config 方法（如果存在）
- import from core.models import Component, ModelConfig

修复后运行验证：
\`\`\`bash
.venv/Scripts/python -c "from core.agent import Agent; from core.llm_agent import LLMAgent; print('OK')"
\`\`\`

git add -A && git commit -m "fix: 修复 agent.py 和 llm_agent.py"`,
    { label: 'fix-agent', phase: 'Fix', isolation: 'worktree' }
  ),

  // Agent 10: 修复 tui/cli.py
  () => agent(
    `修复 tui/cli.py 的所有问题。

读取 .claude/plans/bugs-tui.md 和 .claude/plans/bugs-e2e.md 获取需要修复的问题。

重点检查和修复：
1. import 语句是否正确
2. agent 创建逻辑是否使用 parse_file_result 和 components_dict
3. 是否有旧类型引用
4. run 和 monitor_cmd 命令是否正常工作

修复后运行验证：
\`\`\`bash
.venv/Scripts/python -m tui.cli validate examples/code_review_pipeline.gf
\`\`\`

git add -A && git commit -m "fix: 修复 cli.py 残留问题"`,
    { label: 'fix-cli', phase: 'Fix', isolation: 'worktree' }
  ),

  // Agent 11: 修复测试文件
  () => agent(
    `修复所有测试文件的 import 和类型错误。

读取 .claude/plans/bugs-tests.md 和 .claude/plans/bugs-test-results.md 获取需要修复的问题。

修复规则：
1. 删除所有对 core.dsl_v2_ast 的引用，改为 core.models
2. 删除所有对旧类型（AgentConfig, Edge, InteractionType）的引用
3. 运行时类型从 core.execution 导入
4. Agent 构造使用 Component 而非 AgentConfig
5. Workflow 构造使用 v2 类型（AgentInstance, Connection）

修复后运行验证：
\`\`\`bash
.venv/Scripts/python -m pytest tests/test_dag.py tests/test_scheduler.py tests/test_core.py -q
\`\`\`

git add -A && git commit -m "fix: 修复测试文件 import 和类型错误"`,
    { label: 'fix-tests', phase: 'Fix', isolation: 'worktree' }
  ),

  // Agent 12: 修复其他模块
  () => agent(
    `修复 core/condition.py, core/storage.py, core/context.py, core/monitor.py 等辅助模块。

读取每个文件，检查：
1. import 是否正确
2. 是否引用旧类型
3. 函数签名是否兼容 v2 类型

特别注意：
- core/condition.py — ConditionAgent 应该从 Component 构造
- core/storage.py — 应该能序列化/反序列化 v2 Workflow
- core/monitor.py — 应该从 core.execution 导入运行时类型
- core/db.py — 同上

修复后运行验证：
\`\`\`bash
.venv/Scripts/python -c "from core.condition import ConditionAgent; from core.storage import workflow_storage; from core.monitor import monitor; print('OK')"
\`\`\`

git add -A && git commit -m "fix: 修复辅助模块 import 和类型错误"`,
    { label: 'fix-aux', phase: 'Fix', isolation: 'worktree' }
  ),
])

log('Phase 2 完成。')
log('工作流完成！')

return {
  scan: `${scanResults.filter(Boolean).length}/6 扫描完成`,
  fix: `${fixResults.filter(Boolean).length}/6 修复完成`,
}
