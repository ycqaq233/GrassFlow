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
from core.scheduler import Scheduler, SchedulerError, SchedulerEvent, SchedulerEventType
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


class TestSchedulerCallbacks:
    """调度器事件回调测试"""

    @pytest.fixture
    def context(self):
        return WorkflowContext()

    def _collect_events(self, events: list) -> callable:
        """创建一个收集事件的回调函数"""
        def on_event(event: SchedulerEvent):
            events.append(event)
        return on_event

    @pytest.mark.asyncio
    async def test_no_callback_zero_overhead(self, context):
        """on_event 为 None 时不发射事件，零开销"""
        workflow = make_workflow(agent_names=["A"], name="test_no_cb")
        agent_a = MockAgent("A")
        scheduler = Scheduler(workflow, {"A": agent_a})
        result = await scheduler.run(context)
        assert result.status == ExecutionStatus.COMPLETED
        # 没有回调就不会出错，完全向后兼容

    @pytest.mark.asyncio
    async def test_workflow_start_complete_events(self, context):
        """测试工作流开始和完成事件"""
        workflow = make_workflow(agent_names=["A"], name="test_wf_events")
        agent_a = MockAgent("A")
        events = []
        scheduler = Scheduler(workflow, {"A": agent_a}, on_event=self._collect_events(events))
        await scheduler.run(context)

        event_types = [e.event_type for e in events]
        assert SchedulerEventType.WORKFLOW_START in event_types
        assert SchedulerEventType.WORKFLOW_COMPLETE in event_types
        # WORKFLOW_START 应该是第一个事件
        assert events[0].event_type == SchedulerEventType.WORKFLOW_START
        assert events[0].data["workflow_name"] == "test_wf_events"
        # WORKFLOW_COMPLETE 应该是最后一个事件
        assert events[-1].event_type == SchedulerEventType.WORKFLOW_COMPLETE
        assert events[-1].data["execution_record"].status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_workflow_failed_event(self, context):
        """测试工作流失败事件"""
        workflow = make_workflow(
            agent_names=["A"],
            connections=[],
            name="test_wf_fail",
        )
        agent_a = MockAgent("A", fail=True)
        events = []
        scheduler = Scheduler(workflow, {"A": agent_a}, on_event=self._collect_events(events))

        with pytest.raises(SchedulerError):
            await scheduler.run(context)

        event_types = [e.event_type for e in events]
        assert SchedulerEventType.WORKFLOW_START in event_types
        assert SchedulerEventType.WORKFLOW_FAILED in event_types
        assert SchedulerEventType.WORKFLOW_COMPLETE not in event_types
        # 失败事件包含错误信息
        fail_event = [e for e in events if e.event_type == SchedulerEventType.WORKFLOW_FAILED][0]
        assert "error" in fail_event.data

    @pytest.mark.asyncio
    async def test_agent_start_complete_events(self, context):
        """测试 Agent 开始和完成事件"""
        workflow = make_workflow(agent_names=["A", "B"], connections=[("A", ["B"])], name="test_agent_events")
        agent_a = MockAgent("A")
        agent_b = MockAgent("B")
        events = []
        scheduler = Scheduler(workflow, {"A": agent_a, "B": agent_b}, on_event=self._collect_events(events))
        await scheduler.run(context)

        agent_start_events = [e for e in events if e.event_type == SchedulerEventType.AGENT_START]
        agent_complete_events = [e for e in events if e.event_type == SchedulerEventType.AGENT_COMPLETE]
        assert len(agent_start_events) == 2
        assert len(agent_complete_events) == 2

        # 检查 agent_name 字段
        start_names = {e.agent_name for e in agent_start_events}
        complete_names = {e.agent_name for e in agent_complete_events}
        assert start_names == {"A", "B"}
        assert complete_names == {"A", "B"}

        # 完成事件包含输出数据和耗时
        for e in agent_complete_events:
            assert "output" in e.data
            assert "duration_ms" in e.data

    @pytest.mark.asyncio
    async def test_agent_fail_event(self, context):
        """测试 Agent 失败事件"""
        workflow = make_workflow(agent_names=["A"], name="test_agent_fail")
        agent_a = MockAgent("A", fail=True)
        events = []
        scheduler = Scheduler(workflow, {"A": agent_a}, on_event=self._collect_events(events))

        with pytest.raises(SchedulerError):
            await scheduler.run(context)

        fail_events = [e for e in events if e.event_type == SchedulerEventType.AGENT_FAIL]
        assert len(fail_events) == 1
        assert fail_events[0].agent_name == "A"
        assert "error" in fail_events[0].data
        assert "duration_ms" in fail_events[0].data

    @pytest.mark.asyncio
    async def test_agent_skipped_event(self, context):
        """测试 Agent 跳过事件"""
        workflow = make_workflow(
            agent_names=["A", "B"],
            connections=[("A", ["B"])],
            name="test_skip_event",
        )
        agent_a = MockAgent("A")
        agent_b = MockAgent("B", fail=True)
        agent_b.on_fail = "skip"
        events = []
        scheduler = Scheduler(workflow, {"A": agent_a, "B": agent_b}, on_event=self._collect_events(events))
        await scheduler.run(context)

        skipped_events = [e for e in events if e.event_type == SchedulerEventType.AGENT_SKIPPED]
        assert len(skipped_events) == 1
        assert skipped_events[0].agent_name == "B"

    @pytest.mark.asyncio
    async def test_agent_retry_event(self, context):
        """测试 Agent 重试事件"""
        workflow = make_workflow(
            agent_names=["A", "B"],
            connections=[("A", ["B"])],
            name="test_retry_event",
        )
        call_count = 0

        class RetryAgent(MockAgent):
            async def run(self, input_data: dict) -> dict:
                nonlocal call_count
                self.executed = True
                call_count += 1
                if call_count < 3:
                    raise Exception(f"fail attempt {call_count}")
                return {"result": "ok"}

        agent_a = MockAgent("A")
        agent_b = RetryAgent("B")
        agent_b.on_fail = "retry"
        agent_b.retry_count = 3
        events = []
        scheduler = Scheduler(workflow, {"A": agent_a, "B": agent_b}, on_event=self._collect_events(events))
        await scheduler.run(context)

        # The first call happens in _execute_agent (not a retry), so only 2 retries occur.
        # Total calls: 1 (in _execute_agent) + 2 (in _handle_failure) = 3, agent succeeds on 3rd.
        retry_events = [e for e in events if e.event_type == SchedulerEventType.AGENT_RETRY]
        assert len(retry_events) == 2
        for i, evt in enumerate(retry_events):
            assert evt.agent_name == "B"
            assert evt.data["attempt"] == i + 1
            assert evt.data["max_retries"] == 3

    @pytest.mark.asyncio
    async def test_group_start_complete_events(self, context):
        """测试并行组开始和完成事件"""
        workflow = make_workflow(
            agent_names=["A", "B", "C"],
            connections=[("A", ["C"]), ("B", ["C"])],
            name="test_group_events",
        )
        agent_a = MockAgent("A", delay=0.05)
        agent_b = MockAgent("B", delay=0.05)
        agent_c = MockAgent("C")
        events = []
        scheduler = Scheduler(
            workflow, {"A": agent_a, "B": agent_b, "C": agent_c},
            on_event=self._collect_events(events),
        )
        await scheduler.run(context)

        group_starts = [e for e in events if e.event_type == SchedulerEventType.GROUP_START]
        group_completes = [e for e in events if e.event_type == SchedulerEventType.GROUP_COMPLETE]
        # (A,B) 并行 -> C 顺序，所以有 2 个组
        assert len(group_starts) == 2
        assert len(group_completes) == 2
        # 第一个组应该包含 A 和 B
        assert set(group_starts[0].data["agents"]) == {"A", "B"}
        # 第二个组应该只包含 C
        assert group_starts[1].data["agents"] == ["C"]

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_break_execution(self, context):
        """回调抛出异常不影响工作流执行"""
        workflow = make_workflow(agent_names=["A"], name="test_cb_exn")
        agent_a = MockAgent("A")

        def bad_callback(event: SchedulerEvent):
            raise RuntimeError("callback error")

        scheduler = Scheduler(workflow, {"A": agent_a}, on_event=bad_callback)
        result = await scheduler.run(context)
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_event_timestamp_is_datetime(self, context):
        """事件的 timestamp 字段是 datetime 类型"""
        from datetime import datetime as dt
        workflow = make_workflow(agent_names=["A"], name="test_ts")
        agent_a = MockAgent("A")
        events = []
        scheduler = Scheduler(workflow, {"A": agent_a}, on_event=self._collect_events(events))
        await scheduler.run(context)
        for e in events:
            assert isinstance(e.timestamp, dt)

    @pytest.mark.asyncio
    async def test_full_event_sequence(self, context):
        """测试完整事件序列顺序"""
        workflow = make_workflow(
            agent_names=["A", "B"],
            connections=[("A", ["B"])],
            name="test_full_seq",
        )
        agent_a = MockAgent("A")
        agent_b = MockAgent("B")
        events = []
        scheduler = Scheduler(workflow, {"A": agent_a, "B": agent_b}, on_event=self._collect_events(events))
        await scheduler.run(context)

        expected = [
            SchedulerEventType.WORKFLOW_START,
            SchedulerEventType.GROUP_START,
            SchedulerEventType.AGENT_START,
            SchedulerEventType.AGENT_COMPLETE,
            SchedulerEventType.GROUP_COMPLETE,
            SchedulerEventType.GROUP_START,
            SchedulerEventType.AGENT_START,
            SchedulerEventType.AGENT_COMPLETE,
            SchedulerEventType.GROUP_COMPLETE,
            SchedulerEventType.WORKFLOW_COMPLETE,
        ]
        actual = [e.event_type for e in events]
        assert actual == expected
