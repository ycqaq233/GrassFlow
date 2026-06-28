"""
GrassFlow 调度器

实现功能：
- asyncio 并行调度
- 顺序/并行执行
- 失败策略（stop/skip/retry）
- 条件分支
- 事件回调机制
- Stream 模式（逐项触发）

使用 v2 类型: Workflow, AgentInstance
"""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, Any, List, Optional
from datetime import datetime
from core.models import Workflow, AgentInstance
from core.execution import ExecutionRecord, AgentExecutionRecord, ExecutionStatus
from core.context import WorkflowContext
from core.dag import DAG, DAGError


class SchedulerEventType(str, Enum):
    """调度器事件类型"""
    WORKFLOW_START = "workflow_start"
    WORKFLOW_COMPLETE = "workflow_complete"
    WORKFLOW_FAILED = "workflow_failed"
    GROUP_START = "group_start"
    GROUP_COMPLETE = "group_complete"
    AGENT_START = "agent_start"
    AGENT_COMPLETE = "agent_complete"
    AGENT_FAIL = "agent_fail"
    AGENT_RETRY = "agent_retry"
    AGENT_SKIPPED = "agent_skipped"


@dataclass
class SchedulerEvent:
    """调度器事件"""
    event_type: SchedulerEventType
    agent_name: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    data: Optional[Any] = None


class SchedulerError(Exception):
    """调度器相关错误"""
    pass


class Scheduler:
    """工作流调度器"""

    def __init__(
        self,
        workflow: Workflow,
        agents: Dict[str, Any],
        workflow_input: Optional[Dict[str, Any]] = None,
        on_event: Optional[Callable[[SchedulerEvent], None]] = None,
    ):
        """
        初始化调度器

        Args:
            workflow: 工作流定义 (v2)
            agents: Agent 实例字典，key 为 Agent 名称，value 为 Agent 实例
            on_event: 事件回调函数，接收 SchedulerEvent 参数。为 None 时不发射事件（零开销）。
        """
        self.workflow = workflow
        self.agents = agents
        self.dag = DAG(workflow)
        self.execution_record = ExecutionRecord(workflow_name=workflow.name)
        self.workflow_input = workflow_input or {}
        self._on_event = on_event

    def _get_agent_instance(self, agent_name: str) -> Optional[AgentInstance]:
        """从 workflow 中获取 AgentInstance 定义"""
        for ai in self.workflow.agents:
            if ai.name == agent_name:
                return ai
        return None

    def _get_agent_mode(self, agent_name: str) -> str:
        """获取 Agent 的执行模式：优先 AgentInstance，其次 Agent._component，最后默认 batch"""
        agent_instance = self._get_agent_instance(agent_name)
        if agent_instance and agent_instance.mode != "batch":
            return agent_instance.mode
        agent = self.agents.get(agent_name)
        if agent and hasattr(agent, '_component') and hasattr(agent._component, 'mode'):
            return agent._component.mode
        return "batch"

    def _get_agent_context_strategy(self, agent_name: str) -> str:
        """获取 Agent 的上下文策略：优先 AgentInstance，其次 Agent._component，最后默认 shared"""
        agent_instance = self._get_agent_instance(agent_name)
        if agent_instance and agent_instance.context != "shared":
            return agent_instance.context
        agent = self.agents.get(agent_name)
        if agent and hasattr(agent, '_component') and hasattr(agent._component, 'context'):
            return agent._component.context
        return "shared"

    @staticmethod
    def _get_stream_items(upstream_outputs: Dict[str, Any]) -> List[Any]:
        """从上游输出中提取可迭代的数组值。

        遍历所有上游 agent 的输出，收集其中类型为 list 的值。
        """
        items: List[Any] = []
        for output in upstream_outputs.values():
            if isinstance(output, dict):
                for value in output.values():
                    if isinstance(value, list):
                        items.extend(value)
        return items

    def _emit(self, event: SchedulerEvent) -> None:
        """
        发射事件。回调失败不影响调度执行。

        当 on_event 为 None 时直接跳过（零开销）。
        """
        if self._on_event is None:
            return
        try:
            self._on_event(event)
        except Exception:
            # 回调失败不应影响工作流执行
            pass

    async def run(self, context: WorkflowContext) -> ExecutionRecord:
        """
        执行工作流

        Args:
            context: 工作流上下文

        Returns:
            执行记录
        """
        self.execution_record.start()
        self._emit(SchedulerEvent(
            event_type=SchedulerEventType.WORKFLOW_START,
            data={"workflow_name": self.workflow.name},
        ))

        try:
            groups = self.dag.get_parallel_groups()

            for group in groups:
                await self._execute_group(group, context)

            self.execution_record.complete()
            self._emit(SchedulerEvent(
                event_type=SchedulerEventType.WORKFLOW_COMPLETE,
                data={"execution_record": self.execution_record},
            ))

        except Exception as e:
            self.execution_record.fail(str(e))
            self._emit(SchedulerEvent(
                event_type=SchedulerEventType.WORKFLOW_FAILED,
                data={"error": str(e), "execution_record": self.execution_record},
            ))
            raise SchedulerError(f"Workflow execution failed: {e}")

        return self.execution_record

    async def _execute_group(self, group: list, context: WorkflowContext) -> None:
        """执行一组可以并行执行的 Agent

        将组内 agent 分为 batch 和 stream 两类：
        - batch agent：并行 gather（保持原有行为）
        - stream agent：逐项触发，每个上游输出项执行一次
        """
        agents_to_execute = []
        for agent_name in group:
            if self._should_execute(agent_name, context):
                agents_to_execute.append(agent_name)

        if not agents_to_execute:
            return

        # 分离 batch 和 stream agents
        batch_agents: List[str] = []
        stream_agents: List[str] = []
        for agent_name in agents_to_execute:
            if self._get_agent_mode(agent_name) == "stream":
                stream_agents.append(agent_name)
            else:
                batch_agents.append(agent_name)

        self._emit(SchedulerEvent(
            event_type=SchedulerEventType.GROUP_START,
            data={"agents": agents_to_execute},
        ))

        # 执行 batch agents（并行 gather，保持原有行为）
        if batch_agents:
            tasks = []
            for agent_name in batch_agents:
                task = asyncio.create_task(
                    self._execute_agent(agent_name, context)
                )
                tasks.append(task)

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for agent_name, result in zip(batch_agents, results):
                if isinstance(result, Exception):
                    await self._handle_failure(agent_name, result, context)
                else:
                    context.set(agent_name, result)

        # 执行 stream agents（逐项触发）
        for agent_name in stream_agents:
            try:
                results = await self._execute_stream_agent(agent_name, context)
                context.set(agent_name, results)
            except Exception as e:
                await self._handle_failure(agent_name, e, context)

        self._emit(SchedulerEvent(
            event_type=SchedulerEventType.GROUP_COMPLETE,
            data={"agents": agents_to_execute},
        ))

    async def _execute_agent(self, agent_name: str, context: WorkflowContext) -> Dict[str, Any]:
        """执行单个 Agent"""
        agent = self.agents.get(agent_name)
        if not agent:
            raise SchedulerError(f"Agent '{agent_name}' not found")

        record = AgentExecutionRecord(agent_name=agent_name)
        record.started_at = datetime.now()
        record.status = ExecutionStatus.RUNNING
        self.execution_record.agent_records[agent_name] = record

        self._emit(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_START,
            agent_name=agent_name,
            timestamp=record.started_at,
        ))

        try:
            input_data = self._prepare_input(agent_name, context)
            record.input_data = input_data

            # 优先使用 execute()（带校验和重试），回退到 run()
            if hasattr(agent, 'execute'):
                output = await agent.execute(input_data)
            else:
                output = await agent.run(input_data)

            record.status = ExecutionStatus.COMPLETED
            record.output_data = output
            record.completed_at = datetime.now()
            if record.started_at:
                record.duration_ms = int(
                    (record.completed_at - record.started_at).total_seconds() * 1000
                )

            self._emit(SchedulerEvent(
                event_type=SchedulerEventType.AGENT_COMPLETE,
                agent_name=agent_name,
                timestamp=record.completed_at,
                data={"output": output, "duration_ms": record.duration_ms},
            ))

            return output

        except Exception as e:
            record.status = ExecutionStatus.FAILED
            record.error = str(e)
            record.completed_at = datetime.now()
            if record.started_at:
                record.duration_ms = int(
                    (record.completed_at - record.started_at).total_seconds() * 1000
                )

            self._emit(SchedulerEvent(
                event_type=SchedulerEventType.AGENT_FAIL,
                agent_name=agent_name,
                timestamp=record.completed_at,
                data={"error": str(e), "duration_ms": record.duration_ms},
            ))
            raise

    async def _execute_stream_agent(self, agent_name: str, context: WorkflowContext) -> List[Dict[str, Any]]:
        """执行 Stream 模式的 Agent

        从上游输出中提取数组项，每个项触发一次 agent 执行。
        - shared 模式：复用同一个 agent 实例（累积上下文）
        - independent 模式：每次创建新实例（无状态）

        Returns:
            所有触发结果的列表
        """
        agent = self.agents.get(agent_name)
        if not agent:
            raise SchedulerError(f"Agent '{agent_name}' not found")

        # 收集上游输出
        dependencies = self.dag.get_dependencies(agent_name)
        upstream_outputs: Dict[str, Any] = {}
        for dep_name in dependencies:
            upstream_outputs[dep_name] = context.get(dep_name)

        # 提取可迭代项
        items = self._get_stream_items(upstream_outputs)
        if not items:
            # 无可迭代项，回退到单次 batch 执行
            result = await self._execute_agent(agent_name, context)
            return [result]

        context_strategy = self._get_agent_context_strategy(agent_name)
        all_results: List[Dict[str, Any]] = []

        for item in items:
            # 构造输入：原始依赖数据 + 当前项
            input_data: Dict[str, Any] = {"_deps": dict(upstream_outputs), "_stream_item": item}

            record = AgentExecutionRecord(agent_name=f"{agent_name}[stream]")
            record.started_at = datetime.now()
            record.status = ExecutionStatus.RUNNING
            record.input_data = input_data

            self._emit(SchedulerEvent(
                event_type=SchedulerEventType.AGENT_START,
                agent_name=agent_name,
                timestamp=record.started_at,
                data={"stream_item": item},
            ))

            try:
                if context_strategy == "independent":
                    # 每次创建新实例
                    from copy import deepcopy
                    fresh = deepcopy(agent)
                    if hasattr(fresh, 'execute'):
                        output = await fresh.execute(input_data)
                    else:
                        output = await fresh.run(input_data)
                else:
                    # shared 模式：复用同一实例
                    if hasattr(agent, 'execute'):
                        output = await agent.execute(input_data)
                    else:
                        output = await agent.run(input_data)

                record.status = ExecutionStatus.COMPLETED
                record.output_data = output
                record.completed_at = datetime.now()
                if record.started_at:
                    record.duration_ms = int(
                        (record.completed_at - record.started_at).total_seconds() * 1000
                    )

                self._emit(SchedulerEvent(
                    event_type=SchedulerEventType.AGENT_COMPLETE,
                    agent_name=agent_name,
                    timestamp=record.completed_at,
                    data={"output": output, "duration_ms": record.duration_ms, "stream_item": item},
                ))

                all_results.append(output)

            except Exception as e:
                record.status = ExecutionStatus.FAILED
                record.error = str(e)
                record.completed_at = datetime.now()
                if record.started_at:
                    record.duration_ms = int(
                        (record.completed_at - record.started_at).total_seconds() * 1000
                    )

                self._emit(SchedulerEvent(
                    event_type=SchedulerEventType.AGENT_FAIL,
                    agent_name=agent_name,
                    timestamp=record.completed_at,
                    data={"error": str(e), "duration_ms": record.duration_ms, "stream_item": item},
                ))

                # stream 模式：单次失败不中断后续触发
                on_fail = "stop"
                if agent and hasattr(agent, 'on_fail'):
                    on_fail = agent.on_fail
                agent_instance = self._get_agent_instance(agent_name)
                if agent_instance and "on_fail" in agent_instance.overrides:
                    on_fail = agent_instance.overrides["on_fail"]

                if on_fail == "stop":
                    raise
                # skip/retry：记录错误但继续下一个 item

        return all_results

    def _prepare_input(self, agent_name: str, context: WorkflowContext) -> Dict[str, Any]:
        """准备 Agent 输入数据"""
        dependencies = self.dag.get_dependencies(agent_name)
        deps = {}
        for dep_name in dependencies:
            deps[dep_name] = context.get(dep_name)

        # 根节点（无依赖）使用工作流输入
        if not dependencies and self.workflow_input:
            result = dict(self.workflow_input)
            result["_deps"] = deps
            return result

        return {"_deps": deps}

    def _should_execute(self, agent_name: str, context: WorkflowContext) -> bool:
        """
        判断 Agent 是否应该执行

        支持条件路由：如果入边 Connection 有 routing_rules，
        则根据源 Agent 输出的 route 字段值决定是否执行。
        """
        incoming = self.dag.get_incoming_connections(agent_name)

        # 没有入边 = 起始节点
        if not incoming:
            return True

        # 检查条件路由
        for conn in incoming:
            if conn.routing_rules:
                source_output = context.get(conn.source_agent)
                if source_output:
                    route_value = source_output.get("route")
                    if route_value and route_value in conn.routing_rules:
                        if agent_name in conn.routing_rules[route_value]:
                            return True
                # 有 routing_rules 但没匹配到，不执行
                return False

        # 普通连接：检查所有依赖是否完成
        return self.dag.is_ready(agent_name, set(context._data.keys()))

    async def _handle_failure(self, agent_name: str, error: Exception, context: WorkflowContext) -> None:
        """处理 Agent 执行失败"""
        # 获取失败策略：优先从 agent 对象读取，然后从 workflow AgentInstance 覆盖
        on_fail = "stop"
        retry_count = 3

        agent = self.agents.get(agent_name)

        # 1. 从 agent 对象获取（如 MockAgent.on_fail, Agent.on_fail）
        if agent and hasattr(agent, 'on_fail'):
            on_fail = agent.on_fail
        if agent and hasattr(agent, 'retry_count'):
            retry_count = agent.retry_count

        # 2. 从 workflow AgentInstance 覆盖
        agent_instance = self._get_agent_instance(agent_name)
        if agent_instance:
            if "on_fail" in agent_instance.overrides:
                on_fail = agent_instance.overrides["on_fail"]
            if "retry_count" in agent_instance.overrides:
                retry_count = agent_instance.overrides["retry_count"]

        if on_fail == "stop":
            raise error

        elif on_fail == "skip":
            context.set(agent_name, {})
            self._emit(SchedulerEvent(
                event_type=SchedulerEventType.AGENT_SKIPPED,
                agent_name=agent_name,
                data={"reason": "on_fail=skip"},
            ))

        elif on_fail == "retry":
            for i in range(retry_count):
                self._emit(SchedulerEvent(
                    event_type=SchedulerEventType.AGENT_RETRY,
                    agent_name=agent_name,
                    data={"attempt": i + 1, "max_retries": retry_count},
                ))
                try:
                    agent = self.agents.get(agent_name)
                    input_data = self._prepare_input(agent_name, context)
                    if hasattr(agent, 'execute'):
                        output = await agent.execute(input_data)
                    else:
                        output = await agent.run(input_data)
                    context.set(agent_name, output)
                    return
                except Exception:
                    if i == retry_count - 1:
                        raise error

        else:
            raise SchedulerError(f"Unknown on_fail strategy: {on_fail}")
