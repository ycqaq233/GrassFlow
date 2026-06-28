"""
Stream 模式测试

测试内容：
- batch 模式行为不变
- stream + shared 模式累积状态
- stream + independent 模式隔离
- stream 模式错误处理（单次失败不中断后续触发）
- 多上游并行输出时的 stream 触发
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from core.models import Workflow, AgentInstance, Connection, Component, ModelConfig, Port
from core.context import WorkflowContext
from core.scheduler import Scheduler, SchedulerError, SchedulerEvent, SchedulerEventType
from core.execution import ExecutionStatus


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------

def make_workflow(
    agent_names: list[str] | None = None,
    connections: list[tuple[str, list[str]]] | None = None,
    routing: dict | None = None,
    name: str = "test",
    agent_instances: list[AgentInstance] | None = None,
) -> Workflow:
    """Build a v2 Workflow from concise specs."""
    if agent_instances is not None:
        agents = agent_instances
    else:
        agents = [AgentInstance(name=n) for n in (agent_names or [])]
    conns = [
        Connection(source_agent=src, target_agents=tgts)
        for src, tgts in (connections or [])
    ]
    if routing:
        for src, rules in routing.items():
            for conn in conns:
                if conn.source_agent == src:
                    conn.routing_rules = rules
    return Workflow(name=name, agents=agents, connections=conns)


class MockAgent:
    """模拟 Agent"""

    def __init__(self, name: str, fail: bool = False, delay: float = 0, output: dict | None = None):
        self.name = name
        self.fail = fail
        self.delay = delay
        self.executed = False
        self.input_data = None
        self.on_fail = "stop"
        self.retry_count = 3
        self.call_count = 0
        self._output = output

    async def run(self, input_data: dict) -> dict:
        """模拟执行"""
        self.executed = True
        self.input_data = input_data
        self.call_count += 1

        if self.delay > 0:
            await asyncio.sleep(self.delay)

        if self.fail:
            raise Exception(f"Agent {self.name} failed")

        if self._output is not None:
            return dict(self._output)

        return {"result": f"{self.name}_output"}


class StreamMockAgent:
    """Stream 模式的 Mock Agent，支持共享状态的累积"""

    def __init__(self, name: str, fail_indices: list[int] | None = None):
        self.name = name
        self.on_fail = "stop"
        self.retry_count = 3
        self.call_count = 0
        self.call_inputs: list = []
        self.fail_indices = fail_indices or []
        # shared 模式下的累积状态
        self._accumulated: list = []

    async def run(self, input_data: dict) -> dict:
        self.call_inputs.append(input_data)
        idx = self.call_count
        self.call_count += 1

        if idx in self.fail_indices:
            raise Exception(f"Agent {self.name} failed on item {idx}")

        item = input_data.get("_stream_item")
        self._accumulated.append(item)
        return {"item": item, "count": len(self._accumulated)}


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------

class TestBatchModeUnchanged:
    """batch 模式行为不变"""

    @pytest.fixture
    def context(self):
        return WorkflowContext()

    @pytest.mark.asyncio
    async def test_batch_mode_default(self, context):
        """默认模式（batch）行为不变：agent 只执行一次"""
        workflow = make_workflow(
            agent_names=["A", "B"],
            connections=[("A", ["B"])],
            name="test_batch_default",
        )

        agent_a = MockAgent("A", output={"items": [1, 2, 3]})
        agent_b = MockAgent("B")

        agents = {"A": agent_a, "B": agent_b}
        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        assert agent_a.call_count == 1
        assert agent_b.call_count == 1
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_batch_mode_parallel(self, context):
        """batch 模式并行执行：(A, B) -> C"""
        workflow = make_workflow(
            agent_names=["A", "B", "C"],
            connections=[("A", ["C"]), ("B", ["C"])],
            name="test_batch_parallel",
        )

        agent_a = MockAgent("A", delay=0.05)
        agent_b = MockAgent("B", delay=0.05)
        agent_c = MockAgent("C")

        agents = {"A": agent_a, "B": agent_b, "C": agent_c}
        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        assert agent_a.call_count == 1
        assert agent_b.call_count == 1
        assert agent_c.call_count == 1
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_batch_mode_explicit(self, context):
        """显式声明 mode=batch 的 AgentInstance 行为不变"""
        agent_instances = [
            AgentInstance(name="A"),
            AgentInstance(name="B", mode="batch"),
        ]
        workflow = Workflow(
            name="test_batch_explicit",
            agents=agent_instances,
            connections=[Connection(source_agent="A", target_agents=["B"])],
        )

        agent_a = MockAgent("A", output={"items": [1, 2, 3]})
        agent_b = MockAgent("B")

        agents = {"A": agent_a, "B": agent_b}
        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        assert agent_b.call_count == 1
        assert result.status == ExecutionStatus.COMPLETED


class TestStreamSharedAccumulates:
    """stream + shared 模式：复用同一实例，累积状态"""

    @pytest.fixture
    def context(self):
        return WorkflowContext()

    @pytest.mark.asyncio
    async def test_stream_shared_triggers_per_item(self, context):
        """stream agent 对每个上游数组项触发一次执行"""
        agent_instances = [
            AgentInstance(name="source"),
            AgentInstance(name="counter", mode="stream", context="shared"),
        ]
        workflow = Workflow(
            name="test_stream_shared",
            agents=agent_instances,
            connections=[Connection(source_agent="source", target_agents=["counter"])],
        )

        source = MockAgent("source", output={"items": ["apple", "banana", "cherry"]})
        counter = StreamMockAgent("counter")

        agents = {"source": source, "counter": counter}
        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        # source 执行 1 次，counter 执行 3 次
        assert source.call_count == 1
        assert counter.call_count == 3
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_stream_shared_receives_individual_items(self, context):
        """stream agent 每次接收一个单独的项"""
        agent_instances = [
            AgentInstance(name="source"),
            AgentInstance(name="counter", mode="stream", context="shared"),
        ]
        workflow = Workflow(
            name="test_stream_items",
            agents=agent_instances,
            connections=[Connection(source_agent="source", target_agents=["counter"])],
        )

        source = MockAgent("source", output={"items": ["apple", "banana", "cherry"]})
        counter = StreamMockAgent("counter")

        agents = {"source": source, "counter": counter}
        scheduler = Scheduler(workflow, agents)
        await scheduler.run(context)

        # 验证每次接收的 _stream_item
        received_items = [
            call.get("_stream_item") for call in counter.call_inputs
        ]
        assert received_items == ["apple", "banana", "cherry"]

    @pytest.mark.asyncio
    async def test_stream_shared_state_persists(self, context):
        """shared 模式下 agent 状态在多次触发间保持"""
        agent_instances = [
            AgentInstance(name="source"),
            AgentInstance(name="counter", mode="stream", context="shared"),
        ]
        workflow = Workflow(
            name="test_stream_state",
            agents=agent_instances,
            connections=[Connection(source_agent="source", target_agents=["counter"])],
        )

        source = MockAgent("source", output={"items": ["a", "b", "c"]})
        counter = StreamMockAgent("counter")

        agents = {"source": source, "counter": counter}
        scheduler = Scheduler(workflow, agents)
        await scheduler.run(context)

        # shared 模式：counter 的 _accumulated 跨触发保持
        assert counter._accumulated == ["a", "b", "c"]
        # 每次输出的 count 递增
        outputs = [call for call in counter.call_inputs]
        # 通过 counter.call_inputs 验证 _accumulated 增长
        assert counter.call_count == 3

    @pytest.mark.asyncio
    async def test_stream_context_stores_results_list(self, context):
        """stream agent 的结果以列表形式存储在 context 中"""
        agent_instances = [
            AgentInstance(name="source"),
            AgentInstance(name="counter", mode="stream", context="shared"),
        ]
        workflow = Workflow(
            name="test_stream_context",
            agents=agent_instances,
            connections=[Connection(source_agent="source", target_agents=["counter"])],
        )

        source = MockAgent("source", output={"items": ["x", "y"]})
        counter = StreamMockAgent("counter")

        agents = {"source": source, "counter": counter}
        scheduler = Scheduler(workflow, agents)
        await scheduler.run(context)

        # context 中存储的是结果列表
        stored = context.get("counter")
        assert isinstance(stored, list)
        assert len(stored) == 2
        assert stored[0]["item"] == "x"
        assert stored[1]["item"] == "y"


class TestStreamIndependentIsolated:
    """stream + independent 模式：每次执行创建新实例"""

    @pytest.fixture
    def context(self):
        return WorkflowContext()

    @pytest.mark.asyncio
    async def test_stream_independent_creates_new_instances(self, context):
        """independent 模式下每次触发使用独立实例"""
        agent_instances = [
            AgentInstance(name="source"),
            AgentInstance(name="processor", mode="stream", context="independent"),
        ]
        workflow = Workflow(
            name="test_stream_independent",
            agents=agent_instances,
            connections=[Connection(source_agent="source", target_agents=["processor"])],
        )

        source = MockAgent("source", output={"items": ["a", "b", "c"]})

        # 追踪每次创建的实例
        created_instances: list = []

        class TrackingAgent(StreamMockAgent):
            def __init__(self, name):
                super().__init__(name)
                created_instances.append(self)

        # 我们需要在 agents dict 中放一个模板实例
        # independent 模式下 scheduler 会 deepcopy
        template = TrackingAgent("processor")

        agents = {"source": source, "processor": template}
        scheduler = Scheduler(workflow, agents)
        await scheduler.run(context)

        # 3 个项触发 3 次，每次 deepcopy 创建新实例
        # 但 _accumulated 在每个新实例中从 0 开始
        # template 实例的 call_count 不变（因为用的是 deepcopy）
        # 注意：deepcopy 会复制 _accumulated，所以需要验证
        assert template.call_count == 0  # 原始模板未被调用

    @pytest.mark.asyncio
    async def test_stream_independent_accumulated_resets(self, context):
        """independent 模式下每个实例的累积状态独立"""
        agent_instances = [
            AgentInstance(name="source"),
            AgentInstance(name="processor", mode="stream", context="independent"),
        ]
        workflow = Workflow(
            name="test_stream_independent_reset",
            agents=agent_instances,
            connections=[Connection(source_agent="source", target_agents=["processor"])],
        )

        source = MockAgent("source", output={"items": ["a", "b", "c"]})

        # 用列表收集每次 deepcopy 后的调用结果
        call_results: list = []

        class RecordingAgent(StreamMockAgent):
            async def run(self, input_data: dict) -> dict:
                result = await super().run(input_data)
                call_results.append(dict(result))
                return result

        template = RecordingAgent("processor")
        agents = {"source": source, "processor": template}
        scheduler = Scheduler(workflow, agents)
        await scheduler.run(context)

        # 每次 deepcopy 创建新实例，_accumulated 从模板复制
        # 但由于 deepcopy，每个新实例的 _accumulated 是独立的
        # 注意：deepcopy 会复制当前的 _accumulated 状态
        # 第一次 deepcopy: _accumulated=[] -> run("a") -> _accumulated=["a"]
        # 第二次 deepcopy: 复制模板(仍为[]) -> run("b") -> _accumulated=["b"]
        # 第三次 deepcopy: 复制模板(仍为[]) -> run("c") -> _accumulated=["c"]
        assert len(call_results) == 3
        # 每个结果的 count 都是 1（因为独立实例各自只执行一次）
        for r in call_results:
            assert r["count"] == 1


class TestStreamErrorContinues:
    """stream 模式错误处理：单次失败不中断后续触发（on_fail=skip）"""

    @pytest.fixture
    def context(self):
        return WorkflowContext()

    @pytest.mark.asyncio
    async def test_stream_error_stop_stops_workflow(self, context):
        """on_fail=stop 时，stream agent 单次失败中断整个工作流"""
        agent_instances = [
            AgentInstance(name="source"),
            AgentInstance(name="processor", mode="stream", context="shared"),
        ]
        workflow = Workflow(
            name="test_stream_error_stop",
            agents=agent_instances,
            connections=[Connection(source_agent="source", target_agents=["processor"])],
        )

        source = MockAgent("source", output={"items": ["a", "b", "c"]})
        # 第 0 项失败
        processor = StreamMockAgent("processor", fail_indices=[0])
        processor.on_fail = "stop"

        agents = {"source": source, "processor": processor}
        scheduler = Scheduler(workflow, agents)

        with pytest.raises(SchedulerError):
            await scheduler.run(context)

        # 第 0 项失败后就停止了
        assert processor.call_count == 1

    @pytest.mark.asyncio
    async def test_stream_error_skip_continues(self, context):
        """on_fail=skip 时，stream agent 单次失败不中断后续触发"""
        agent_instances = [
            AgentInstance(name="source"),
            AgentInstance(name="processor", mode="stream", context="shared"),
        ]
        workflow = Workflow(
            name="test_stream_error_skip",
            agents=agent_instances,
            connections=[Connection(source_agent="source", target_agents=["processor"])],
        )

        source = MockAgent("source", output={"items": ["a", "b", "c"]})
        # 第 1 项失败
        processor = StreamMockAgent("processor", fail_indices=[1])
        processor.on_fail = "skip"

        agents = {"source": source, "processor": processor}
        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        # 第 1 项失败被跳过，但第 0 和第 2 项正常执行
        assert processor.call_count == 3
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_stream_error_skip_results_partial(self, context):
        """on_fail=skip 时，失败项不出现在结果列表中"""
        agent_instances = [
            AgentInstance(name="source"),
            AgentInstance(name="processor", mode="stream", context="shared"),
        ]
        workflow = Workflow(
            name="test_stream_partial",
            agents=agent_instances,
            connections=[Connection(source_agent="source", target_agents=["processor"])],
        )

        source = MockAgent("source", output={"items": ["a", "b", "c"]})
        # 第 1 项失败
        processor = StreamMockAgent("processor", fail_indices=[1])
        processor.on_fail = "skip"

        agents = {"source": source, "processor": processor}
        scheduler = Scheduler(workflow, agents)
        await scheduler.run(context)

        # context 中的结果列表只包含成功的项
        stored = context.get("processor")
        assert isinstance(stored, list)
        assert len(stored) == 2  # "a" 和 "c" 成功
        assert stored[0]["item"] == "a"
        assert stored[1]["item"] == "c"


class TestStreamWithParallelUpstream:
    """多个上游并行输出时的 stream 触发"""

    @pytest.fixture
    def context(self):
        return WorkflowContext()

    @pytest.mark.asyncio
    async def test_stream_with_parallel_upstream(self, context):
        """多个上游并行完成后，stream agent 处理所有上游的数组输出"""
        agent_instances = [
            AgentInstance(name="source_a"),
            AgentInstance(name="source_b"),
            AgentInstance(name="collector", mode="stream", context="shared"),
        ]
        workflow = Workflow(
            name="test_stream_parallel_upstream",
            agents=agent_instances,
            connections=[
                Connection(source_agent="source_a", target_agents=["collector"]),
                Connection(source_agent="source_b", target_agents=["collector"]),
            ],
        )

        source_a = MockAgent("source_a", output={"items": ["a1", "a2"]})
        source_b = MockAgent("source_b", output={"items": ["b1", "b2"]})
        collector = StreamMockAgent("collector")

        agents = {"source_a": source_a, "source_b": source_b, "collector": collector}
        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        # 两个上游各有 2 项，总共触发 4 次
        assert source_a.call_count == 1
        assert source_b.call_count == 1
        assert collector.call_count == 4
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_stream_with_mixed_upstream(self, context):
        """上游有数组和非数组输出时，只处理数组项"""
        agent_instances = [
            AgentInstance(name="array_source"),
            AgentInstance(name="scalar_source"),
            AgentInstance(name="collector", mode="stream", context="shared"),
        ]
        workflow = Workflow(
            name="test_stream_mixed",
            agents=agent_instances,
            connections=[
                Connection(source_agent="array_source", target_agents=["collector"]),
                Connection(source_agent="scalar_source", target_agents=["collector"]),
            ],
        )

        array_source = MockAgent("array_source", output={"items": ["x", "y"]})
        scalar_source = MockAgent("scalar_source", output={"value": "single"})
        collector = StreamMockAgent("collector")

        agents = {
            "array_source": array_source,
            "scalar_source": scalar_source,
            "collector": collector,
        }
        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        # 只有 array_source 的 items 被处理（2 项）
        assert collector.call_count == 2
        assert result.status == ExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_stream_no_array_falls_back_to_single(self, context):
        """上游没有数组输出时，stream agent 回退到单次 batch 执行"""
        agent_instances = [
            AgentInstance(name="source"),
            AgentInstance(name="processor", mode="stream", context="shared"),
        ]
        workflow = Workflow(
            name="test_stream_fallback",
            agents=agent_instances,
            connections=[Connection(source_agent="source", target_agents=["processor"])],
        )

        source = MockAgent("source", output={"value": "no_array"})
        processor = MockAgent("processor")

        agents = {"source": source, "processor": processor}
        scheduler = Scheduler(workflow, agents)
        result = await scheduler.run(context)

        # 无数组项，回退到单次执行
        assert processor.call_count == 1
        assert result.status == ExecutionStatus.COMPLETED


class TestStreamEventCallbacks:
    """Stream 模式的事件回调"""

    @pytest.fixture
    def context(self):
        return WorkflowContext()

    @pytest.mark.asyncio
    async def test_stream_emits_events_per_item(self, context):
        """stream agent 每个项触发 AGENT_START 和 AGENT_COMPLETE 事件"""
        agent_instances = [
            AgentInstance(name="source"),
            AgentInstance(name="counter", mode="stream", context="shared"),
        ]
        workflow = Workflow(
            name="test_stream_events",
            agents=agent_instances,
            connections=[Connection(source_agent="source", target_agents=["counter"])],
        )

        source = MockAgent("source", output={"items": ["a", "b"]})
        counter = StreamMockAgent("counter")

        events: list = []
        def on_event(event: SchedulerEvent):
            events.append(event)

        agents = {"source": source, "counter": counter}
        scheduler = Scheduler(workflow, agents, on_event=on_event)
        await scheduler.run(context)

        # stream agent 触发 2 次，每次有 AGENT_START + AGENT_COMPLETE
        agent_starts = [e for e in events if e.event_type == SchedulerEventType.AGENT_START and e.agent_name == "counter"]
        agent_completes = [e for e in events if e.event_type == SchedulerEventType.AGENT_COMPLETE and e.agent_name == "counter"]

        assert len(agent_starts) == 2
        assert len(agent_completes) == 2

        # 事件数据中包含 stream_item
        assert agent_starts[0].data["stream_item"] == "a"
        assert agent_starts[1].data["stream_item"] == "b"

    @pytest.mark.asyncio
    async def test_stream_error_emits_fail_event(self, context):
        """stream agent 失败时发射 AGENT_FAIL 事件"""
        agent_instances = [
            AgentInstance(name="source"),
            AgentInstance(name="processor", mode="stream", context="shared"),
        ]
        workflow = Workflow(
            name="test_stream_fail_event",
            agents=agent_instances,
            connections=[Connection(source_agent="source", target_agents=["processor"])],
        )

        source = MockAgent("source", output={"items": ["a", "b", "c"]})
        processor = StreamMockAgent("processor", fail_indices=[1])
        processor.on_fail = "skip"

        events: list = []
        def on_event(event: SchedulerEvent):
            events.append(event)

        agents = {"source": source, "processor": processor}
        scheduler = Scheduler(workflow, agents, on_event=on_event)
        await scheduler.run(context)

        fail_events = [e for e in events if e.event_type == SchedulerEventType.AGENT_FAIL and e.agent_name == "processor"]
        assert len(fail_events) == 1
        assert fail_events[0].data["stream_item"] == "b"


class TestGetStreamItems:
    """_get_stream_items 静态方法测试"""

    def test_extracts_arrays_from_single_upstream(self):
        """从单个上游输出中提取数组"""
        upstream = {"source": {"items": [1, 2, 3]}}
        result = Scheduler._get_stream_items(upstream)
        assert result == [1, 2, 3]

    def test_extracts_arrays_from_multiple_upstreams(self):
        """从多个上游输出中提取数组"""
        upstream = {
            "src_a": {"items": [1, 2]},
            "src_b": {"data": [3, 4]},
        }
        result = Scheduler._get_stream_items(upstream)
        assert result == [1, 2, 3, 4]

    def test_ignores_non_array_values(self):
        """忽略非数组值"""
        upstream = {"source": {"value": "string", "count": 42, "items": [1]}}
        result = Scheduler._get_stream_items(upstream)
        assert result == [1]

    def test_empty_upstream_returns_empty(self):
        """空上游返回空列表"""
        upstream = {}
        result = Scheduler._get_stream_items(upstream)
        assert result == []

    def test_no_arrays_returns_empty(self):
        """没有数组值时返回空列表"""
        upstream = {"source": {"value": "string", "count": 42}}
        result = Scheduler._get_stream_items(upstream)
        assert result == []
