"""
GrassFlow REPL 内工作流执行引擎

在 REPL 会话中提供工作流执行能力，对齐 tui/cli.py 的 run_cmd 逻辑，
但面向 REPL 环境：异步执行、事件驱动输出、可取消。

主要组件：
- WorkflowRunner: 工作流执行引擎
- REPLOutputHandler: SchedulerEvent -> Rich 输出格式化
"""

import asyncio
import copy
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.context import WorkflowContext
from core.execution import ExecutionRecord, ExecutionStatus
from core.models import AgentInstance, Component, ModelConfig, Workflow
from core.scheduler import Scheduler, SchedulerEvent, SchedulerEventType
from core.condition import ConditionAgent
from core.llm_agent import LLMAgent
from core.tool_registry import (
    ToolRegistry,
    create_filtered_registry,
    register_builtin_tools,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  执行结果
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """工作流执行结果，封装 ExecutionRecord 附加上下文信息"""

    workflow_name: str
    status: str  # "completed" | "failed" | "cancelled"
    execution_record: Optional[ExecutionRecord] = None
    error: Optional[str] = None
    context_data: Dict[str, Any] = field(default_factory=dict)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def duration_ms(self) -> Optional[int]:
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds() * 1000)
        return None

    @property
    def success(self) -> bool:
        return self.status == "completed"


# ---------------------------------------------------------------------------
#  REPLOutputHandler
# ---------------------------------------------------------------------------


class REPLOutputHandler:
    """接收 SchedulerEvent，格式化为输出到 REPL。

    支持两种输出模式：
    1. output_fn 回调模式（推荐）— 通过回调函数输出纯文本，无 ANSI 码
    2. Rich Console 模式（降级）— 直接打印到 stdout，含 ANSI 码
    """

    def __init__(self, console=None, output_fn=None):
        """
        Args:
            console: Rich Console 实例。为 None 时自动创建。
            output_fn: 输出回调函数 (text: str) -> None。
                       提供时优先使用此模式，输出纯文本。
        """
        self._output_fn = output_fn
        try:
            from rich.console import Console as _Console
            self._console = console or _Console()
            self._has_rich = True
        except ImportError:
            self._console = None
            self._has_rich = False

        # 进度追踪
        self._total_agents: int = 0
        self._completed_agents: int = 0
        self._failed_agents: int = 0
        self._running_agents: Dict[str, datetime] = {}

    def _print(self, text: str, rich_text: str = "") -> None:
        """输出文本。优先使用 output_fn（纯文本），降级到 Rich Console。"""
        if self._output_fn:
            # 使用回调模式：输出纯文本（去除 Rich 标记）
            import re
            clean = re.sub(r'\[/?[^\]]+\]', '', rich_text or text)
            self._output_fn(clean)
        elif self._has_rich and self._console:
            self._console.print(rich_text or text)
        else:
            print(text)

    def set_total_agents(self, count: int) -> None:
        """设置总 Agent 数量，用于进度计算"""
        self._total_agents = count
        self._completed_agents = 0
        self._failed_agents = 0

    @property
    def progress_ratio(self) -> float:
        done = self._completed_agents + self._failed_agents
        return done / max(self._total_agents, 1)

    def handle(self, event: SchedulerEvent) -> None:
        """调度器事件回调入口"""
        handler = {
            SchedulerEventType.WORKFLOW_START: self._on_workflow_start,
            SchedulerEventType.WORKFLOW_COMPLETE: self._on_workflow_complete,
            SchedulerEventType.WORKFLOW_FAILED: self._on_workflow_failed,
            SchedulerEventType.GROUP_START: self._on_group_start,
            SchedulerEventType.GROUP_COMPLETE: self._on_group_complete,
            SchedulerEventType.AGENT_START: self._on_agent_start,
            SchedulerEventType.AGENT_COMPLETE: self._on_agent_complete,
            SchedulerEventType.AGENT_FAIL: self._on_agent_fail,
            SchedulerEventType.AGENT_RETRY: self._on_agent_retry,
            SchedulerEventType.AGENT_SKIPPED: self._on_agent_skipped,
        }.get(event.event_type)

        if handler:
            try:
                handler(event)
            except Exception:
                logger.debug("Output handler error for %s", event.event_type, exc_info=True)

    # ---- 事件处理器 ----

    def _on_workflow_start(self, event: SchedulerEvent) -> None:
        name = event.data.get("workflow_name", "unknown") if event.data else "unknown"
        self._print(f"\nExecuting workflow: {name}",
                    f"\n[bold green]Executing workflow:[/bold green] {name}")
        if self._total_agents > 0:
            self._print(f"Agents: {self._total_agents}",
                        f"[dim]Agents: {self._total_agents}[/dim]")
        self._print("")

    def _on_workflow_complete(self, event: SchedulerEvent) -> None:
        self._print("\nWorkflow completed successfully!",
                    "\n[bold green]Workflow completed successfully![/bold green]")
        self._render_progress_bar()

    def _on_workflow_failed(self, event: SchedulerEvent) -> None:
        error = event.data.get("error", "unknown") if event.data else "unknown"
        self._print(f"\nWorkflow failed: {error}",
                    f"\n[bold red]Workflow failed:[/bold red] {error}")

    def _on_group_start(self, event: SchedulerEvent) -> None:
        agents = event.data.get("agents", []) if event.data else []
        if len(agents) > 1:
            self._print(f"--- Parallel group: {', '.join(agents)} ---",
                        f"[dim]--- Parallel group: {', '.join(agents)} ---[/dim]")

    def _on_group_complete(self, event: SchedulerEvent) -> None:
        pass  # 组完成在 individual agent 完成时已处理

    def _on_agent_start(self, event: SchedulerEvent) -> None:
        name = event.agent_name or "unknown"
        self._running_agents[name] = event.timestamp
        self._print(f"  * {name} started",
                    f"  [blue]●[/blue] [bold]{name}[/bold] [dim]started[/dim]")

    def _on_agent_complete(self, event: SchedulerEvent) -> None:
        name = event.agent_name or "unknown"
        self._running_agents.pop(name, None)
        self._completed_agents += 1

        duration_ms = event.data.get("duration_ms") if event.data else None
        duration_str = f" ({duration_ms}ms)" if duration_ms else ""

        self._print(f"  + {name} completed{duration_str}",
                    f"  [green]✓[/green] [bold]{name}[/bold] [dim]completed{duration_str}[/dim]")
        self._render_progress_bar()

    def _on_agent_fail(self, event: SchedulerEvent) -> None:
        name = event.agent_name or "unknown"
        self._running_agents.pop(name, None)
        self._failed_agents += 1

        error = event.data.get("error", "") if event.data else ""
        self._print(f"  ! {name} failed: {error}",
                    f"  [red]✗[/red] [bold]{name}[/bold] [red]failed: {error}[/red]")

    def _on_agent_retry(self, event: SchedulerEvent) -> None:
        name = event.agent_name or "unknown"
        attempt = event.data.get("attempt", "?") if event.data else "?"
        max_retries = event.data.get("max_retries", "?") if event.data else "?"
        self._print(f"  ~ {name} retry {attempt}/{max_retries}",
                    f"  [yellow]↻[/yellow] [bold]{name}[/bold] [yellow]retry {attempt}/{max_retries}[/yellow]")

    def _on_agent_skipped(self, event: SchedulerEvent) -> None:
        name = event.agent_name or "unknown"
        self._completed_agents += 1
        self._print(f"  - {name} skipped",
                    f"  [dim]⊙ {name} skipped[/dim]")

    def _render_progress_bar(self) -> None:
        """渲染进度条"""
        if self._total_agents <= 0:
            return

        done = self._completed_agents + self._failed_agents
        ratio = done / self._total_agents
        width = 30
        filled = int(ratio * width)
        empty = width - filled

        bar_plain = '#' * filled + '.' * empty
        bar_color = "green" if ratio >= 1.0 else "cyan" if ratio > 0.5 else "blue"
        bar_rich = f"[{bar_color}]{'#' * filled}[/{bar_color}][dim]{'.' * empty}[/dim]"

        failed_plain = f" {self._failed_agents} failed" if self._failed_agents > 0 else ""
        failed_rich = f" [red]{self._failed_agents} failed[/red]" if self._failed_agents > 0 else ""

        self._print(
            f"  Progress: [{bar_plain}] {ratio * 100:.0f}% ({done}/{self._total_agents}){failed_plain}",
            f"  Progress: [{bar_rich}] {ratio * 100:.0f}% ({done}/{self._total_agents}){failed_rich}",
        )


# ---------------------------------------------------------------------------
#  WorkflowRunner
# ---------------------------------------------------------------------------


class WorkflowRunner:
    """REPL 内工作流执行引擎。

    对齐 tui/cli.py 的 run_cmd 逻辑，但面向 REPL 环境：
    - 异步执行（不阻塞事件循环）
    - 事件驱动输出（通过 REPLOutputHandler）
    - 可取消（通过 asyncio.Task）
    """

    def __init__(
        self,
        tool_registry: Optional[ToolRegistry] = None,
        config_manager: Optional[Any] = None,
        output_handler: Optional[REPLOutputHandler] = None,
    ):
        """
        Args:
            tool_registry: 工具注册表。为 None 时创建默认注册表。
            config_manager: 配置管理器。为 None 时使用 core.config.config_manager。
            output_handler: 输出处理器。为 None 时创建默认处理器。
        """
        self._tool_registry = tool_registry or ToolRegistry()
        self._config_manager = config_manager
        self._output_handler = output_handler or REPLOutputHandler()

        self._current_task: Optional[asyncio.Task] = None
        self._current_scheduler: Optional[Scheduler] = None
        self._cancel_event = asyncio.Event()
        self._is_running = False
        self._last_result: Optional[ExecutionResult] = None

    @property
    def is_running(self) -> bool:
        """是否有正在执行的工作流"""
        return self._is_running

    @property
    def last_result(self) -> Optional[ExecutionResult]:
        """最后一次执行结果"""
        return self._last_result

    @property
    def output_handler(self) -> REPLOutputHandler:
        """输出处理器"""
        return self._output_handler

    # ------------------------------------------------------------------
    #  公共 API
    # ------------------------------------------------------------------

    async def run_workflow(
        self,
        file_path: str,
        task: Optional[str] = None,
        input_params: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> ExecutionResult:
        """解析 .gf 文件并执行工作流。

        Args:
            file_path: 工作流文件路径 (.gf / .af / .json)
            task: 任务描述，注入为 input_params["task"]
            input_params: 额外输入参数
            model: 模型名称（覆盖默认值）
            provider: LLM 提供商（覆盖默认值）

        Returns:
            ExecutionResult 执行结果

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 工作流解析失败
        """
        if self._is_running:
            raise RuntimeError("A workflow is already running. Call stop_workflow() first.")

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Workflow file not found: {file_path}")

        self._is_running = True
        self._cancel_event.clear()
        started_at = datetime.now()

        try:
            # 1. 解析文件
            workflow, components_dict = self._parse_workflow(file_path)

            # 2. 确定 model/provider
            effective_model, effective_provider = self._resolve_model_provider(model, provider)

            # 3. 注册内置工具
            register_builtin_tools(self._tool_registry)

            # 4. 创建 agents
            agents = self._create_agents(
                workflow, components_dict, effective_model, effective_provider
            )

            # 5. 合并输入参数
            merged_input = dict(input_params or {})
            if task:
                merged_input["task"] = task

            # 6. 计算 agent 数量并设置进度
            self._output_handler.set_total_agents(len(workflow.agents))

            # 7. 创建 Scheduler（带事件回调）
            scheduler = Scheduler(
                workflow,
                agents,
                workflow_input=merged_input,
                on_event=self._output_handler.handle,
            )
            self._current_scheduler = scheduler

            # 8. 执行
            context = WorkflowContext()
            execution_record = await scheduler.run(context)

            # 9. 保存执行记录
            self._save_execution(execution_record)

            completed_at = datetime.now()
            result = ExecutionResult(
                workflow_name=workflow.name,
                status="completed",
                execution_record=execution_record,
                context_data=context.to_dict(),
                started_at=started_at,
                completed_at=completed_at,
            )
            self._last_result = result
            return result

        except asyncio.CancelledError:
            completed_at = datetime.now()
            result = ExecutionResult(
                workflow_name=getattr(workflow, "name", "unknown") if "workflow" in dir() else "unknown",
                status="cancelled",
                error="Workflow execution was cancelled",
                started_at=started_at,
                completed_at=completed_at,
            )
            self._last_result = result
            return result

        except Exception as e:
            completed_at = datetime.now()
            result = ExecutionResult(
                workflow_name=getattr(workflow, "name", "unknown") if "workflow" in dir() else "unknown",
                status="failed",
                error=str(e),
                started_at=started_at,
                completed_at=completed_at,
            )
            self._last_result = result
            raise

        finally:
            self._is_running = False
            self._current_scheduler = None
            self._current_task = None

    async def stop_workflow(self) -> None:
        """取消正在运行的工作流。

        如果没有正在运行的工作流，则不做任何操作。
        """
        if not self._is_running:
            return

        self._cancel_event.set()

        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except (asyncio.CancelledError, Exception):
                pass

    def run_workflow_background(
        self,
        file_path: str,
        task: Optional[str] = None,
        input_params: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        on_complete: Optional[Callable[[ExecutionResult], None]] = None,
    ) -> asyncio.Task:
        """在后台 Task 中执行工作流（非阻塞）。

        Args:
            file_path: 工作流文件路径
            task: 任务描述
            input_params: 额外输入参数
            model: 模型名称
            provider: LLM 提供商
            on_complete: 完成回调（可选）

        Returns:
            asyncio.Task 实例
        """
        async def _run():
            try:
                result = await self.run_workflow(
                    file_path, task, input_params, model, provider
                )
                if on_complete:
                    on_complete(result)
                return result
            except Exception:
                if on_complete:
                    on_complete(self._last_result)
                raise

        self._current_task = asyncio.create_task(_run())
        return self._current_task

    # ------------------------------------------------------------------
    #  内部方法
    # ------------------------------------------------------------------

    def _parse_workflow(self, file_path: str):
        """解析工作流文件，返回 (workflow, components_dict)"""
        from tui.dsl_parser import parse_file_result

        parse_result = parse_file_result(file_path)

        if not parse_result.workflows:
            raise ValueError(f"No workflow found in {file_path}")

        workflow = parse_result.workflows[0]
        components_dict = {c.name: c for c in parse_result.components}
        return workflow, components_dict

    def _resolve_model_provider(
        self, model: Optional[str], provider: Optional[str]
    ) -> tuple:
        """解析 model 和 provider，返回 (effective_model, effective_provider)"""
        try:
            if self._config_manager:
                config = self._config_manager.load_config()
            else:
                from core.config import config_manager as cm
                config = cm.load_config()

            default_model = config.llm.default_model
            default_provider = config.llm.default_provider
        except Exception:
            default_model = "gpt-4"
            default_provider = "openai"

        effective_model = model or default_model
        effective_provider = provider or default_provider
        return effective_model, effective_provider

    def _resolve_model_for_provider(self, model_name: str, provider: str) -> str:
        """解析模型名称，如果当前 provider 中不存在该模型则回退到默认模型"""
        try:
            if self._config_manager:
                config = self._config_manager.load_config()
            else:
                from core.config import config_manager as cm
                config = cm.load_config()

            provider_config = config.provider.get(provider)
            if provider_config and provider_config.models:
                bare_name = model_name.split("/")[-1] if "/" in model_name else model_name
                if bare_name not in provider_config.models:
                    fallback = config.llm.default_model
                    logger.info(
                        "Model '%s' not found in provider '%s', falling back to: %s",
                        bare_name, provider, fallback,
                    )
                    return fallback
        except Exception:
            pass
        return model_name

    def _create_agents(
        self,
        workflow: Workflow,
        components_dict: Dict[str, Component],
        effective_model: str,
        effective_provider: str,
    ) -> Dict[str, Any]:
        """从 Workflow 创建 Agent 实例字典，对齐 cli.py 中的创建逻辑"""
        agents = {}

        for agent_instance in workflow.agents:
            component = self._resolve_component(
                agent_instance, components_dict, effective_model, effective_provider
            )

            # 判断是否是条件 Agent
            name_lower = agent_instance.name.lower()
            if "route" in name_lower or "condition" in name_lower:
                rules = agent_instance.overrides.get("rules", [])
                agent = ConditionAgent(component, rules=rules)
            else:
                # 根据 component 权限过滤工具
                if component.permission and (component.permission.allow or component.permission.deny):
                    agent_registry = create_filtered_registry(
                        self._tool_registry, component.permission
                    )
                else:
                    agent_registry = self._tool_registry
                agent = LLMAgent(component=component, tool_registry=agent_registry)

            agents[agent_instance.name] = agent

        return agents

    def _resolve_component(
        self,
        agent_instance: AgentInstance,
        components_dict: Dict[str, Component],
        effective_model: str,
        effective_provider: str,
    ) -> Component:
        """解析 AgentInstance 对应的 Component，对齐 cli.py 的解析逻辑"""
        if agent_instance.component and agent_instance.component in components_dict:
            component = copy.deepcopy(components_dict[agent_instance.component])
            # 应用 overrides
            for k, v in agent_instance.overrides.items():
                if k == "model" and isinstance(v, dict):
                    for mk, mv in v.items():
                        setattr(component.model, mk, mv)
                elif k == "model":
                    component.model.default = v
                elif hasattr(component, k):
                    setattr(component, k, v)
            # 解析模型
            if component.model.default:
                component.model.default = self._resolve_model_for_provider(
                    component.model.default, effective_provider
                )
        else:
            raw_model = agent_instance.overrides.get("model", effective_model)
            resolved_model = self._resolve_model_for_provider(raw_model, effective_provider)
            component = Component(
                name=agent_instance.name,
                system_prompt=agent_instance.inline_system_prompt or "",
                model=ModelConfig(default=resolved_model),
                ports=list(agent_instance.inline_ports),
            )

        return component

    def _save_execution(self, record: ExecutionRecord) -> None:
        """保存执行记录到数据库（失败不影响主流程）"""
        try:
            from core.db import execution_db
            execution_db.save_execution(record)
        except Exception:
            logger.debug("Failed to save execution record", exc_info=True)
