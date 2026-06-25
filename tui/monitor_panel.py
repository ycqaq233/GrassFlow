"""
GrassFlow 实时监控面板

参考 htop 风格，显示执行时的实时进度、日志、状态
"""

import asyncio
import time
from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass, field

try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
    from rich.tree import Tree
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from core.models import Workflow, ExecutionRecord, AgentExecutionRecord, ExecutionStatus
from core.context import WorkflowContext
from core.scheduler import Scheduler


@dataclass
class AgentStatus:
    """Agent 状态"""
    name: str
    status: str = "pending"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    output_preview: Optional[str] = None


@dataclass
class MonitorState:
    """监控状态"""
    workflow_name: str
    total_agents: int
    completed_agents: int = 0
    failed_agents: int = 0
    running_agents: int = 0
    pending_agents: int = 0
    started_at: Optional[datetime] = None
    agents: Dict[str, AgentStatus] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)


class MonitorPanel:
    """实时监控面板"""

    def __init__(self, console: Optional[Any] = None):
        """初始化监控面板"""
        if HAS_RICH:
            self.console = console or Console()
        else:
            self.console = None

    def create_layout(self, state: MonitorState) -> Optional[Any]:
        """创建布局"""
        if not HAS_RICH:
            return None

        layout = Layout()

        # 分割布局
        layout.split(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=10),
        )

        # body 分为左右两部分
        layout["body"].split_row(
            Layout(name="agents", ratio=2),
            Layout(name="progress", ratio=1),
        )

        # 设置各个部分的内容
        layout["header"].update(self._create_header(state))
        layout["agents"].update(self._create_agents_table(state))
        layout["progress"].update(self._create_progress_panel(state))
        layout["footer"].update(self._create_logs_panel(state))

        return layout

    def _create_header(self, state: MonitorState) -> Any:
        """创建头部"""
        status_text = Text()
        status_text.append("Workflow: ", style="bold")
        status_text.append(state.workflow_name, style="cyan")
        status_text.append("  |  ")
        status_text.append("Status: ", style="bold")

        if state.failed_agents > 0:
            status_text.append("FAILED", style="bold red")
        elif state.completed_agents == state.total_agents:
            status_text.append("COMPLETED", style="bold green")
        elif state.running_agents > 0:
            status_text.append("RUNNING", style="bold yellow")
        else:
            status_text.append("PENDING", style="dim")

        return Panel(status_text, title="GrassFlow Monitor", border_style="blue")

    def _create_agents_table(self, state: MonitorState) -> Any:
        """创建 Agent 表格"""
        table = Table(show_header=True, header_style="bold magenta", show_lines=True)
        table.add_column("Agent", style="cyan", min_width=15)
        table.add_column("Status", style="yellow", min_width=10)
        table.add_column("Duration", style="blue", min_width=10)
        table.add_column("Details", style="dim")

        for agent_name, agent_status in state.agents.items():
            # 状态颜色
            status_color = {
                "pending": "dim",
                "running": "yellow",
                "completed": "green",
                "failed": "red",
                "skipped": "dim",
            }.get(agent_status.status, "white")

            # 状态图标
            status_icon = {
                "pending": "⏳",
                "running": "🔄",
                "completed": "✅",
                "failed": "❌",
                "skipped": "⏭️",
            }.get(agent_status.status, "❓")

            duration = f"{agent_status.duration_ms}ms" if agent_status.duration_ms else "..."
            details = agent_status.error or agent_status.output_preview or ""

            table.add_row(
                agent_name,
                f"[{status_color}]{status_icon} {agent_status.status}[/{status_color}]",
                duration,
                details[:50] if details else "",
            )

        return Panel(table, title="Agents", border_style="green")

    def _create_progress_panel(self, state: MonitorState) -> Any:
        """创建进度面板"""
        # 计算进度
        progress_pct = (state.completed_agents / state.total_agents * 100) if state.total_agents > 0 else 0

        # 创建进度条
        progress_text = Text()
        progress_text.append(f"\n  Completed: ", style="bold")
        progress_text.append(f"{state.completed_agents}/{state.total_agents}", style="green")
        progress_text.append(f"\n  Progress: ", style="bold")
        progress_text.append(f"{progress_pct:.1f}%", style="cyan")

        if state.started_at:
            elapsed = (datetime.now() - state.started_at).total_seconds()
            progress_text.append(f"\n  Elapsed: ", style="bold")
            progress_text.append(f"{elapsed:.1f}s", style="blue")

        # 统计信息
        progress_text.append(f"\n\n  Statistics:", style="bold")
        progress_text.append(f"\n    Running: ", style="dim")
        progress_text.append(f"{state.running_agents}", style="yellow")
        progress_text.append(f"\n    Completed: ", style="dim")
        progress_text.append(f"{state.completed_agents}", style="green")
        progress_text.append(f"\n    Failed: ", style="dim")
        progress_text.append(f"{state.failed_agents}", style="red")
        progress_text.append(f"\n    Pending: ", style="dim")
        progress_text.append(f"{state.pending_agents}", style="dim")

        return Panel(progress_text, title="Progress", border_style="yellow")

    def _create_logs_panel(self, state: MonitorState) -> Any:
        """创建日志面板"""
        logs_text = Text()

        # 显示最近的日志
        recent_logs = state.logs[-8:] if len(state.logs) > 8 else state.logs
        for log in recent_logs:
            logs_text.append(log + "\n", style="dim")

        if not recent_logs:
            logs_text.append("  No logs yet...", style="dim")

        return Panel(logs_text, title="Logs", border_style="dim")

    def update_state(self, state: MonitorState, agent_name: str, status: str, **kwargs) -> None:
        """更新状态"""
        if agent_name not in state.agents:
            state.agents[agent_name] = AgentStatus(name=agent_name)

        agent = state.agents[agent_name]
        agent.status = status

        if status == "running":
            agent.started_at = datetime.now()
            state.running_agents += 1
            state.pending_agents = max(0, state.pending_agents - 1)
            state.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {agent_name} started")

        elif status == "completed":
            agent.completed_at = datetime.now()
            if agent.started_at:
                agent.duration_ms = int((agent.completed_at - agent.started_at).total_seconds() * 1000)
            state.completed_agents += 1
            state.running_agents = max(0, state.running_agents - 1)
            state.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {agent_name} completed ({agent.duration_ms}ms)")

            if "output" in kwargs:
                output_str = str(kwargs["output"])
                agent.output_preview = output_str[:100] + "..." if len(output_str) > 100 else output_str

        elif status == "failed":
            agent.completed_at = datetime.now()
            if agent.started_at:
                agent.duration_ms = int((agent.completed_at - agent.started_at).total_seconds() * 1000)
            agent.error = kwargs.get("error", "Unknown error")
            state.failed_agents += 1
            state.running_agents = max(0, state.running_agents - 1)
            state.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {agent_name} failed: {agent.error}")


def execute_with_monitor(scheduler: Scheduler, context: WorkflowContext, workflow: Workflow) -> ExecutionRecord:
    """带监控面板执行工作流"""
    if not HAS_RICH:
        # 如果没有 Rich，直接执行
        return asyncio.run(scheduler.run(context))

    from rich.live import Live

    # 初始化状态
    state = MonitorState(
        workflow_name=workflow.name,
        total_agents=len(workflow.agents),
        pending_agents=len(workflow.agents),
        started_at=datetime.now(),
    )

    # 初始化 Agent 状态
    for agent_config in workflow.agents:
        state.agents[agent_config.name] = AgentStatus(name=agent_config.name)

    panel = MonitorPanel()

    # 使用 Live 实时更新
    with Live(panel.create_layout(state), refresh_per_second=4, console=Console()) as live:
        # 包装调度器以捕获事件
        original_execute_agent = scheduler._execute_agent

        async def monitored_execute_agent(agent_name: str, context: WorkflowContext):
            """带监控的执行 Agent"""
            panel.update_state(state, agent_name, "running")
            live.update(panel.create_layout(state))

            try:
                result = await original_execute_agent(agent_name, context)
                panel.update_state(state, agent_name, "completed", output=result)
                live.update(panel.create_layout(state))
                return result
            except Exception as e:
                panel.update_state(state, agent_name, "failed", error=str(e))
                live.update(panel.create_layout(state))
                raise

        # 替换执行方法
        scheduler._execute_agent = monitored_execute_agent

        # 执行工作流
        result = asyncio.run(scheduler.run(context))

        # 更新最终状态
        if result.status == ExecutionStatus.COMPLETED:
            state.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] Workflow completed successfully!")
        else:
            state.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] Workflow failed: {result.error}")

        live.update(panel.create_layout(state))
        time.sleep(1)  # 让用户看到最终状态

    return result
