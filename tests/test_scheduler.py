"""
调度器测试

测试内容：
- 顺序执行
- 并行执行
- 失败策略
- 条件分支

使用 v2 类型: Workflow, AgentInstance, Connection
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from core.models import Workflow, AgentInstance, Connection, Component, ModelConfig
from core.context import WorkflowContext
from core.scheduler import Scheduler, SchedulerError
from core.execution import ExecutionStatus


def make_workflow(
    agent_names: list[str] | None = None,
    connections: list[tuple[str, list[str]]] | None = None,
    routing: dict | None = None,
    name: str = "test",
) -> Workflow:
    """Build a v2 Workflow from concise specs."""
    agents = [AgentInstance(name=n) for n in (agent_names or [])]
    conns = [
        Connection(source_agent=src, target_agents=tgts)
        for src, tgts in (connections or [])
    ]
    if routing:
        for src, rules in routing.items():
            # 找到对应的 connection 并添加 routing_rules
            for conn in conns:
                if conn.source_agent == src:
                    conn.routing_rules = rules
    return Workflow(name=name, agents=agents, connections=conns)


class MockAgent:
    """模拟 Agent"""

    def __init__(self, name: str, fail: bool = False, delay: float = 0):
        self.name = name
        self.fail = fail
        self.delay = delay
        self.executed = False
        self.input_data = None
        self.on_fail = "stop"
        self.retry_count = 3

    async def run(self, input_data: dict) -> dict:
        """模拟执行"""
        self.executed = True
        self.input_data = input_data

        if self.delay > 0:
            await asyncio.sleep(self.delay)

        if self.fail:
            raise Exception(f"Agent {self.name} failed")

        return {"result": f"{self.name}_output"}


class TestScheduler:
    """调度器测试"""

    @pytest.fixture
    def workflow(self):
        return make_workflow(
            agent_names=["A", "B", "C"],
            name="test",
        )

    @pytest.fixture
    def context(self):
        return WorkflowContext()

    @pytest.mark.asyncio
    async def test_simple_sequence(self, workflow, context):
        """测试简单顺序执行：A -> B -> C"""
        workflow.connections = [
            Connection(source_agent="A", target_agents=["B"]),
            Connection(source_agent="B", target_agents=["C"]),
        ]

        agent_a = MockAgent("A")
        agent_b = MockAgent("B")
        agent_c = MockAgent("C")

        agents = {"A": agent_a, "B": agent_b, "C": agent_c}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        assert agent_a.executed
        assert agent_b.executed
        assert agent_c.executed
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_parallel_execution(self, workflow, context):
        """测试并行执行：(A, B) -> C"""
        workflow.connections = [
            Connection(source_agent="A", target_agents=["C"]),
            Connection(source_agent="B", target_agents=["C"]),
        ]

        agent_a = MockAgent("A", delay=0.1)
        agent_b = MockAgent("B", delay=0.1)
        agent_c = MockAgent("C")

        agents = {"A": agent_a, "B": agent_b, "C": agent_c}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        assert agent_a.executed
        assert agent_b.executed
        assert agent_c.executed
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_failure_stop(self, workflow, context):
        """测试失败策略：stop（默认）"""
        workflow.connections = [
            Connection(source_agent="A", target_agents=["B"]),
            Connection(source_agent="B", target_agents=["C"]),
        ]

        agent_a = MockAgent("A")
        agent_b = MockAgent("B", fail=True)
        agent_c = MockAgent("C")

        agents = {"A": agent_a, "B": agent_b, "C": agent_c}

        scheduler = Scheduler(workflow, agents)

        with pytest.raises(SchedulerError):
            await scheduler.run(context)

        assert agent_a.executed
        assert agent_b.executed
        assert not agent_c.executed

    @pytest.mark.asyncio
    async def test_failure_skip(self, workflow, context):
        """测试失败策略：skip"""
        workflow.connections = [
            Connection(source_agent="A", target_agents=["B"]),
            Connection(source_agent="B", target_agents=["C"]),
        ]

        agent_a = MockAgent("A")
        agent_b = MockAgent("B", fail=True)
        agent_b.on_fail = "skip"
        agent_c = MockAgent("C")

        agents = {"A": agent_a, "B": agent_b, "C": agent_c}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        assert agent_a.executed
        assert agent_b.executed
        assert agent_c.executed
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_failure_retry(self, context):
        """测试失败策略：retry"""
        workflow = make_workflow(
            agent_names=["A", "B"],
            connections=[("A", ["B"])],
            name="test_retry",
        )

        call_count = 0

        class RetryAgent(MockAgent):
            async def run(self, input_data: dict) -> dict:
                nonlocal call_count
                self.executed = True
                self.input_data = input_data
                call_count += 1
                if call_count < 3:
                    raise Exception(f"Agent {self.name} failed")
                return {"result": f"{self.name}_output"}

        agent_a = MockAgent("A")
        agent_b = RetryAgent("B")
        agent_b.on_fail = "retry"
        agent_b.retry_count = 3

        agents = {"A": agent_a, "B": agent_b}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        assert agent_a.executed
        assert agent_b.executed
        assert call_count == 3
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_condition_branch(self, context):
        """测试条件分支"""
        workflow = Workflow(
            name="test_condition",
            agents=[
                AgentInstance(name="A"),
                AgentInstance(name="route"),
                AgentInstance(name="output1"),
                AgentInstance(name="output2"),
            ],
            connections=[
                Connection(source_agent="A", target_agents=["route"]),
                Connection(
                    source_agent="route",
                    target_agents=["output1", "output2"],
                    routing_rules={
                        "urgent": ["output1"],
                        "normal": ["output2"],
                    },
                ),
            ],
        )

        agent_a = MockAgent("A")
        agent_route = MockAgent("route")

        async def route_run(input_data: dict) -> dict:
            agent_route.executed = True
            agent_route.input_data = input_data
            return {"route": "urgent"}

        agent_route.run = route_run
        agent_output1 = MockAgent("output1")
        agent_output2 = MockAgent("output2")

        agents = {
            "A": agent_a,
            "route": agent_route,
            "output1": agent_output1,
            "output2": agent_output2,
        }

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        assert agent_a.executed
        assert agent_route.executed
        assert agent_output1.executed
        assert not agent_output2.executed
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_empty_workflow(self, context):
        """测试空工作流"""
        workflow = Workflow(name="test_empty")
        agents = {}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_single_agent(self, context):
        """测试单个 Agent"""
        workflow = make_workflow(agent_names=["A"], name="test_single")

        agent_a = MockAgent("A")
        agents = {"A": agent_a}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        assert agent_a.executed
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_context_data_passing(self, context):
        """测试数据传递"""
        workflow = make_workflow(
            agent_names=["A", "B"],
            connections=[("A", ["B"])],
            name="test_data",
        )

        agent_a = MockAgent("A")
        agent_b = MockAgent("B")

        agents = {"A": agent_a, "B": agent_b}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        assert agent_b.input_data is not None
        assert "_deps" in agent_b.input_data
        assert "A" in agent_b.input_data["_deps"]

    @pytest.mark.asyncio
    async def test_execution_record(self, context):
        """测试执行记录"""
        workflow = make_workflow(
            agent_names=["A", "B"],
            connections=[("A", ["B"])],
            name="test_record",
        )

        agent_a = MockAgent("A")
        agent_b = MockAgent("B")

        agents = {"A": agent_a, "B": agent_b}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        assert result.workflow_name == "test_record"
        assert "A" in result.agent_records
        assert "B" in result.agent_records
        assert result.agent_records["A"].status == ExecutionStatus.COMPLETED
        assert result.agent_records["B"].status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_immediate_execution(self, context):
        """测试立即执行：A | B (both start immediately)"""
        workflow = make_workflow(
            agent_names=["A", "B"],
            connections=[("A", ["B"])],
            name="test_immediate",
        )

        agent_a = MockAgent("A", delay=0.1)
        agent_b = MockAgent("B")

        agents = {"A": agent_a, "B": agent_b}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        assert agent_a.executed
        assert agent_b.executed
        assert result.status == ExecutionStatus.COMPLETED
