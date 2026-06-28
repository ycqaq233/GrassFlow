"""
调度器测试

测试内容：
- 顺序执行
- 并行执行
- 失败策略
- 条件分支
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
try:
    from core.models import (
        Component, Workflow, AgentInstance, Connection, Port, ModelConfig,
        WorkflowV1, AgentConfig, Edge, AgentType, InteractionType, ExecutionStatus,
    )
except ImportError:
    from core.dsl_v2_ast import Component, Workflow, AgentInstance, Connection, Port, ModelConfig
    from core.models import WorkflowV1, AgentConfig, Edge, AgentType, InteractionType, ExecutionStatus
from core.context import WorkflowContext
from core.scheduler import Scheduler, SchedulerError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_v1_workflow(
    agents: list[tuple[str, str]] | None = None,
    edges: list[tuple[str, str, str | None, str | None]] | None = None,
    name: str = "test",
) -> WorkflowV1:
    """Build a v1 Workflow from concise specs."""
    type_map = {
        "llm": AgentType.LLM,
        "condition": AgentType.CONDITION,
        "manual": AgentType.MANUAL,
        "input": AgentType.INPUT,
        "output": AgentType.OUTPUT,
    }
    interaction_map = {
        "sequence": InteractionType.SEQUENCE,
        "parallel": InteractionType.PARALLEL,
        "immediate": InteractionType.IMMEDIATE,
        "condition": InteractionType.CONDITION,
        None: InteractionType.SEQUENCE,
    }
    wf = WorkflowV1(name=name)
    for agent_name, agent_type in (agents or []):
        wf.add_agent(AgentConfig(name=agent_name, type=type_map.get(agent_type, AgentType.LLM)))
    for src, tgt, itype, cond in (edges or []):
        wf.add_edge(Edge(
            source=src, target=tgt,
            interaction_type=interaction_map.get(itype, InteractionType.SEQUENCE),
            condition=cond,
        ))
    return wf


class MockAgent:
    """模拟 Agent"""

    def __init__(self, name: str, fail: bool = False, delay: float = 0):
        self.name = name
        self.fail = fail
        self.delay = delay
        self.executed = False
        self.input_data = None

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
        """创建测试工作流"""
        return make_v1_workflow(
            agents=[("A", "llm"), ("B", "llm"), ("C", "llm")],
            name="test",
        )

    @pytest.fixture
    def context(self):
        """创建测试上下文"""
        return WorkflowContext()

    @pytest.mark.asyncio
    async def test_simple_sequence(self, workflow, context):
        """测试简单顺序执行：A -> B -> C"""
        workflow.add_edge(Edge(source="A", target="B"))
        workflow.add_edge(Edge(source="B", target="C"))

        agent_a = MockAgent("A")
        agent_b = MockAgent("B")
        agent_c = MockAgent("C")

        agents = {"A": agent_a, "B": agent_b, "C": agent_c}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        # 验证执行顺序
        assert agent_a.executed
        assert agent_b.executed
        assert agent_c.executed

        # 验证状态
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_parallel_execution(self, workflow, context):
        """测试并行执行：(A, B) -> C"""
        workflow.add_edge(Edge(source="A", target="C", interaction_type=InteractionType.PARALLEL))
        workflow.add_edge(Edge(source="B", target="C", interaction_type=InteractionType.PARALLEL))

        agent_a = MockAgent("A", delay=0.1)
        agent_b = MockAgent("B", delay=0.1)
        agent_c = MockAgent("C")

        agents = {"A": agent_a, "B": agent_b, "C": agent_c}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        # 验证所有 Agent 都被执行
        assert agent_a.executed
        assert agent_b.executed
        assert agent_c.executed

        # 验证状态
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_failure_stop(self, workflow, context):
        """测试失败策略：stop（默认）"""
        workflow.add_edge(Edge(source="A", target="B"))
        workflow.add_edge(Edge(source="B", target="C"))

        agent_a = MockAgent("A")
        agent_b = MockAgent("B", fail=True)
        agent_c = MockAgent("C")

        agents = {"A": agent_a, "B": agent_b, "C": agent_c}

        scheduler = Scheduler(workflow, agents)

        # 应该抛出 SchedulerError
        with pytest.raises(SchedulerError):
            await scheduler.run(context)

        # 验证 A 执行成功，B 失败，C 未执行
        assert agent_a.executed
        assert agent_b.executed
        assert not agent_c.executed

    @pytest.mark.asyncio
    async def test_failure_skip(self, workflow, context):
        """测试失败策略：skip"""
        workflow.add_edge(Edge(source="A", target="B"))
        workflow.add_edge(Edge(source="B", target="C"))

        agent_a = MockAgent("A")
        agent_b = MockAgent("B", fail=True)
        agent_b_config = workflow.get_agent("B")
        agent_b_config.on_fail = "skip"

        agent_c = MockAgent("C")

        agents = {"A": agent_a, "B": agent_b, "C": agent_c}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        # 验证 A 执行成功，B 失败但被跳过，C 继续执行
        assert agent_a.executed
        assert agent_b.executed
        assert agent_c.executed

        # 验证状态
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_failure_retry(self, context):
        """测试失败策略：retry"""
        workflow = make_v1_workflow(
            agents=[("A", "llm"), ("B", "llm")],
            edges=[("A", "B", None, None)],
            name="test_retry",
        )

        # 创建一个会失败两次然后成功的 Agent
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
        agent_b_config = workflow.get_agent("B")
        agent_b_config.on_fail = "retry"
        agent_b_config.retry_count = 3

        agents = {"A": agent_a, "B": agent_b}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        # 验证 A 执行成功，B 重试后成功
        assert agent_a.executed
        assert agent_b.executed
        assert call_count == 3  # 失败两次，第三次成功

        # 验证状态
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_condition_branch(self, context):
        """测试条件分支"""
        workflow = make_v1_workflow(
            agents=[("A", "llm"), ("route", "condition"), ("output1", "output"), ("output2", "output")],
            edges=[
                ("A", "route", None, None),
                ("route", "output1", "condition", "urgent"),
                ("route", "output2", "condition", "normal"),
            ],
            name="test_condition",
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

        # 验证 A 和 route 执行
        assert agent_a.executed
        assert agent_route.executed

        # 验证只有 output1 被执行（条件为 urgent）
        assert agent_output1.executed
        assert not agent_output2.executed

        # 验证状态
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_empty_workflow(self, context):
        """测试空工作流"""
        workflow = WorkflowV1(name="test_empty")
        agents = {}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        # 验证状态
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_single_agent(self, context):
        """测试单个 Agent"""
        workflow = make_v1_workflow(agents=[("A", "llm")], name="test_single")

        agent_a = MockAgent("A")
        agents = {"A": agent_a}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        # 验证 A 被执行
        assert agent_a.executed

        # 验证状态
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_context_data_passing(self, context):
        """测试数据传递"""
        workflow = make_v1_workflow(
            agents=[("A", "llm"), ("B", "llm")],
            edges=[("A", "B", None, None)],
            name="test_data",
        )

        agent_a = MockAgent("A")
        agent_b = MockAgent("B")

        agents = {"A": agent_a, "B": agent_b}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        # 验证 B 收到了 A 的输出
        assert agent_b.input_data is not None
        assert "_deps" in agent_b.input_data
        assert "A" in agent_b.input_data["_deps"]

    @pytest.mark.asyncio
    async def test_execution_record(self, context):
        """测试执行记录"""
        workflow = make_v1_workflow(
            agents=[("A", "llm"), ("B", "llm")],
            edges=[("A", "B", None, None)],
            name="test_record",
        )

        agent_a = MockAgent("A")
        agent_b = MockAgent("B")

        agents = {"A": agent_a, "B": agent_b}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        # 验证执行记录
        assert result.workflow_name == "test_record"
        assert "A" in result.agent_records
        assert "B" in result.agent_records
        assert result.agent_records["A"].status == ExecutionStatus.COMPLETED
        assert result.agent_records["B"].status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_immediate_execution(self, context):
        """测试立即执行：A | B"""
        workflow = make_v1_workflow(
            agents=[("A", "llm"), ("B", "llm")],
            edges=[("A", "B", "immediate", None)],
            name="test_immediate",
        )

        agent_a = MockAgent("A", delay=0.1)
        agent_b = MockAgent("B")

        agents = {"A": agent_a, "B": agent_b}

        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        # 验证 A 和 B 都被执行
        assert agent_a.executed
        assert agent_b.executed

        # 验证状态
        assert result.status == ExecutionStatus.COMPLETED
