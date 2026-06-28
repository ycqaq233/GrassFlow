"""
GrassFlow 实时监控面板

基于 Scheduler 事件回调的实时监控，支持：
- 嵌入模式：在 REPL 中内联显示
- 全屏模式：独立的 htop 风格面板
- 连接线动画（完成时变绿，失败时变红）
- Port 数据预览（显示传递的数据摘要）
"""

import asyncio
import time
from typing import Dict, Any, Optional, List, Callable, Set
from datetime import datetime
from dataclasses import dataclass, field

try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.progress_bar import ProgressBar
    from rich.tree import Tree
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from core.models import Workflow, Connection
from core.execution import ExecutionRecord, AgentExecutionRecord, ExecutionStatus
from core.context import WorkflowContext
from core.scheduler import Scheduler, SchedulerEvent, SchedulerEventType


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class AgentStatus:
    """单个 Agent 的运行时状态"""
    name: str
    status: str = "pending"          # pending / running / completed / failed / skipped / retrying
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    output_preview: Optional[str] = None
    input_preview: Optional[str] = None
    retry_attempt: int = 0
    max_retries: int = 0
    group_index: int = -1            # 所属并行组索引


@dataclass
class ConnectionStatus:
    """连接线状态"""
    source: str
    target: str
    status: str = "pending"          # pending / active / completed / failed


@dataclass
class MonitorState:
    """监控面板的完整状态"""
    workflow_name: str
    total_agents: int = 0
    completed_agents: int = 0
    failed_agents: int = 0
    running_agents: int = 0
    pending_agents: int = 0
    skipped_agents: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    agents: Dict[str, AgentStatus] = field(default_factory=dict)
    connections: List[ConnectionStatus] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    is_running: bool = False
    is_failed: bool = False
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# 面板渲染器
# ---------------------------------------------------------------------------

class MonitorPanel:
    """实时监控面板 — 渲染 + 事件处理"""

    def __init__(self, console: Optional[Any] = None):
        if HAS_RICH:
            self.console = console or Console()
        else:
            self.console = None

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def create_state(self, workflow: Workflow) -> MonitorState:
        """从 Workflow 定义创建初始 MonitorState"""
        state = MonitorState(
            workflow_name=workflow.name,
            total_agents=len(workflow.agents),
            pending_agents=len(workflow.agents),
            started_at=datetime.now(),
            is_running=True,
        )
        for ai in workflow.agents:
            state.agents[ai.name] = AgentStatus(name=ai.name)

        # 记录连接
        for conn in workflow.connections:
            for target in conn.target_agents:
                state.connections.append(
                    ConnectionStatus(source=conn.source_agent, target=target)
                )
        return state

    def register_scheduler(self, scheduler: Scheduler, state: MonitorState) -> None:
        """注册 Scheduler 事件回调 — 不再猴子补丁

        Args:
            scheduler: 已初始化的 Scheduler 实例
            state: 共享的 MonitorState
        """
        def _handler(event: SchedulerEvent) -> None:
            self.on_event(event, state)
        # Scheduler.__init__ 接受 on_event 参数；如果已设置则链式调用
        existing = scheduler._on_event
        def _chained(event: SchedulerEvent) -> None:
            if existing is not None:
                try:
                    existing(event)
                except Exception:
                    pass
            _handler(event)
        scheduler._on_event = _chained

    def on_event(self, event: SchedulerEvent, state: MonitorState) -> None:
        """统一事件处理器 — 将 SchedulerEvent 翻译为状态更新"""
        et = event.event_type
        name = event.agent_name
        data = event.data or {}

        if et == SchedulerEventType.WORKFLOW_START:
            state.is_running = True
            state.started_at = event.timestamp
            self._log(state, "Workflow started")

        elif et == SchedulerEventType.WORKFLOW_COMPLETE:
            state.is_running = False
            state.completed_at = event.timestamp
            self._log(state, "Workflow completed successfully!")

        elif et == SchedulerEventType.WORKFLOW_FAILED:
            state.is_running = False
            state.is_failed = True
            state.error = data.get("error", "Unknown error")
            state.completed_at = event.timestamp
            self._log(state, f"Workflow failed: {state.error}")

        elif et == SchedulerEventType.GROUP_START:
            agents = data.get("agents", [])
            for a in agents:
                if a in state.agents:
                    self._update_agent_status(state, a, "pending")
            self._log(state, f"Group started: {', '.join(agents)}")

        elif et == SchedulerEventType.GROUP_COMPLETE:
            self._log(state, "Group completed")

        elif et == SchedulerEventType.AGENT_START:
            if name and name in state.agents:
                self._update_agent_status(state, name, "running",
                                          started_at=event.timestamp)
                self._log(state, f"{name} started")
                # 激活入边连接
                self._activate_incoming_connections(state, name)

        elif et == SchedulerEventType.AGENT_COMPLETE:
            if name and name in state.agents:
                output = data.get("output")
                duration = data.get("duration_ms")
                self._update_agent_status(state, name, "completed",
                                          completed_at=event.timestamp,
                                          duration_ms=duration,
                                          output=output)
                self._log(state, f"{name} completed ({duration}ms)")
                self._complete_outgoing_connections(state, name)

        elif et == SchedulerEventType.AGENT_FAIL:
            if name and name in state.agents:
                error = data.get("error", "Unknown error")
                duration = data.get("duration_ms")
                self._update_agent_status(state, name, "failed",
                                          completed_at=event.timestamp,
                                          duration_ms=duration,
                                          error=error)
                self._log(state, f"{name} failed: {error}")
                self._fail_outgoing_connections(state, name)

        elif et == SchedulerEventType.AGENT_RETRY:
            if name and name in state.agents:
                attempt = data.get("attempt", 0)
                max_retries = data.get("max_retries", 0)
                agent = state.agents[name]
                agent.retry_attempt = attempt
                agent.max_retries = max_retries
                agent.status = "retrying"
                self._log(state, f"{name} retrying ({attempt}/{max_retries})")

        elif et == SchedulerEventType.AGENT_SKIPPED:
            if name and name in state.agents:
                self._update_agent_status(state, name, "skipped")
                self._log(state, f"{name} skipped")

    # ------------------------------------------------------------------
    # 布局渲染
    # ------------------------------------------------------------------

    def render(self, state: MonitorState) -> Any:
        """渲染完整布局（返回 Rich renderable）"""
        if not HAS_RICH:
            return self._render_plain(state)

        layout = Layout()
        layout.split(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=10),
        )
        layout["body"].split_row(
            Layout(name="agents", ratio=2),
            Layout(name="sidebar", ratio=1),
        )
        layout["sidebar"].split(
            Layout(name="progress", size=12),
            Layout(name="connections"),
        )

        layout["header"].update(self._render_header(state))
        layout["agents"].update(self._render_agents_table(state))
        layout["progress"].update(self._render_progress_panel(state))
        layout["connections"].update(self._render_connections_panel(state))
        layout["footer"].update(self._render_logs_panel(state))

        return layout

    def render_compact(self, state: MonitorState) -> Any:
        """渲染紧凑布局（嵌入 REPL 模式）"""
        if not HAS_RICH:
            return self._render_plain(state)

        layout = Layout()
        layout.split(
            Layout(name="header", size=3),
            Layout(name="body"),
        )
        layout["body"].split_row(
            Layout(name="agents", ratio=3),
            Layout(name="progress", ratio=1),
        )

        layout["header"].update(self._render_header(state))
        layout["agents"].update(self._render_agents_table(state))
        layout["progress"].update(self._render_progress_panel(state))

        return layout

    # ------------------------------------------------------------------
    # 执行入口
    # ------------------------------------------------------------------

    def execute(
        self,
        scheduler: Scheduler,
        context: WorkflowContext,
        workflow: Workflow,
        *,
        fullscreen: bool = False,
        refresh_per_second: int = 4,
    ) -> ExecutionRecord:
        """带监控面板执行工作流

        Args:
            scheduler: Scheduler 实例
            context: WorkflowContext
            workflow: Workflow 定义
            fullscreen: True = 全屏 htop 风格；False = 嵌入模式
            refresh_per_second: 刷新频率

        Returns:
            ExecutionRecord
        """
        if not HAS_RICH:
            return asyncio.run(scheduler.run(context))

        state = self.create_state(workflow)
        self.register_scheduler(scheduler, state)

        render_fn = self.render if fullscreen else self.render_compact

        with Live(render_fn(state), refresh_per_second=refresh_per_second,
                  console=self.console, screen=fullscreen) as live:
            # 定义一个周期性刷新回调，确保面板持续更新
            _original_handler = scheduler._on_event

            def _live_handler(event: SchedulerEvent) -> None:
                _original_handler(event)
                live.update(render_fn(state))

            scheduler._on_event = _live_handler

            result = asyncio.run(scheduler.run(context))

            # 最终状态更新
            if result.status == ExecutionStatus.COMPLETED:
                state.is_running = False
            elif result.status == ExecutionStatus.FAILED:
                state.is_running = False
                state.is_failed = True
                state.error = result.error

            live.update(render_fn(state))
            time.sleep(1)  # 让用户看到最终状态

        return result

    # ------------------------------------------------------------------
    # 数据收集
    # ------------------------------------------------------------------

    def get_progress(self, state: MonitorState) -> float:
        """返回完成百分比 0.0 ~ 1.0"""
        if state.total_agents == 0:
            return 0.0
        done = state.completed_agents + state.skipped_agents
        return done / state.total_agents

    def get_timeline(self, state: MonitorState) -> List[Dict[str, Any]]:
        """返回执行时间线"""
        events = []
        for name, agent in state.agents.items():
            events.append({
                "agent": name,
                "status": agent.status,
                "started_at": agent.started_at.isoformat() if agent.started_at else None,
                "completed_at": agent.completed_at.isoformat() if agent.completed_at else None,
                "duration_ms": agent.duration_ms,
                "error": agent.error,
            })
        return events

    def get_data_summary(self, state: MonitorState) -> Dict[str, Dict[str, str]]:
        """返回每个 agent 的输入/输出摘要"""
        summary = {}
        for name, agent in state.agents.items():
            summary[name] = {
                "input": agent.input_preview or "",
                "output": agent.output_preview or "",
                "error": agent.error or "",
            }
        return summary

    # ------------------------------------------------------------------
    # 内部渲染方法
    # ------------------------------------------------------------------

    def _render_header(self, state: MonitorState) -> Any:
        text = Text()
        text.append("  Workflow: ", style="bold")
        text.append(state.workflow_name, style="cyan")
        text.append("  |  Status: ", style="bold")

        if state.is_failed:
            text.append("FAILED", style="bold red")
        elif not state.is_running and state.completed_agents + state.skipped_agents >= state.total_agents:
            text.append("COMPLETED", style="bold green")
        elif state.is_running:
            text.append("RUNNING", style="bold yellow")
        else:
            text.append("PENDING", style="dim")

        if state.started_at:
            elapsed = (state.completed_at or datetime.now()) - state.started_at
            text.append(f"  |  Elapsed: {elapsed.total_seconds():.1f}s", style="dim")

        return Panel(text, title="[bold]GrassFlow Monitor[/bold]", border_style="blue")

    def _render_agents_table(self, state: MonitorState) -> Any:
        table = Table(
            show_header=True, header_style="bold magenta",
            show_lines=True, box=box.ROUNDED,
            expand=True,
        )
        table.add_column("Agent", style="cyan", min_width=14)
        table.add_column("Status", min_width=12)
        table.add_column("Duration", style="blue", min_width=10)
        table.add_column("Data Preview", style="dim", ratio=1)

        for agent in state.agents.values():
            status_style, status_icon = self._status_style(agent.status)

            duration = self._format_duration(agent)
            detail = self._build_detail(agent)

            table.add_row(
                agent.name,
                f"[{status_style}]{status_icon} {agent.status}[/{status_style}]",
                duration,
                detail,
            )

        return Panel(table, title="[bold]Agents[/bold]", border_style="green")

    def _render_progress_panel(self, state: MonitorState) -> Any:
        pct = self.get_progress(state) * 100
        bar_width = 20
        filled = int(pct / 100 * bar_width)
        bar = "[green]" + "#" * filled + "[/green]" + "[dim]" + "-" * (bar_width - filled) + "[/dim]"

        text = Text()
        text.append(f"\n  {bar} {pct:.0f}%\n", style="bold")
        text.append(f"\n  Completed:  ", style="bold")
        text.append(f"{state.completed_agents}/{state.total_agents}", style="green")
        text.append(f"\n  Running:    ", style="bold")
        text.append(f"{state.running_agents}", style="yellow")
        text.append(f"\n  Failed:     ", style="bold")
        text.append(f"{state.failed_agents}", style="red" if state.failed_agents else "dim")
        text.append(f"\n  Skipped:    ", style="bold")
        text.append(f"{state.skipped_agents}", style="dim")
        text.append(f"\n  Pending:    ", style="bold")
        text.append(f"{state.pending_agents}", style="dim")

        if state.started_at:
            elapsed = (state.completed_at or datetime.now()) - state.started_at
            text.append(f"\n\n  Elapsed:    ", style="bold")
            text.append(f"{elapsed.total_seconds():.1f}s", style="blue")

        return Panel(text, title="[bold]Progress[/bold]", border_style="yellow")

    def _render_connections_panel(self, state: MonitorState) -> Any:
        """渲染连接状态面板"""
        if not state.connections:
            return Panel(Text("  No connections", style="dim"),
                         title="[bold]Connections[/bold]", border_style="cyan")

        text = Text()
        for conn in state.connections:
            icon, style = self._connection_style(conn.status)
            arrow = f"{conn.source} {icon} {conn.target}"
            text.append(f"  {arrow}\n", style=style)

        return Panel(text, title="[bold]Connections[/bold]", border_style="cyan")

    def _render_logs_panel(self, state: MonitorState) -> Any:
        text = Text()
        recent = state.logs[-8:] if len(state.logs) > 8 else state.logs
        for log in recent:
            # 简单的着色
            if "failed" in log.lower():
                text.append(log + "\n", style="red")
            elif "completed" in log.lower():
                text.append(log + "\n", style="green")
            elif "started" in log.lower():
                text.append(log + "\n", style="yellow")
            else:
                text.append(log + "\n", style="dim")

        if not recent:
            text.append("  No logs yet...", style="dim")

        return Panel(text, title="[bold]Logs[/bold]", border_style="dim")

    def _render_plain(self, state: MonitorState) -> str:
        """纯文本回退"""
        lines = [f"=== {state.workflow_name} ==="]
        for agent in state.agents.values():
            lines.append(f"  {agent.name}: {agent.status}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 状态更新内部方法
    # ------------------------------------------------------------------

    def _update_agent_status(
        self,
        state: MonitorState,
        agent_name: str,
        status: str,
        *,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        duration_ms: Optional[int] = None,
        output: Any = None,
        error: Optional[str] = None,
    ) -> None:
        agent = state.agents[agent_name]
        old_status = agent.status
        agent.status = status

        if started_at:
            agent.started_at = started_at
        if completed_at:
            agent.completed_at = completed_at
        if duration_ms is not None:
            agent.duration_ms = duration_ms
        if error:
            agent.error = error
        if output is not None:
            preview = str(output)
            agent.output_preview = preview[:100] + "..." if len(preview) > 100 else preview

        # 更新计数器（先减旧状态，再加新状态）
        self._adjust_counters(state, old_status, -1)
        self._adjust_counters(state, status, +1)

    def _adjust_counters(self, state: MonitorState, status: str, delta: int) -> None:
        if status == "running":
            state.running_agents = max(0, state.running_agents + delta)
        elif status == "completed":
            state.completed_agents = max(0, state.completed_agents + delta)
        elif status == "failed":
            state.failed_agents = max(0, state.failed_agents + delta)
        elif status == "skipped":
            state.skipped_agents = max(0, state.skipped_agents + delta)
        elif status == "pending":
            state.pending_agents = max(0, state.pending_agents + delta)

    def _activate_incoming_connections(self, state: MonitorState, target: str) -> None:
        for conn in state.connections:
            if conn.target == target and conn.status == "pending":
                conn.status = "active"

    def _complete_outgoing_connections(self, state: MonitorState, source: str) -> None:
        for conn in state.connections:
            if conn.source == source and conn.status == "active":
                conn.status = "completed"

    def _fail_outgoing_connections(self, state: MonitorState, source: str) -> None:
        for conn in state.connections:
            if conn.source == source and conn.status == "active":
                conn.status = "failed"

    def _log(self, state: MonitorState, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        state.logs.append(f"[{ts}] {message}")

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _status_style(status: str) -> tuple:
        """返回 (style, icon)"""
        mapping = {
            "pending":   ("dim",    "⏳"),  # hourglass
            "running":   ("yellow", "\U0001f504"),  # counterclockwise arrows
            "completed": ("green",  "✅"),  # check mark
            "failed":    ("red",    "❌"),  # cross mark
            "skipped":   ("dim",    "⏭️"),  # skip
            "retrying":  ("yellow", "\U0001f501"),  # repeat
        }
        return mapping.get(status, ("white", "❓"))

    @staticmethod
    def _connection_style(status: str) -> tuple:
        """返回 (icon, style)"""
        mapping = {
            "pending":   ("───", "dim"),        # ---
            "active":    ("▶──", "yellow"),     # >--
            "completed": ("✔──", "green"),      # check--
            "failed":    ("✖──", "red"),        # x--
        }
        return mapping.get(status, ("───", "dim"))

    @staticmethod
    def _format_duration(agent: AgentStatus) -> str:
        if agent.duration_ms is not None:
            if agent.duration_ms < 1000:
                return f"{agent.duration_ms}ms"
            return f"{agent.duration_ms / 1000:.1f}s"
        if agent.started_at and agent.status == "running":
            elapsed = (datetime.now() - agent.started_at).total_seconds()
            return f"{elapsed:.1f}s..."
        return "..."

    @staticmethod
    def _build_detail(agent: AgentStatus) -> str:
        parts = []
        if agent.error:
            parts.append(f"[red]{agent.error[:60]}[/red]")
        if agent.output_preview:
            parts.append(agent.output_preview[:60])
        if agent.retry_attempt > 0:
            parts.append(f"[yellow]retry {agent.retry_attempt}/{agent.max_retries}[/yellow]")
        return " | ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

def execute_with_monitor(
    scheduler: Scheduler,
    context: WorkflowContext,
    workflow: Workflow,
    *,
    fullscreen: bool = False,
) -> ExecutionRecord:
    """便捷入口 — 带监控面板执行工作流

    Args:
        scheduler: Scheduler 实例（已包含 on_event 或未设置均可）
        context: WorkflowContext
        workflow: Workflow 定义
        fullscreen: True = 全屏 htop 风格；False = 嵌入模式

    Returns:
        ExecutionRecord
    """
    panel = MonitorPanel()
    return panel.execute(scheduler, context, workflow, fullscreen=fullscreen)
