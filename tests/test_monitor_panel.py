"""
monitor_panel 测试

测试内容：
- MonitorPanel 事件驱动的状态更新
- register_scheduler 回调注册
- 连接线状态转换
- 进度计算与数据收集
- 嵌入/全屏模式渲染
"""

import asyncio
import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock

from core.models import Workflow, AgentInstance, Connection
from core.execution import ExecutionRecord, ExecutionStatus
from core.context import WorkflowContext
from core.scheduler import Scheduler, SchedulerEvent, SchedulerEventType
from tui.monitor_panel import (
    MonitorPanel,
    MonitorState,
    AgentStatus,
    ConnectionStatus,
    execute_with_monitor,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def panel():
    return MonitorPanel()


@pytest.fixture
def simple_workflow():
    """A -> B 简单顺序工作流"""
    return Workflow(
        name="test_workflow",
        agents=[
            AgentInstance(name="A"),
            AgentInstance(name="B"),
        ],
        connections=[
            Connection(source_agent="A", target_agents=["B"]),
        ],
    )


@pytest.fixture
def parallel_workflow():
    """(A, B) -> C 并行工作流"""
    return Workflow(
        name="parallel_workflow",
        agents=[
            AgentInstance(name="A"),
            AgentInstance(name="B"),
            AgentInstance(name="C"),
        ],
        connections=[
            Connection(source_agent="A", target_agents=["C"]),
            Connection(source_agent="B", target_agents=["C"]),
        ],
    )


@pytest.fixture
def state(simple_workflow, panel):
    return panel.create_state(simple_workflow)


# ---------------------------------------------------------------------------
# create_state 测试
# ---------------------------------------------------------------------------

class TestCreateState:
    def test_creates_agent_statuses(self, panel, simple_workflow):
        state = panel.create_state(simple_workflow)
        assert "A" in state.agents
        assert "B" in state.agents
        assert state.total_agents == 2
        assert state.pending_agents == 2

    def test_creates_connections(self, panel, simple_workflow):
        state = panel.create_state(simple_workflow)
        assert len(state.connections) == 1
        assert state.connections[0].source == "A"
        assert state.connections[0].target == "B"
        assert state.connections[0].status == "pending"

    def test_parallel_workflow_connections(self, panel, parallel_workflow):
        state = panel.create_state(parallel_workflow)
        assert len(state.connections) == 2
        sources = {c.source for c in state.connections}
        assert sources == {"A", "B"}

    def test_initial_state_is_running(self, panel, simple_workflow):
        state = panel.create_state(simple_workflow)
        assert state.is_running is True
        assert state.is_failed is False


# ---------------------------------------------------------------------------
# on_event 测试
# ---------------------------------------------------------------------------

class TestOnEvent:
    def test_workflow_start(self, panel, state):
        event = SchedulerEvent(
            event_type=SchedulerEventType.WORKFLOW_START,
            data={"workflow_name": "test"},
        )
        panel.on_event(event, state)
        assert state.is_running is True
        assert any("started" in log for log in state.logs)

    def test_workflow_complete(self, panel, state):
        event = SchedulerEvent(event_type=SchedulerEventType.WORKFLOW_COMPLETE)
        panel.on_event(event, state)
        assert state.is_running is False
        assert state.is_failed is False
        assert any("completed" in log.lower() for log in state.logs)

    def test_workflow_failed(self, panel, state):
        event = SchedulerEvent(
            event_type=SchedulerEventType.WORKFLOW_FAILED,
            data={"error": "boom"},
        )
        panel.on_event(event, state)
        assert state.is_running is False
        assert state.is_failed is True
        assert state.error == "boom"

    def test_agent_start(self, panel, state):
        event = SchedulerEvent(
            event_type=SchedulerEventType.AGENT_START,
            agent_name="A",
        )
        panel.on_event(event, state)
        assert state.agents["A"].status == "running"
        assert state.running_agents == 1
        assert state.pending_agents == 1  # 2 - 1

    def test_agent_complete(self, panel, state):
        # 先启动
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_START, agent_name="A",
        ), state)
        # 再完成
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_COMPLETE,
            agent_name="A",
            data={"output": {"result": "ok"}, "duration_ms": 150},
        ), state)
        assert state.agents["A"].status == "completed"
        assert state.agents["A"].duration_ms == 150
        assert state.agents["A"].output_preview is not None
        assert state.completed_agents == 1
        assert state.running_agents == 0

    def test_agent_fail(self, panel, state):
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_START, agent_name="A",
        ), state)
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_FAIL,
            agent_name="A",
            data={"error": "timeout", "duration_ms": 5000},
        ), state)
        assert state.agents["A"].status == "failed"
        assert state.agents["A"].error == "timeout"
        assert state.failed_agents == 1

    def test_agent_retry(self, panel, state):
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_RETRY,
            agent_name="A",
            data={"attempt": 2, "max_retries": 3},
        ), state)
        assert state.agents["A"].status == "retrying"
        assert state.agents["A"].retry_attempt == 2
        assert state.agents["A"].max_retries == 3

    def test_agent_skipped(self, panel, state):
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_SKIPPED,
            agent_name="A",
        ), state)
        assert state.agents["A"].status == "skipped"
        assert state.skipped_agents == 1

    def test_group_start(self, panel, state):
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.GROUP_START,
            data={"agents": ["A", "B"]},
        ), state)
        assert any("Group started" in log for log in state.logs)

    def test_unknown_agent_ignored(self, panel, state):
        """对不存在的 agent 名称不应崩溃"""
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_START,
            agent_name="nonexistent",
        ), state)
        # 不抛异常即可


# ---------------------------------------------------------------------------
# 连接线状态测试
# ---------------------------------------------------------------------------

class TestConnectionStatus:
    def test_activate_incoming_on_agent_start(self, panel, state):
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_START, agent_name="B",
        ), state)
        # A->B 连接应变为 active
        assert state.connections[0].status == "active"

    def test_complete_outgoing_on_agent_complete(self, panel, state):
        # 先激活 B 的入边
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_START, agent_name="B",
        ), state)
        # A 完成，A->B 连接应变为 completed
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_START, agent_name="A",
        ), state)
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_COMPLETE,
            agent_name="A",
            data={"output": {}, "duration_ms": 100},
        ), state)
        # 找到 A 的出边
        a_conns = [c for c in state.connections if c.source == "A"]
        assert any(c.status == "completed" for c in a_conns)

    def test_fail_outgoing_on_agent_fail(self, panel, state):
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_START, agent_name="B",
        ), state)
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_FAIL,
            agent_name="A",
            data={"error": "crash"},
        ), state)
        a_conns = [c for c in state.connections if c.source == "A"]
        assert any(c.status == "failed" for c in a_conns)


# ---------------------------------------------------------------------------
# register_scheduler 测试
# ---------------------------------------------------------------------------

class TestRegisterScheduler:
    def test_callback_invoked(self, panel, simple_workflow):
        state = panel.create_state(simple_workflow)

        # 创建 mock scheduler
        scheduler = MagicMock(spec=Scheduler)
        scheduler._on_event = None

        panel.register_scheduler(scheduler, state)
        assert scheduler._on_event is not None

        # 模拟事件触发
        scheduler._on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_START, agent_name="A",
        ))
        assert state.agents["A"].status == "running"

    def test_chains_existing_callback(self, panel, simple_workflow):
        """如果 scheduler 已有回调，应链式调用"""
        state = panel.create_state(simple_workflow)
        scheduler = MagicMock(spec=Scheduler)

        called = []
        scheduler._on_event = lambda e: called.append(e)

        panel.register_scheduler(scheduler, state)

        event = SchedulerEvent(event_type=SchedulerEventType.AGENT_START, agent_name="A")
        scheduler._on_event(event)

        assert len(called) == 1
        assert state.agents["A"].status == "running"


# ---------------------------------------------------------------------------
# 进度与数据收集测试
# ---------------------------------------------------------------------------

class TestDataCollection:
    def test_get_progress_empty(self, panel, simple_workflow):
        state = panel.create_state(simple_workflow)
        assert panel.get_progress(state) == 0.0

    def test_get_progress_partial(self, panel, simple_workflow):
        state = panel.create_state(simple_workflow)
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_COMPLETE,
            agent_name="A",
            data={"output": {}, "duration_ms": 100},
        ), state)
        assert panel.get_progress(state) == pytest.approx(0.5)

    def test_get_progress_with_skip(self, panel, simple_workflow):
        state = panel.create_state(simple_workflow)
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_COMPLETE,
            agent_name="A",
            data={"output": {}, "duration_ms": 100},
        ), state)
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_SKIPPED,
            agent_name="B",
        ), state)
        assert panel.get_progress(state) == pytest.approx(1.0)

    def test_get_timeline(self, panel, simple_workflow):
        state = panel.create_state(simple_workflow)
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_START, agent_name="A",
        ), state)
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_COMPLETE,
            agent_name="A",
            data={"output": {}, "duration_ms": 50},
        ), state)
        timeline = panel.get_timeline(state)
        assert len(timeline) == 2
        a_event = next(e for e in timeline if e["agent"] == "A")
        assert a_event["status"] == "completed"
        assert a_event["duration_ms"] == 50

    def test_get_data_summary(self, panel, simple_workflow):
        state = panel.create_state(simple_workflow)
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_COMPLETE,
            agent_name="A",
            data={"output": {"key": "value"}, "duration_ms": 50},
        ), state)
        summary = panel.get_data_summary(state)
        assert "A" in summary
        assert summary["A"]["output"] != ""


# ---------------------------------------------------------------------------
# 渲染测试
# ---------------------------------------------------------------------------

class TestRendering:
    def test_render_returns_layout(self, panel, simple_workflow):
        """render() 应返回 Rich Layout 对象"""
        state = panel.create_state(simple_workflow)
        result = panel.render(state)
        assert result is not None
        # Rich Layout 对象有 name 属性
        assert hasattr(result, 'split')

    def test_render_compact_returns_layout(self, panel, simple_workflow):
        state = panel.create_state(simple_workflow)
        result = panel.render_compact(state)
        assert result is not None
        assert hasattr(result, 'split')

    def test_render_plain_fallback(self, simple_workflow):
        """无 Rich 时应返回纯文本"""
        panel = MonitorPanel(console=None)
        # 模拟无 Rich
        import tui.monitor_panel as mod
        orig = mod.HAS_RICH
        mod.HAS_RICH = False
        try:
            state = panel.create_state(simple_workflow)
            result = panel.render(state)
            assert isinstance(result, str)
            assert "test_workflow" in result
        finally:
            mod.HAS_RICH = orig


# ---------------------------------------------------------------------------
# 计数器一致性测试
# ---------------------------------------------------------------------------

class TestCounterConsistency:
    def test_counters_after_full_lifecycle(self, panel, simple_workflow):
        state = panel.create_state(simple_workflow)
        # A: pending -> running -> completed
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_START, agent_name="A",
        ), state)
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_COMPLETE,
            agent_name="A",
            data={"output": {}, "duration_ms": 50},
        ), state)
        # B: pending -> running -> failed
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_START, agent_name="B",
        ), state)
        panel.on_event(SchedulerEvent(
            event_type=SchedulerEventType.AGENT_FAIL,
            agent_name="B",
            data={"error": "err"},
        ), state)

        assert state.completed_agents == 1
        assert state.failed_agents == 1
        assert state.running_agents == 0
        assert state.pending_agents == 0

    def test_total_invariant(self, panel, simple_workflow):
        """任何时刻 completed + failed + running + pending + skipped == total"""
        state = panel.create_state(simple_workflow)

        events = [
            SchedulerEvent(event_type=SchedulerEventType.AGENT_START, agent_name="A"),
            SchedulerEvent(event_type=SchedulerEventType.AGENT_START, agent_name="B"),
            SchedulerEvent(event_type=SchedulerEventType.AGENT_COMPLETE,
                           agent_name="A", data={"output": {}, "duration_ms": 50}),
            SchedulerEvent(event_type=SchedulerEventType.AGENT_FAIL,
                           agent_name="B", data={"error": "err"}),
        ]
        for event in events:
            panel.on_event(event, state)
            total = (state.completed_agents + state.failed_agents +
                     state.running_agents + state.pending_agents +
                     state.skipped_agents)
            assert total == state.total_agents, (
                f"Counter invariant violated after {event.event_type}: "
                f"{total} != {state.total_agents}"
            )


# ---------------------------------------------------------------------------
# execute_with_monitor 便捷函数测试
# ---------------------------------------------------------------------------

class TestExecuteWithMonitor:
    def test_returns_execution_record(self, simple_workflow):
        """execute_with_monitor 应返回 ExecutionRecord"""
        # 创建 mock agent
        mock_agent = AsyncMock()
        mock_agent.execute = AsyncMock(return_value={"result": "ok"})

        scheduler = Scheduler(
            workflow=simple_workflow,
            agents={"A": mock_agent, "B": mock_agent},
        )
        context = WorkflowContext()

        result = execute_with_monitor(scheduler, context, simple_workflow)
        assert isinstance(result, ExecutionRecord)

    def test_runs_without_rich(self, simple_workflow):
        """无 Rich 时应降级执行"""
        import tui.monitor_panel as mod
        orig = mod.HAS_RICH
        mod.HAS_RICH = False
        try:
            mock_agent = AsyncMock()
            mock_agent.execute = AsyncMock(return_value={"result": "ok"})

            scheduler = Scheduler(
                workflow=simple_workflow,
                agents={"A": mock_agent, "B": mock_agent},
            )
            context = WorkflowContext()

            result = execute_with_monitor(scheduler, context, simple_workflow)
            assert isinstance(result, ExecutionRecord)
        finally:
            mod.HAS_RICH = orig


# ---------------------------------------------------------------------------
# AgentStatus 辅助方法测试
# ---------------------------------------------------------------------------

class TestAgentStatusHelpers:
    def test_status_style_known(self):
        for status in ("pending", "running", "completed", "failed", "skipped", "retrying"):
            style, icon = MonitorPanel._status_style(status)
            assert style  # non-empty
            assert icon   # non-empty

    def test_status_style_unknown(self):
        style, icon = MonitorPanel._status_style("unknown")
        assert style == "white"

    def test_connection_style_known(self):
        for status in ("pending", "active", "completed", "failed"):
            icon, style = MonitorPanel._connection_style(status)
            assert icon
            assert style

    def test_format_duration_ms(self):
        agent = AgentStatus(name="A", duration_ms=150)
        assert MonitorPanel._format_duration(agent) == "150ms"

    def test_format_duration_seconds(self):
        agent = AgentStatus(name="A", duration_ms=2500)
        assert MonitorPanel._format_duration(agent) == "2.5s"

    def test_format_duration_running(self):
        agent = AgentStatus(name="A", status="running",
                            started_at=datetime.now())
        result = MonitorPanel._format_duration(agent)
        assert result.endswith("s...")

    def test_format_duration_pending(self):
        agent = AgentStatus(name="A")
        assert MonitorPanel._format_duration(agent) == "..."

    def test_build_detail_with_error(self):
        agent = AgentStatus(name="A", error="something broke")
        detail = MonitorPanel._build_detail(agent)
        assert "something broke" in detail

    def test_build_detail_with_output(self):
        agent = AgentStatus(name="A", output_preview="result data")
        detail = MonitorPanel._build_detail(agent)
        assert "result data" in detail

    def test_build_detail_with_retry(self):
        agent = AgentStatus(name="A", retry_attempt=2, max_retries=3)
        detail = MonitorPanel._build_detail(agent)
        assert "retry 2/3" in detail

    def test_build_detail_empty(self):
        agent = AgentStatus(name="A")
        assert MonitorPanel._build_detail(agent) == ""
