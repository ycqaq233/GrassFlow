"""
GrassFlow 调度器

实现功能：
- asyncio 并行调度
- 顺序/并行执行
- 失败策略（stop/skip/retry）
- 条件分支

使用 v2 类型: Workflow, AgentInstance
"""

import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
from core.models import Workflow, AgentInstance
from core.execution import ExecutionRecord, AgentExecutionRecord, ExecutionStatus
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
            workflow: 工作流定义 (v2)
            agents: Agent 实例字典，key 为 Agent 名称，value 为 Agent 实例
        """
        self.workflow = workflow
        self.agents = agents
        self.dag = DAG(workflow)
        self.execution_record = ExecutionRecord(workflow_name=workflow.name)

    def _get_agent_instance(self, agent_name: str) -> Optional[AgentInstance]:
        """从 workflow 中获取 AgentInstance 定义"""
        for ai in self.workflow.agents:
            if ai.name == agent_name:
                return ai
        return None

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

    async def _execute_group(self, group: list, context: WorkflowContext) -> None:
        """执行一组可以并行执行的 Agent"""
        agents_to_execute = []
        for agent_name in group:
            if self._should_execute(agent_name, context):
                agents_to_execute.append(agent_name)

        if not agents_to_execute:
            return

        tasks = []
        for agent_name in agents_to_execute:
            task = asyncio.create_task(
                self._execute_agent(agent_name, context)
            )
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for agent_name, result in zip(agents_to_execute, results):
            if isinstance(result, Exception):
                await self._handle_failure(agent_name, result, context)
            else:
                context.set(agent_name, result)

    async def _execute_agent(self, agent_name: str, context: WorkflowContext) -> Dict[str, Any]:
        """执行单个 Agent"""
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
        """准备 Agent 输入数据"""
        dependencies = self.dag.get_dependencies(agent_name)
        deps = {}
        for dep_name in dependencies:
            deps[dep_name] = context.get(dep_name)

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

        elif on_fail == "retry":
            for i in range(retry_count):
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
