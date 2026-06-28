"""
GrassFlow 调度器 (v2)

实现功能：
- asyncio 并行调度
- port-aware 输入映射
- 基于 Connection 的条件判断
- 失败策略（stop/skip/retry）
"""

import asyncio
from typing import Dict, Any, List
from datetime import datetime

try:
    from core.models import Workflow, AgentInstance
except ImportError:
    from core.dsl_v2_ast import Workflow, AgentInstance
from core.execution import ExecutionRecord, AgentExecutionRecord, ExecutionStatus
from core.agent import Agent
from core.dag import DAG, DAGError
from core.context import WorkflowContext


class SchedulerError(Exception):
    """调度器相关错误"""
    pass


class Scheduler:
    """工作流调度器 (v2 - port-aware)"""

    def __init__(self, workflow: Workflow, agents: Dict[str, Agent]):
        """
        初始化调度器

        Args:
            workflow: 工作流定义 (v2 Workflow)
            agents: Agent 实例字典，key 为 Agent 名称，value 为 Agent 实例
        """
        self.workflow = workflow
        self.agents = agents
        self.dag = DAG(workflow)
        self.execution_record = ExecutionRecord(workflow_name=workflow.name)

    async def run(self, context: WorkflowContext) -> ExecutionRecord:
        """
        执行工作流

        Args:
            context: 工作流上下文

        Returns:
            执行记录
        """
        self.execution_record.start()

        try:
            groups = self.dag.get_parallel_groups()

            for group in groups:
                await self._execute_group(group, context)

            self.execution_record.complete()

        except Exception as e:
            self.execution_record.fail(str(e))
            raise SchedulerError(f"Workflow execution failed: {e}")

        return self.execution_record

    async def _execute_group(self, group: List[str], context: WorkflowContext) -> None:
        """
        执行一组可以并行执行的 Agent

        Args:
            group: Agent 名称列表
            context: 工作流上下文
        """
        agents_to_execute = [
            name for name in group
            if self._should_execute(name, context)
        ]

        if not agents_to_execute:
            return

        tasks = [
            asyncio.create_task(self._execute_agent(name, context))
            for name in agents_to_execute
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for agent_name, result in zip(agents_to_execute, results):
            if isinstance(result, Exception):
                await self._handle_failure(agent_name, result, context)
            else:
                context.set(agent_name, result)

    async def _execute_agent(self, agent_name: str, context: WorkflowContext) -> Dict[str, Any]:
        """
        执行单个 Agent

        Args:
            agent_name: Agent 名称
            context: 工作流上下文

        Returns:
            Agent 输出数据
        """
        agent = self.agents.get(agent_name)
        if not agent:
            raise SchedulerError(f"Agent '{agent_name}' not found")

        record = AgentExecutionRecord(agent_name=agent_name)
        record.started_at = datetime.now()
        record.status = ExecutionStatus.RUNNING
        self.execution_record.agent_records[agent_name] = record

        try:
            input_data = self._prepare_input(agent_name, context)
            record.input_data = input_data

            output = await agent.execute(input_data)

            record.status = ExecutionStatus.COMPLETED
            record.output_data = output
            record.completed_at = datetime.now()
            if record.started_at:
                record.duration_ms = int(
                    (record.completed_at - record.started_at).total_seconds() * 1000
                )

            return output

        except Exception as e:
            record.status = ExecutionStatus.FAILED
            record.error = str(e)
            record.completed_at = datetime.now()
            if record.started_at:
                record.duration_ms = int(
                    (record.completed_at - record.started_at).total_seconds() * 1000
                )
            raise

    def _prepare_input(self, agent_name: str, context: WorkflowContext) -> Dict[str, Any]:
        """
        准备 Agent 输入数据 (port-aware)

        按 Connection 的端口映射组装输入：
        - 有 source_port + target_ports 时做端口到端口映射
        - 否则将源输出整体合并
        - 始终附带 _deps 字段

        Args:
            agent_name: Agent 名称
            context: 工作流上下文

        Returns:
            输入数据字典
        """
        incoming = self.dag.get_incoming_connections(agent_name)

        port_inputs: Dict[str, Any] = {}
        deps: Dict[str, Any] = {}

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

    def _should_execute(self, agent_name: str, context: WorkflowContext) -> bool:
        """
        判断 Agent 是否应该执行 (基于 Connection)

        规则：
        - 无入连接 -> 根节点，直接执行
        - 有入连接 -> 检查所有源 Agent 是否已执行完成

        Args:
            agent_name: Agent 名称
            context: 工作流上下文

        Returns:
            如果应该执行返回 True，否则返回 False
        """
        incoming = self.dag.get_incoming_connections(agent_name)

        if not incoming:
            return True

        completed = set(context._data.keys())

        for conn in incoming:
            if conn.source_agent not in completed:
                return False

        return True

    async def _handle_failure(
        self, agent_name: str, error: Exception, context: WorkflowContext
    ) -> None:
        """
        处理 Agent 执行失败

        Args:
            agent_name: Agent 名称
            error: 异常
            context: 工作流上下文
        """
        agent_instance = None
        for a in self.workflow.agents:
            if a.name == agent_name:
                agent_instance = a
                break

        on_fail = "stop"
        retry_count = 3
        if agent_instance:
            on_fail = getattr(agent_instance, "on_fail", "stop") or "stop"
            retry_count = getattr(agent_instance, "retry_count", 3) or 3

        if on_fail == "stop":
            raise error

        elif on_fail == "skip":
            context.set(agent_name, {})
            record = self.execution_record.agent_records.get(agent_name)
            if record:
                record.status = ExecutionStatus.SKIPPED

        elif on_fail == "retry":
            for i in range(retry_count):
                try:
                    agent = self.agents.get(agent_name)
                    if not agent:
                        raise SchedulerError(f"Agent '{agent_name}' not found")
                    input_data = self._prepare_input(agent_name, context)
                    output = await agent.execute(input_data)
                    context.set(agent_name, output)
                    record = self.execution_record.agent_records.get(agent_name)
                    if record:
                        record.status = ExecutionStatus.COMPLETED
                        record.output_data = output
                        record.error = None
                    return
                except Exception:
                    if i == retry_count - 1:
                        raise error

        else:
            raise SchedulerError(f"Unknown on_fail strategy: {on_fail}")
