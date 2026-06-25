"""
GrassFlow 调度器

实现功能：
- asyncio 并行调度
- 顺序/并行执行
- 失败策略（stop/skip/retry）
- 条件分支
"""

import asyncio
from typing import Dict, Any, Optional, Set
from datetime import datetime
from core.models import (
    Workflow, AgentConfig, Edge, AgentType,
    InteractionType, ExecutionStatus, ExecutionRecord, AgentExecutionRecord
)
from core.context import WorkflowContext
from core.dag import DAG, DAGError


class SchedulerError(Exception):
    """调度器相关错误"""
    pass


class Scheduler:
    """工作流调度器"""

    def __init__(self, workflow: Workflow, agents: Dict[str, Any]):
        """
        初始化调度器

        Args:
            workflow: 工作流定义
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
            # 获取并行执行组
            groups = self.dag.get_parallel_groups()

            # 按组执行
            for group in groups:
                await self._execute_group(group, context)

            self.execution_record.complete()

        except Exception as e:
            self.execution_record.fail(str(e))
            raise SchedulerError(f"Workflow execution failed: {e}")

        return self.execution_record

    async def _execute_group(self, group: list, context: WorkflowContext) -> None:
        """
        执行一组可以并行执行的 Agent

        Args:
            group: Agent 名称列表
            context: 工作流上下文
        """
        # 过滤出需要执行的 Agent
        agents_to_execute = []
        for agent_name in group:
            # 检查是否满足执行条件
            if self._should_execute(agent_name, context):
                agents_to_execute.append(agent_name)

        if not agents_to_execute:
            return

        # 并行执行所有 Agent
        tasks = []
        for agent_name in agents_to_execute:
            task = asyncio.create_task(
                self._execute_agent(agent_name, context)
            )
            tasks.append(task)

        # 等待所有任务完成
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理结果
        for agent_name, result in zip(agents_to_execute, results):
            if isinstance(result, Exception):
                # 执行失败
                await self._handle_failure(agent_name, result, context)
            else:
                # 执行成功
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

        # 创建执行记录
        record = AgentExecutionRecord(agent_name=agent_name)
        record.started_at = datetime.now()
        record.status = ExecutionStatus.RUNNING
        self.execution_record.agent_records[agent_name] = record

        try:
            # 准备输入数据
            input_data = self._prepare_input(agent_name, context)
            record.input_data = input_data

            # 执行 Agent
            output = await agent.run(input_data)

            # 更新执行记录
            record.status = ExecutionStatus.COMPLETED
            record.output_data = output
            record.completed_at = datetime.now()
            if record.started_at:
                record.duration_ms = int(
                    (record.completed_at - record.started_at).total_seconds() * 1000
                )

            return output

        except Exception as e:
            # 更新执行记录
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
        准备 Agent 输入数据

        Args:
            agent_name: Agent 名称
            context: 工作流上下文

        Returns:
            输入数据字典
        """
        # 获取依赖数据
        dependencies = self.dag.get_dependencies(agent_name)
        deps = {}
        for dep_name in dependencies:
            deps[dep_name] = context.get(dep_name)

        return {"_deps": deps}

    def _should_execute(self, agent_name: str, context: WorkflowContext) -> bool:
        """
        判断 Agent 是否应该执行

        Args:
            agent_name: Agent 名称
            context: 工作流上下文

        Returns:
            如果应该执行返回 True，否则返回 False
        """
        # 获取入边
        incoming_edges = self.dag.get_incoming_edges(agent_name)

        # 如果没有入边，说明是起始节点，应该执行
        if not incoming_edges:
            return True

        # 检查条件分支
        condition_edges = [
            edge for edge in incoming_edges
            if edge.interaction_type == InteractionType.CONDITION
        ]

        if condition_edges:
            # 是条件分支节点，检查是否有匹配的条件
            for edge in condition_edges:
                source_output = context.get(edge.source)
                if source_output:
                    # 检查 route 字段或其他条件
                    route_value = source_output.get("route")
                    if route_value == edge.condition:
                        return True
            return False

        # 检查所有依赖是否都已完成
        return self.dag.is_ready(agent_name, set(context._data.keys()))

    async def _handle_failure(self, agent_name: str, error: Exception, context: WorkflowContext) -> None:
        """
        处理 Agent 执行失败

        Args:
            agent_name: Agent 名称
            error: 异常
            context: 工作流上下文
        """
        agent_config = self.workflow.get_agent(agent_name)
        if not agent_config:
            raise SchedulerError(f"Agent config '{agent_name}' not found")

        on_fail = agent_config.on_fail

        if on_fail == "stop":
            # 停止整个工作流
            raise error

        elif on_fail == "skip":
            # 跳过该 Agent，用空结果继续
            context.set(agent_name, {})

        elif on_fail == "retry":
            # 重试
            retry_count = agent_config.retry_count
            for i in range(retry_count):
                try:
                    agent = self.agents.get(agent_name)
                    input_data = self._prepare_input(agent_name, context)
                    output = await agent.run(input_data)
                    context.set(agent_name, output)
                    return
                except Exception:
                    if i == retry_count - 1:
                        raise error

        else:
            raise SchedulerError(f"Unknown on_fail strategy: {on_fail}")
