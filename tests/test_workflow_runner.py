"""
Tests for tui/workflow_runner.py

覆盖：
- WorkflowRunner 初始化
- 工作流文件解析
- Agent 创建（LLMAgent + ConditionAgent）
- 事件处理（REPLOutputHandler）
- 工作流执行（mock LLM 调用）
- 停止工作流
- 后台执行
- 错误处理
"""

import asyncio
import json
import tempfile
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from core.models import (
    AgentInstance,
    Component,
    Connection,
    ModelConfig,
    ParseResult,
    Workflow,
)
from core.scheduler import SchedulerEvent, SchedulerEventType
from core.execution import ExecutionRecord, ExecutionStatus
from core.context import WorkflowContext
from core.tool_registry import ToolRegistry, reset_default_registry

from tui.workflow_runner import ExecutionResult, REPLOutputHandler, WorkflowRunner


# ---------------------------------------------------------------------------
#  Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tool_registry():
    """Create a fresh tool registry for each test"""
    return ToolRegistry()


@pytest.fixture
def mock_config_manager():
    """Mock config manager"""
    cm = MagicMock()
    config = MagicMock()
    config.llm.default_model = "test-model"
    config.llm.default_provider = "test-provider"
    config.provider = {}
    cm.load_config.return_value = config
    return cm


@pytest.fixture
def output_handler():
    """Create an output handler (no Rich console for testing)"""
    handler = REPLOutputHandler(console=None)
    return handler


@pytest.fixture
def sample_gf_file(tmp_path):
    """Create a minimal .gf workflow file for testing"""
    content = """
workflow test_workflow {
  agent agent_a {
    prompt: "Do task A: {input}"
  }

  agent agent_b {
    prompt: "Do task B: {input}"
  }

  agent_a -> agent_b
}
"""
    gf_file = tmp_path / "test.gf"
    gf_file.write_text(content, encoding="utf-8")
    return str(gf_file)


@pytest.fixture
def parallel_gf_file(tmp_path):
    """Create a .gf workflow with parallel agents"""
    content = """
workflow parallel_test {
  agent p1 {
    prompt: "Parallel task 1: {input}"
  }

  agent p2 {
    prompt: "Parallel task 2: {input}"
  }

  agent merger {
    prompt: "Merge results: {input}"
  }

  (p1, p2) -> merger
}
"""
    gf_file = tmp_path / "parallel.gf"
    gf_file.write_text(content, encoding="utf-8")
    return str(gf_file)


@pytest.fixture
def condition_gf_file(tmp_path):
    """Create a .gf workflow with a condition agent"""
    content = """
workflow condition_test {
  agent classify {
    prompt: "Classify: {input}"
  }

  agent route {
    type: "condition"
    rules: ["fast", "slow"]
  }

  agent fast_handler {
    prompt: "Handle fast: {input}"
  }

  agent slow_handler {
    prompt: "Handle slow: {input}"
  }

  classify -> route -> [fast] fast_handler, [slow] slow_handler
}
"""
    gf_file = tmp_path / "condition.gf"
    gf_file.write_text(content, encoding="utf-8")
    return str(gf_file)


# ---------------------------------------------------------------------------
#  Mock LLM helper
# ---------------------------------------------------------------------------


def _make_mock_llm_client(response_text: str = '{"result": "ok"}'):
    """Create a mock LLM client that returns a fixed response"""
    client = AsyncMock()
    response = MagicMock()
    response.content = response_text
    response.model = "test-model"
    response.usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    response.finish_reason = "stop"
    response.tool_calls = None
    client.chat = AsyncMock(return_value=response)
    return client


# ---------------------------------------------------------------------------
#  Tests: ExecutionResult
# ---------------------------------------------------------------------------


class TestExecutionResult:
    def test_default_values(self):
        result = ExecutionResult(workflow_name="test", status="completed")
        assert result.workflow_name == "test"
        assert result.status == "completed"
        assert result.success is True
        assert result.error is None
        assert result.duration_ms is None

    def test_success_property(self):
        assert ExecutionResult(workflow_name="t", status="completed").success is True
        assert ExecutionResult(workflow_name="t", status="failed").success is False
        assert ExecutionResult(workflow_name="t", status="cancelled").success is False

    def test_duration_calculation(self):
        start = datetime(2024, 1, 1, 12, 0, 0)
        end = datetime(2024, 1, 1, 12, 0, 1)
        result = ExecutionResult(
            workflow_name="t",
            status="completed",
            started_at=start,
            completed_at=end,
        )
        assert result.duration_ms == 1000


# ---------------------------------------------------------------------------
#  Tests: REPLOutputHandler
# ---------------------------------------------------------------------------


class TestREPLOutputHandler:
    def test_init_without_rich(self):
        handler = REPLOutputHandler(console=None)
        # When console=None, _has_rich may be True or False depending on import
        # but handler should still work
        assert handler._total_agents == 0

    def test_set_total_agents(self):
        handler = REPLOutputHandler(console=None)
        handler.set_total_agents(5)
        assert handler._total_agents == 5
        assert handler._completed_agents == 0

    def test_progress_ratio_no_agents(self):
        handler = REPLOutputHandler(console=None)
        assert handler.progress_ratio == 0.0

    def test_progress_ratio_partial(self):
        handler = REPLOutputHandler(console=None)
        handler.set_total_agents(4)
        handler._completed_agents = 2
        assert handler.progress_ratio == 0.5

    def test_progress_ratio_complete(self):
        handler = REPLOutputHandler(console=None)
        handler.set_total_agents(3)
        handler._completed_agents = 2
        handler._failed_agents = 1
        assert handler.progress_ratio == 1.0

    def test_handle_workflow_start(self):
        handler = REPLOutputHandler(console=None)
        event = SchedulerEvent(
            event_type=SchedulerEventType.WORKFLOW_START,
            data={"workflow_name": "test_flow"},
        )
        # Should not raise
        handler.handle(event)

    def test_handle_workflow_complete(self):
        handler = REPLOutputHandler(console=None)
        handler.set_total_agents(2)
        handler._completed_agents = 2
        event = SchedulerEvent(event_type=SchedulerEventType.WORKFLOW_COMPLETE)
        handler.handle(event)

    def test_handle_workflow_failed(self):
        handler = REPLOutputHandler(console=None)
        event = SchedulerEvent(
            event_type=SchedulerEventType.WORKFLOW_FAILED,
            data={"error": "something broke"},
        )
        handler.handle(event)

    def test_handle_agent_start(self):
        handler = REPLOutputHandler(console=None)
        event = SchedulerEvent(
            event_type=SchedulerEventType.AGENT_START,
            agent_name="my_agent",
        )
        handler.handle(event)
        assert "my_agent" in handler._running_agents

    def test_handle_agent_complete(self):
        handler = REPLOutputHandler(console=None)
        handler.set_total_agents(2)
        event = SchedulerEvent(
            event_type=SchedulerEventType.AGENT_COMPLETE,
            agent_name="my_agent",
            data={"output": {}, "duration_ms": 150},
        )
        handler.handle(event)
        assert handler._completed_agents == 1
        assert "my_agent" not in handler._running_agents

    def test_handle_agent_fail(self):
        handler = REPLOutputHandler(console=None)
        handler.set_total_agents(2)
        event = SchedulerEvent(
            event_type=SchedulerEventType.AGENT_FAIL,
            agent_name="bad_agent",
            data={"error": "oops"},
        )
        handler.handle(event)
        assert handler._failed_agents == 1

    def test_handle_agent_retry(self):
        handler = REPLOutputHandler(console=None)
        event = SchedulerEvent(
            event_type=SchedulerEventType.AGENT_RETRY,
            agent_name="retry_agent",
            data={"attempt": 1, "max_retries": 3},
        )
        handler.handle(event)

    def test_handle_agent_skipped(self):
        handler = REPLOutputHandler(console=None)
        handler.set_total_agents(2)
        event = SchedulerEvent(
            event_type=SchedulerEventType.AGENT_SKIPPED,
            agent_name="skip_agent",
            data={"reason": "on_fail=skip"},
        )
        handler.handle(event)
        assert handler._completed_agents == 1

    def test_handle_unknown_event_no_error(self):
        """Handler should silently ignore unknown event types"""
        handler = REPLOutputHandler(console=None)
        # All event types are known, but the handler should not crash
        # even with minimal data
        event = SchedulerEvent(event_type=SchedulerEventType.GROUP_START, data={"agents": []})
        handler.handle(event)

    def test_handler_callback_exception_does_not_propagate(self):
        """If the handler's internal method raises, handle() should not propagate"""
        handler = REPLOutputHandler(console=None)
        # Force an error by making _on_workflow_start fail
        handler._on_workflow_start = lambda e: 1 / 0
        event = SchedulerEvent(
            event_type=SchedulerEventType.WORKFLOW_START,
            data={"workflow_name": "test"},
        )
        # Should not raise
        handler.handle(event)


# ---------------------------------------------------------------------------
#  Tests: WorkflowRunner initialization
# ---------------------------------------------------------------------------


class TestWorkflowRunnerInit:
    def test_default_init(self, tool_registry):
        runner = WorkflowRunner(tool_registry=tool_registry)
        assert runner.is_running is False
        assert runner.last_result is None
        assert runner.output_handler is not None

    def test_custom_output_handler(self, tool_registry):
        custom_handler = REPLOutputHandler()
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            output_handler=custom_handler,
        )
        assert runner.output_handler is custom_handler

    def test_custom_config_manager(self, tool_registry, mock_config_manager):
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )
        assert runner._config_manager is mock_config_manager


# ---------------------------------------------------------------------------
#  Tests: WorkflowRunner parsing
# ---------------------------------------------------------------------------


class TestWorkflowRunnerParsing:
    def test_parse_workflow_success(self, tool_registry, sample_gf_file, mock_config_manager):
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )
        workflow, components = runner._parse_workflow(sample_gf_file)
        assert isinstance(workflow, Workflow)
        assert workflow.name == "test_workflow"
        assert len(workflow.agents) == 2

    def test_parse_workflow_file_not_found(self, tool_registry, mock_config_manager):
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )
        with pytest.raises(FileNotFoundError):
            runner._parse_workflow("/nonexistent/path.gf")

    def test_resolve_model_provider(self, tool_registry, mock_config_manager):
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )
        model, provider = runner._resolve_model_provider(None, None)
        assert model == "test-model"
        assert provider == "test-provider"

    def test_resolve_model_provider_override(self, tool_registry, mock_config_manager):
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )
        model, provider = runner._resolve_model_provider("custom-model", "custom-provider")
        assert model == "custom-model"
        assert provider == "custom-provider"


# ---------------------------------------------------------------------------
#  Tests: WorkflowRunner agent creation
# ---------------------------------------------------------------------------


class TestWorkflowRunnerAgentCreation:
    def test_create_agents_llm(self, tool_registry, sample_gf_file, mock_config_manager):
        from core.llm_agent import LLMAgent

        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )
        workflow, components = runner._parse_workflow(sample_gf_file)

        with patch("tui.workflow_runner.LLMAgent") as mock_llm_cls:
            mock_llm_cls.return_value = MagicMock(spec=LLMAgent)
            agents = runner._create_agents(
                workflow, components, "test-model", "test-provider"
            )

        assert len(agents) == 2
        assert "agent_a" in agents
        assert "agent_b" in agents

    def test_create_agents_condition(self, tool_registry, condition_gf_file, mock_config_manager):
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )
        workflow, components = runner._parse_workflow(condition_gf_file)

        with patch("tui.workflow_runner.LLMAgent") as mock_llm_cls, \
             patch("tui.workflow_runner.ConditionAgent") as mock_cond_cls:
            mock_llm_cls.return_value = MagicMock()
            mock_cond_cls.return_value = MagicMock()
            agents = runner._create_agents(
                workflow, components, "test-model", "test-provider"
            )

        # route should be created as ConditionAgent
        mock_cond_cls.assert_called_once()
        # classify, fast_handler, slow_handler should be LLMAgent
        assert mock_llm_cls.call_count == 3

    def test_create_agents_with_permission_filter(self, tool_registry, mock_config_manager):
        """When a component has permission allow/deny, a filtered registry should be used"""
        from core.models import PermissionConfig

        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )

        workflow = Workflow(
            name="perm_test",
            agents=[
                AgentInstance(name="restricted_agent", component="restricted_agent"),
            ],
            connections=[],
        )
        component = Component(
            name="restricted_agent",
            model=ModelConfig(default="test-model"),
            permission=PermissionConfig(allow=["tool_a"]),
        )
        components_dict = {"restricted_agent": component}

        with patch("tui.workflow_runner.create_filtered_registry") as mock_filter, \
             patch("tui.workflow_runner.LLMAgent") as mock_llm_cls:
            mock_filter.return_value = ToolRegistry()
            mock_llm_cls.return_value = MagicMock()
            runner._create_agents(
                workflow, components_dict, "test-model", "test-provider"
            )

        mock_filter.assert_called_once()


# ---------------------------------------------------------------------------
#  Tests: WorkflowRunner.run_workflow
# ---------------------------------------------------------------------------


class TestWorkflowRunnerRunWorkflow:
    @pytest.mark.asyncio
    async def test_run_workflow_success(self, tool_registry, sample_gf_file, mock_config_manager):
        """Full run with mocked LLM calls"""
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )

        mock_client = _make_mock_llm_client('{"result": "done"}')

        with patch("tui.workflow_runner.register_builtin_tools"), \
             patch("tui.workflow_runner.LLMAgent") as mock_llm_cls:
            # Make the mock agent return a dict directly
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value={"result": "done"})
            mock_agent.execute = AsyncMock(return_value={"result": "done"})
            mock_agent.on_fail = "stop"
            mock_agent.retry_count = 1
            mock_llm_cls.return_value = mock_agent

            result = await runner.run_workflow(
                sample_gf_file,
                task="test task",
                input_params={"key": "value"},
            )

        assert isinstance(result, ExecutionResult)
        assert result.success is True
        assert result.workflow_name == "test_workflow"
        assert runner.is_running is False

    @pytest.mark.asyncio
    async def test_run_workflow_file_not_found(self, tool_registry, mock_config_manager):
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )
        with pytest.raises(FileNotFoundError):
            await runner.run_workflow("/nonexistent.gf")

    @pytest.mark.asyncio
    async def test_run_workflow_already_running(self, tool_registry, mock_config_manager):
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )
        runner._is_running = True
        with pytest.raises(RuntimeError, match="already running"):
            await runner.run_workflow("dummy.gf")

    @pytest.mark.asyncio
    async def test_run_workflow_with_task(self, tool_registry, sample_gf_file, mock_config_manager):
        """Task parameter should be injected into workflow input"""
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )

        with patch("tui.workflow_runner.register_builtin_tools"), \
             patch("tui.workflow_runner.LLMAgent") as mock_llm_cls, \
             patch.object(runner, "_parse_workflow") as mock_parse:
            mock_workflow = Workflow(
                name="test",
                agents=[AgentInstance(name="a")],
                connections=[],
            )
            mock_parse.return_value = (mock_workflow, {})

            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value={"result": "ok"})
            mock_agent.execute = AsyncMock(return_value={"result": "ok"})
            mock_agent.on_fail = "stop"
            mock_agent.retry_count = 1
            mock_llm_cls.return_value = mock_agent

            # Patch Scheduler.run to capture the input
            with patch("tui.workflow_runner.Scheduler") as mock_sched_cls:
                mock_scheduler = MagicMock()
                mock_record = ExecutionRecord(workflow_name="test")
                mock_record.start()
                mock_record.complete()
                mock_scheduler.run = AsyncMock(return_value=mock_record)
                mock_sched_cls.return_value = mock_scheduler

                result = await runner.run_workflow(
                    sample_gf_file, task="do something"
                )

                # Check that Scheduler was created with task in workflow_input
                call_kwargs = mock_sched_cls.call_args
                assert call_kwargs[1]["workflow_input"]["task"] == "do something"

    @pytest.mark.asyncio
    async def test_run_workflow_failure_records_error(
        self, tool_registry, sample_gf_file, mock_config_manager
    ):
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )

        with patch("tui.workflow_runner.register_builtin_tools"), \
             patch("tui.workflow_runner.LLMAgent") as mock_llm_cls:
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(side_effect=RuntimeError("LLM exploded"))
            mock_agent.execute = AsyncMock(side_effect=RuntimeError("LLM exploded"))
            mock_agent.on_fail = "stop"
            mock_agent.retry_count = 1
            mock_llm_cls.return_value = mock_agent

            with pytest.raises(RuntimeError, match="LLM exploded"):
                await runner.run_workflow(sample_gf_file)

        assert runner.last_result is not None
        assert runner.last_result.status == "failed"
        assert runner.is_running is False


# ---------------------------------------------------------------------------
#  Tests: WorkflowRunner.stop_workflow
# ---------------------------------------------------------------------------


class TestWorkflowRunnerStop:
    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, tool_registry, mock_config_manager):
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )
        # Should not raise
        await runner.stop_workflow()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, tool_registry, mock_config_manager):
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )

        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def slow_workflow():
            runner._is_running = True
            runner._current_scheduler = MagicMock()
            task = asyncio.current_task()
            runner._current_task = task
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(slow_workflow())
        await started.wait()

        assert runner.is_running is True

        await runner.stop_workflow()

        await asyncio.sleep(0.05)
        assert cancelled.is_set() or task.done()


# ---------------------------------------------------------------------------
#  Tests: WorkflowRunner.run_workflow_background
# ---------------------------------------------------------------------------


class TestWorkflowRunnerBackground:
    @pytest.mark.asyncio
    async def test_background_returns_task(self, tool_registry, sample_gf_file, mock_config_manager):
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )

        with patch("tui.workflow_runner.register_builtin_tools"), \
             patch("tui.workflow_runner.LLMAgent") as mock_llm_cls:
            mock_agent = MagicMock()
            mock_agent.run = AsyncMock(return_value={"result": "ok"})
            mock_agent.execute = AsyncMock(return_value={"result": "ok"})
            mock_agent.on_fail = "stop"
            mock_agent.retry_count = 1
            mock_llm_cls.return_value = mock_agent

            callback_results = []

            def on_complete(result):
                callback_results.append(result)

            task = runner.run_workflow_background(
                sample_gf_file, on_complete=on_complete
            )

            assert isinstance(task, asyncio.Task)
            result = await task
            assert result.success is True
            assert len(callback_results) == 1
            assert callback_results[0].success is True


# ---------------------------------------------------------------------------
#  Tests: component resolution
# ---------------------------------------------------------------------------


class TestComponentResolution:
    def test_resolve_inline_component(self, tool_registry, mock_config_manager):
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )
        agent_inst = AgentInstance(
            name="my_agent",
            overrides={"model": "custom-model"},
            inline_system_prompt="You are helpful.",
        )
        component = runner._resolve_component(
            agent_inst, {}, "default-model", "test-provider"
        )
        assert component.name == "my_agent"
        assert component.system_prompt == "You are helpful."

    def test_resolve_referenced_component(self, tool_registry, mock_config_manager):
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )
        ref_component = Component(
            name="base_agent",
            system_prompt="Base prompt",
            model=ModelConfig(default="base-model"),
        )
        components_dict = {"base_agent": ref_component}

        agent_inst = AgentInstance(
            name="instance",
            component="base_agent",
            overrides={"system_prompt": "Override prompt"},
        )
        result = runner._resolve_component(
            agent_inst, components_dict, "default-model", "test-provider"
        )
        assert result.system_prompt == "Override prompt"

    def test_resolve_component_model_override(self, tool_registry, mock_config_manager):
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )
        ref_component = Component(
            name="c",
            model=ModelConfig(default="old-model"),
        )
        agent_inst = AgentInstance(
            name="i",
            component="c",
            overrides={"model": "new-model"},
        )
        result = runner._resolve_component(
            agent_inst, {"c": ref_component}, "default-model", "test-provider"
        )
        assert result.model.default == "new-model"


# ---------------------------------------------------------------------------
#  Tests: parallel workflow execution
# ---------------------------------------------------------------------------


class TestParallelWorkflow:
    @pytest.mark.asyncio
    async def test_parallel_agents_execute(
        self, tool_registry, parallel_gf_file, mock_config_manager
    ):
        runner = WorkflowRunner(
            tool_registry=tool_registry,
            config_manager=mock_config_manager,
        )

        call_log = []

        def make_agent(name):
            agent = MagicMock()
            agent.on_fail = "stop"
            agent.retry_count = 1

            async def run_fn(input_data):
                call_log.append(name)
                return {name: "result"}

            async def exec_fn(input_data):
                call_log.append(name)
                return {name: "result"}

            agent.run = AsyncMock(side_effect=run_fn)
            agent.execute = AsyncMock(side_effect=exec_fn)
            return agent

        with patch("tui.workflow_runner.register_builtin_tools"), \
             patch("tui.workflow_runner.LLMAgent") as mock_llm_cls:
            mock_llm_cls.side_effect = lambda **kwargs: make_agent(
                kwargs.get("component", MagicMock()).name
            )

            result = await runner.run_workflow(parallel_gf_file)

        assert result.success is True
        # All 3 agents should have been called
        assert len(call_log) == 3
        assert "p1" in call_log
        assert "p2" in call_log
        assert "merger" in call_log
