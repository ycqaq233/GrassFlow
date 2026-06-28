# REPL 智能编排系统设计

## 概述

让 GrassFlow REPL 中的 AI 能够主动识别多步骤任务，自动生成 DSL 并执行工作流。用户只需描述复杂任务，AI 自动拆解为多个 Agent、声明依赖关系、调度执行。

## 架构总览

```
用户: "帮我分析 A 项目和 B 项目的代码质量，然后生成对比报告"

    ↓ REPL AgentLoop LLM 调用

LLM 判断 → 多步骤任务 → 调用 workflow_execute 工具
    ↓
WorkflowExecuteTool.execute(dsl="...")
    ↓
DSLParser.parse() → Workflow 对象
    ↓
WorkflowRunner.run()
    ├── Agent "analyze_a" → LLM 子调用（分析 A 项目）
    ├── Agent "analyze_b" → LLM 子调用（分析 B 项目）  ← 并行
    └── Agent "report"   → LLM 子调用（等待 a,b 完成后生成报告）
    ↓
最终结果返回给父 LLM → 格式化展示给用户
```

核心原则：**工作流中的每个 Agent 都是一次 LLM 调用**，复用现有 AgentLoop 的 LLM 基础设施。

---

## 1. WorkflowExecuteTool 设计

### 1.1 工具定义

```python
# 文件: tui/workflow_tool.py

WORKFLOW_EXECUTE_TOOL = ToolDef(
    id="workflow_execute",
    description=(
        "Execute a multi-agent workflow. Use this when a task requires "
        "multiple steps, parallel processing, or conditional branching. "
        "The workflow is defined in GrassFlow DSL syntax."
    ),
    source=ToolSource.BUILTIN,
    permission=ToolPermission.ALLOW,  # 工作流执行不需要额外审批
    parameters={
        "type": "object",
        "properties": {
            "dsl": {
                "type": "string",
                "description": "GrassFlow DSL workflow definition",
            },
            "file": {
                "type": "string",
                "description": "Path to a .gf workflow file (alternative to dsl)",
            },
            "input": {
                "type": "object",
                "description": "Input data for the workflow (available to all agents as {input})",
                "additionalProperties": True,
            },
        },
        "required": [],  # dsl 或 file 至少提供一个
    },
)
```

### 1.2 WorkflowRunner — 工作流执行引擎

`WorkflowRunner` 是连接 DSL/Scheduler 与 LLM 的桥梁。它接收 `Workflow` 对象，为每个 Agent 创建 LLM 子调用，通过 `WorkflowContext` 传递数据。

```python
# 文件: tui/workflow_runner.py

class LLMAdapter:
    """将 AgentLoop 的 LLM 能力适配为 Scheduler 可用的 Agent 接口"""

    def __init__(self, agent_loop: AgentLoop):
        self._agent_loop = agent_loop

    async def call(self, prompt: str, model: str = "",
                   context_data: dict = None) -> dict:
        """
        执行一次 LLM 调用，模拟一个 Agent 的 run() 方法。

        Args:
            prompt: Agent 的 prompt 模板（支持 {input} 和 {deps.xxx} 占位符）
            model: 模型名（空则使用当前模型）
            context_data: 上下文数据（依赖 Agent 的输出）

        Returns:
            {"text": str, "raw": str} — 解析后的结构化输出
        """
        # 1. 替换 prompt 中的占位符
        filled_prompt = self._fill_template(prompt, context_data)

        # 2. 调用 LLM（复用 AgentLoop 的 client）
        messages = [{"role": "user", "content": filled_prompt}]
        response = await self._agent_loop._client.chat(
            messages=messages,
            tools=[],  # 子 Agent 不使用工具
        )

        # 3. 返回结果
        return {"text": response.content, "raw": response.content}

    def _fill_template(self, prompt: str, context_data: dict) -> str:
        """替换 prompt 中的 {input}, {deps.agent_name} 占位符"""
        if not context_data:
            return prompt
        # {input} → context_data.get("_input", {})
        # {deps.analyze_a} → context_data.get("_deps", {}).get("analyze_a", {})
        ...


class WorkflowRunner:
    """工作流执行器 — 桥接 DSL/Scheduler 与 LLM"""

    def __init__(self, llm_adapter: LLMAdapter):
        self._adapter = llm_adapter
        self._abort_signal = asyncio.Event()
        self._current_execution: Optional[ExecutionRecord] = None

    async def run(
        self,
        workflow: Workflow,
        input_data: dict = None,
        on_progress: Optional[Callable] = None,
    ) -> dict:
        """
        执行工作流。

        Args:
            workflow: 解析后的 Workflow 对象
            input_data: 工作流输入数据
            on_progress: 进度回调 (agent_name, status, data)

        Returns:
            {"results": {agent_name: output}, "execution_record": ExecutionRecord}
        """
        # 1. 创建 agents 字典（每个 Agent 是一个 LLMCallableAgent）
        agents = {}
        for agent_config in workflow.agents:
            if agent_config.type == AgentType.LLM:
                agents[agent_config.name] = LLMCallableAgent(
                    config=agent_config,
                    adapter=self._adapter,
                )
            elif agent_config.type == AgentType.CONDITION:
                agents[agent_config.name] = ConditionAgent(config=agent_config)

        # 2. 注入 input_data 到 context
        context = WorkflowContext()
        if input_data:
            context.set("_input", input_data)

        # 3. 创建 Scheduler 并执行
        scheduler = Scheduler(workflow, agents)

        # 4. 注入进度回调
        if on_progress:
            scheduler.on_agent_start = lambda name: on_progress(name, "running", {})
            scheduler.on_agent_end = lambda name, result: on_progress(name, "completed", result)

        # 5. 执行
        execution_record = await scheduler.run(context)

        return {
            "results": context.to_dict(),
            "execution_record": execution_record,
        }

    def abort(self):
        """中止工作流执行"""
        self._abort_signal.set()


class LLMCallableAgent:
    """将 LLM 调用包装为 Agent 接口，供 Scheduler 调用"""

    def __init__(self, config: AgentConfig, adapter: LLMAdapter):
        self.config = config
        self._adapter = adapter

    async def run(self, input_data: dict) -> dict:
        """执行 Agent（一次 LLM 调用）"""
        return await self._adapter.call(
            prompt=self.config.prompt,
            model=self.config.model,
            context_data=input_data,
        )
```

### 1.3 WorkflowExecuteTool.execute 实现

```python
class WorkflowExecuteTool:
    """workflow_execute 工具实现"""

    def __init__(self, agent_loop: AgentLoop, repl: Any = None):
        self._agent_loop = agent_loop
        self._repl = repl
        self._runner: Optional[WorkflowRunner] = None

    async def execute(self, args: dict) -> ToolResult:
        dsl_text = args.get("dsl", "")
        file_path = args.get("file", "")
        input_data = args.get("input", {})

        # 1. 获取 DSL 文本
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    dsl_text = f.read()
            except FileNotFoundError:
                return ToolResult.error(f"File not found: {file_path}")
        elif not dsl_text:
            return ToolResult.error("Must provide either 'dsl' or 'file' parameter")

        # 2. 解析 DSL
        try:
            workflow = parse_dsl(dsl_text)
        except DSLError as e:
            return ToolResult.error(f"DSL parse error: {e}")

        # 3. 创建 Runner 并执行
        adapter = LLMAdapter(self._agent_loop)
        self._runner = WorkflowRunner(adapter)

        # 4. 更新 REPL 状态栏（如果可用）
        if self._repl:
            self._repl._active_workflow = workflow.name

        try:
            result = await self._runner.run(
                workflow=workflow,
                input_data=input_data,
                on_progress=self._make_progress_callback(),
            )

            # 5. 格式化结果
            summary = self._format_result(result)
            return ToolResult.success(summary)

        except Exception as e:
            return ToolResult.error(f"Workflow execution failed: {e}")
        finally:
            if self._repl:
                self._repl._active_workflow = None
            self._runner = None

    def _make_progress_callback(self) -> Callable:
        """创建进度回调（通过 REPL 输出到终端）"""
        repl = self._repl
        if not repl:
            return lambda *a: None

        def on_progress(agent_name, status, data):
            if status == "running":
                repl._cprint_raw(f"\033[36m  ⚡ [{agent_name}] started\033[0m\n")
            elif status == "completed":
                repl._cprint_raw(f"\033[32m  ✅ [{agent_name}] completed\033[0m\n")
        return on_progress

    def _format_result(self, result: dict) -> str:
        """格式化工作流执行结果"""
        lines = [f"Workflow completed: {result['execution_record'].workflow_name}"]
        records = result["execution_record"].agent_records
        for name, record in records.items():
            status = record.status.value
            dur = f"{record.duration_ms}ms" if record.duration_ms else "N/A"
            lines.append(f"  [{name}] {status} ({dur})")
        # 最终叶子节点的输出
        results = result.get("results", {})
        if results:
            lines.append("\nFinal outputs:")
            for name, output in results.items():
                if name.startswith("_"):
                    continue
                text = output.get("text", str(output))
                if len(text) > 500:
                    text = text[:497] + "..."
                lines.append(f"  [{name}]: {text}")
        return "\n".join(lines)
```

### 1.4 工具注册

在 `AgentIntegration.init_agent_loop()` 中注册 WorkflowExecuteTool：

```python
# tui/agent_integration.py 的 init_agent_loop() 方法中，
# 在 register_builtin_tools() 之后添加:

from tui.workflow_tool import WorkflowExecuteTool, WORKFLOW_EXECUTE_TOOL

wf_tool_impl = WorkflowExecuteTool(agent_loop=self._agent_loop, repl=None)
tool_registry.register(WORKFLOW_EXECUTE_TOOL)
# 注册 invoke handler
tool_registry.register_invoke("workflow_execute", wf_tool_impl.execute)
```

同时在 REPL 初始化时注入 `repl` 引用：

```python
# tui/repl.py 的 run() 方法中，agent loop 初始化后:
wf_tool = tool_registry.get_tool_impl("workflow_execute")
if wf_tool:
    wf_tool._repl = self
```

---

## 2. 系统提示词注入

在 `GrassFlowREPL._get_system_prompt()` 方法中追加工作流编排指引。

### 2.1 注入位置

在 `_get_system_prompt()` 方法末尾、`"Be concise and helpful..."` 之前，插入以下内容：

### 2.2 注入内容

```python
WORKFLOW_ORCHESTRATION_PROMPT = """
## Workflow Orchestration

You have the ability to create and execute multi-agent workflows using the `workflow_execute` tool.
Use this when a task involves multiple independent or dependent steps that benefit from parallel execution or structured pipelines.

### When to Use Workflows

- Task requires analysis of multiple independent items (parallel processing)
- Task has clear sequential stages (pipeline)
- Task needs conditional branching based on intermediate results
- Task would benefit from structured decomposition into sub-tasks

### When NOT to Use Workflows

- Simple single-step tasks (just do them directly)
- Tasks that are purely conversational
- Tasks where you can accomplish everything in one tool call

### DSL Syntax Quick Reference

```
# Sequential: A runs first, then B, then C
A -> B -> C

# Parallel: A, B, C run simultaneously, D waits for all
(A, B, C) -> D

# Immediate: B starts immediately, doesn't wait for A
A | B

# Condition: route decides which path to take
route -> [urgent] human, [normal] bot

# Combined
(A | B) -> route -> [urgent] human, [normal] bot
```

### Workflow Definition Format

When calling `workflow_execute`, provide a complete workflow definition:

```
workflow <name> {
  agent <name> {
    model: "<model_name>"           # optional, uses current model if omitted
    prompt: "<prompt_template>"     # required, supports {input} and {deps.xxx}
    on_fail: "stop|skip|retry"      # optional, default "stop"
    retry_count: 3                  # optional
  }
  # ... more agents ...

  # Execution flow
  agent_a -> agent_b -> agent_c
}
```

### Prompt Templates

- `{input}` — The workflow's input data (passed by the caller)
- `{deps.agent_name}` — Output from a dependency agent (as JSON string)
- `{deps.agent_name.field}` — Specific field from a dependency's output

### Example: Parallel Code Review

```
workflow code_review {
  agent security {
    prompt: "Analyze this code for security vulnerabilities: {input.code}"
  }
  agent performance {
    prompt: "Analyze this code for performance issues: {input.code}"
  }
  agent summary {
    prompt: "Summarize these reviews into a report:\\nSecurity: {deps.security}\\nPerformance: {deps.performance}"
  }

  (security, performance) -> summary
}
```

Call: workflow_execute(dsl="...", input={"code": "<code to review>"})
"""
```

### 2.3 注入代码

```python
# 在 _get_system_prompt() 中:

# 5. Inject Workflow Orchestration prompt
base += WORKFLOW_ORCHESTRATION_PROMPT + "\n"
```

---

## 3. /run 命令设计

### 3.1 命令变体

| 用法 | 描述 |
|------|------|
| `/run <file.gf>` | 执行 .gf 工作流文件 |
| `/run <inline_dsl>` | 执行内联 DSL（单行简短语法） |
| `/run` | 显示当前运行中的工作流状态 |
| `/run stop` | 取消当前运行中的工作流 |

### 3.2 实现

```python
# tui/slash_commands.py

def _cmd_run(repl, args: List[str]) -> None:
    """执行工作流"""
    # /run — 显示状态
    if not args:
        if repl._active_workflow:
            repl.add_output(
                f"  Running workflow: {repl._active_workflow}\n"
                f"  Use /run stop to cancel.",
                role="system",
            )
        else:
            repl.add_output(
                "  No workflow running.\n"
                "  Usage:\n"
                "    /run <file.gf>       Execute workflow file\n"
                "    /run <dsl>           Execute inline DSL\n"
                "    /run stop            Cancel running workflow",
                role="system",
            )
        return

    # /run stop — 取消
    if args[0].lower() == "stop":
        if repl._active_workflow_runner:
            repl._active_workflow_runner.abort()
            repl.add_output("  Workflow abort signal sent.", role="system")
        else:
            repl.add_output("  No workflow to cancel.", role="system")
        return

    target = " ".join(args)

    # 判断是文件还是内联 DSL
    if target.endswith(".gf") or os.path.isfile(target):
        # 文件模式
        _run_workflow_file(repl, target)
    else:
        # 内联 DSL 模式
        _run_inline_dsl(repl, target)


def _run_workflow_file(repl, file_path: str) -> None:
    """执行工作流文件"""
    if not os.path.isfile(file_path):
        # 尝试在 workflows 目录查找
        workflows_dir = os.path.join(os.path.expanduser("~"), ".Grass", "workflows")
        alt_path = os.path.join(workflows_dir, file_path)
        if os.path.isfile(alt_path):
            file_path = alt_path
        elif not file_path.endswith(".gf"):
            alt_path = file_path + ".gf"
            if os.path.isfile(alt_path):
                file_path = alt_path
            else:
                repl.add_output(f"  File not found: {file_path}", role="error")
                return
        else:
            repl.add_output(f"  File not found: {file_path}", role="error")
            return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            dsl_text = f.read()
    except Exception as e:
        repl.add_output(f"  Error reading file: {e}", role="error")
        return

    repl.add_output(f"  Executing workflow: {file_path}", role="system")
    _execute_workflow_dsl(repl, dsl_text, {})


def _run_inline_dsl(repl, dsl_text: str) -> None:
    """执行内联 DSL"""
    # 验证 DSL 语法
    try:
        from tui.dsl_parser import DSLParser
        parser = DSLParser()
        workflow = parser.parse(dsl_text)
        repl.add_output(f"  Executing workflow: {workflow.name}", role="system")
    except Exception as e:
        repl.add_output(f"  DSL parse error: {e}", role="error")
        return

    _execute_workflow_dsl(repl, dsl_text, {})


def _execute_workflow_dsl(repl, dsl_text: str, input_data: dict) -> None:
    """执行工作流 DSL（异步）"""
    import asyncio

    async def _run():
        try:
            from tui.workflow_runner import WorkflowRunner, LLMAdapter
            from tui.dsl_parser import parse_dsl

            workflow = parse_dsl(dsl_text)
            adapter = LLMAdapter(repl._agent._agent_loop)
            runner = WorkflowRunner(adapter)
            repl._active_workflow_runner = runner
            repl._active_workflow = workflow.name

            result = await runner.run(workflow, input_data)

            # 输出结果
            summary = runner._format_result(result)
            repl.add_output(summary, role="system")
        except Exception as e:
            repl.add_output(f"  Workflow error: {e}", role="error")
        finally:
            repl._active_workflow = None
            repl._active_workflow_runner = None

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        asyncio.run(_run())
```

### 3.3 命令定义更新

```python
# 替换现有的 _cmd_run CommandDef
CommandDef(
    name="run",
    description="Execute workflow (file, inline DSL, or show status)",
    category="Workflow",
    aliases=(),
    args_hint="[<file.gf> | <dsl> | stop]",
    handler_name="_cmd_run",
),
```

---

## 4. 状态栏集成

### 4.1 新增 REPL 属性

在 `GrassFlowREPL.__init__()` 中添加：

```python
# 工作流状态
self._active_workflow: Optional[str] = None         # 正在执行的工作流名称
self._active_workflow_runner: Optional[Any] = None   # WorkflowRunner 实例（用于 abort）
self._workflow_progress: Dict[str, str] = {}         # agent_name → status
```

### 4.2 状态栏渲染

在 `make_status_text_from_repl()` 的 `_get_status_text()` 中，在 `agent_running` 检查之前添加：

```python
# 工作流状态
active_wf = getattr(repl, '_active_workflow', None)
if active_wf:
    wf_progress = getattr(repl, '_workflow_progress', {})
    completed = sum(1 for s in wf_progress.values() if s == "completed")
    total = len(wf_progress)
    progress_str = f"{completed}/{total}" if total > 0 else ""
    result.append(("class:status-bar-bright", f"| 🔄 {active_wf} ({progress_str}) "))
```

### 4.3 进度更新机制

WorkflowRunner 在每个 Agent 开始/结束时更新 REPL 的 `_workflow_progress`：

```python
# WorkflowRunner.run() 中:
def on_progress(agent_name, status, data):
    if self._repl:
        self._repl._workflow_progress[agent_name] = status
        if self._repl.app:
            self._repl.app.invalidate()  # 触发状态栏刷新
```

---

## 5. Scheduler 适配

当前 `Scheduler` 假设 `agents` 字典中的值有 `run()` 方法。`LLMCallableAgent` 已满足此接口。但需要微调 Scheduler 以支持进度回调：

### 5.1 Scheduler 修改

```python
# core/scheduler.py — 添加回调支持

class Scheduler:
    def __init__(self, workflow: Workflow, agents: Dict[str, Any]):
        self.workflow = workflow
        self.agents = agents
        self.dag = DAG(workflow)
        self.execution_record = ExecutionRecord(workflow_name=workflow.name)
        # 新增：进度回调
        self.on_agent_start: Optional[Callable[[str], None]] = None
        self.on_agent_end: Optional[Callable[[str, dict], None]] = None

    async def _execute_agent(self, agent_name: str, context: WorkflowContext) -> Dict[str, Any]:
        agent = self.agents.get(agent_name)
        if not agent:
            raise SchedulerError(f"Agent '{agent_name}' not found")

        # 触发开始回调
        if self.on_agent_start:
            self.on_agent_start(agent_name)

        # ... existing execution logic ...

        # 触发结束回调
        if self.on_agent_end:
            self.on_agent_end(agent_name, output)

        return output
```

### 5.2 Agent 类型扩展

当前 `AgentConfig.type` 已支持 `CONDITION` 类型，但 Scheduler 没有对应的处理。需要在 `WorkflowRunner.run()` 中为 Condition 类型创建特殊 Agent：

```python
class ConditionCallableAgent:
    """条件分支 Agent — 根据输入数据决定路由"""

    def __init__(self, config: AgentConfig):
        self.config = config

    async def run(self, input_data: dict) -> dict:
        # 从 input_data 中提取路由值
        deps = input_data.get("_deps", {})
        # 取第一个依赖的输出
        if deps:
            first_dep = next(iter(deps.values()))
            route = first_dep.get("route", first_dep.get("text", "default"))
        else:
            route = "default"
        return {"route": route}
```

---

## 6. 实现文件清单

### 6.1 新建文件

| 文件 | 职责 |
|------|------|
| `tui/workflow_tool.py` | WorkflowExecuteTool 实现 + 工具定义 |
| `tui/workflow_runner.py` | WorkflowRunner + LLMAdapter + LLMCallableAgent |

### 6.2 修改文件

| 文件 | 变更 |
|------|------|
| `tui/repl.py` | (1) `_get_system_prompt()` 追加编排指引 (2) `__init__()` 添加 `_active_workflow` 等属性 |
| `tui/slash_commands.py` | (1) 重写 `_cmd_run()` 支持文件/内联/状态/取消 (2) 添加 `_run_workflow_file`、`_run_inline_dsl`、`_execute_workflow_dsl` 辅助函数 |
| `tui/agent_integration.py` | `init_agent_loop()` 中注册 WorkflowExecuteTool |
| `core/scheduler.py` | (1) 添加 `on_agent_start`/`on_agent_end` 回调属性 (2) `_execute_agent()` 中触发回调 |
| `tui/layout.py` | `make_status_text_from_repl()` 中添加工作流进度显示 |

### 6.3 可选修改

| 文件 | 变更 |
|------|------|
| `tui/layout.py` | 补全器添加 `/run` 参数补全（.gf 文件列表） |
| `tui/slash_commands.py` | `SlashCommandCompleter._ARG_COMPLETIONS` 添加 `"run": ["stop"]` |

---

## 7. 数据流图

```
用户输入: "帮我并行分析 a.py 和 b.py 的代码质量"

REPL._handle_agent_message()
  → AgentLoop.process_streaming()
    → LLM 推理 → 决定调用 workflow_execute tool
      → ToolExecutor.execute(workflow_execute, {dsl: "workflow ...", input: {...}})
        → WorkflowExecuteTool.execute()
          → DSLParser.parse(dsl) → Workflow
          → WorkflowRunner.run(workflow)
            → Scheduler.run(context)
              → 并行组 [analyze_a, analyze_b]
                → LLMAdapter.call(prompt_a) → LLM 子调用
                → LLMAdapter.call(prompt_b) → LLM 子调用
              → 顺序组 [report]
                → LLMAdapter.call(prompt_report, deps={a, b}) → LLM 子调用
            → ExecutionRecord 返回
          → 格式化结果 → ToolResult
        → 返回给 AgentLoop
      → LLM 看到结果 → 生成最终回复
    → 流式输出到终端
```

## 8. 关键设计决策

### Q: 为什么不用 AgentLoop 的嵌套调用？

A: AgentLoop 是面向 REPL 的完整对话循环，包含 UI 事件、流式输出等。工作流中的子 Agent 只需要纯粹的 LLM 调用能力，不需要对话管理。LLMAdapter 直接使用 `AgentLoop._client`（ProtocolLLMClient）进行精简调用。

### Q: 工作流中的 Agent 如何访问工具？

A: MVP 阶段，工作流中的子 Agent 不使用工具（tools=[]）。后续可以通过 AgentConfig 的 `tools` 字段指定可用工具列表，将 ToolRegistry 的子集传递给子 Agent。

### Q: 如何处理长时间运行的工作流？

A: WorkflowRunner 在独立的 asyncio Task 中运行，不阻塞 REPL。用户可以通过 `/run stop` 发送 abort 信号。状态栏实时显示进度。

### Q: 工作流结果如何传递回父 LLM？

A: WorkflowExecuteTool 返回 ToolResult，其 output 字段包含格式化的执行摘要。父 LLM 可以基于此生成最终用户回复。
